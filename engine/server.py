"""Engine entry point: WebSocket server plus the main loop.

Run with `uv run server.py` from engine/. The engine holds all state; UI
windows are views that can connect and disconnect at any time.
"""

import asyncio
import dataclasses
import itertools
import logging
import os
import time
from collections import deque

from pydantic import ValidationError
from websockets.asyncio.server import ServerConnection, broadcast, serve
from websockets.exceptions import ConnectionClosed

import numpy as np

from commander.agent import Commander
from commander.briefings import BriefingQueue, ForecastWatcher, round_summary
from commander.listen import Listener, vocabulary_prompt
from commander.voice import MacVoice, speakable
from commander.tools import CommanderTools
from forecast.recommend import PlacedCrew, Rec, Recommender, TownInfo, describe
from forecast.runner import HORIZONS_MIN, Forecast, Forecaster
from protocol import (
    AcceptRecommendation,
    BinaryType,
    CommanderKind,
    CommanderMessage,
    CommanderQuery,
    CommanderSpeech,
    CameraState,
    EndRound,
    Event,
    EventKind,
    Events,
    Hello,
    Ignite,
    PttStart,
    PttStop,
    Reset,
    ResourceUse,
    RoundPhase,
    ScenarioState,
    Score,
    SetRunning,
    SetSpeed,
    SetVoice,
    SetWind,
    StartRound,
    StepOnce,
    Token,
    TokenType,
    Transcript,
    VoiceMode,
    Tokens,
    TokenSource,
    VirtualTokenAdd,
    VirtualTokenMove,
    VirtualTokenRemove,
    VisionStatus,
    TownScore,
    VirtualTokenAdd,
    VirtualTokenMove,
    VirtualTokenRemove,
    WaterCooldown,
    WindState,
    client_message_adapter,
    RecAction,
    Recommendation,
    Recommendations,
    pack_binary,
)
from protocol import TownEffect as TownEffectInfo
from protocol import TownShare as TownShareInfo
from routing.evac import Route, burning_edges, plan_routes, replan_routes, routes_message
from routing.tracker import RouteTracker
from routing.roads import load_network
from scenario import load_scenario
from sim.effects import CREW_RADIUS, TokenEffects
from sim.fire import BURNING, SIM_MINUTES_PER_TICK, FireSim, Wind
from sim.game import Game, GameTown
from vision import camera
from vision.tokens import TokenTracker
from vision.virtual import VirtualTable

HOST = os.environ.get("ENGINE_HOST", "localhost")
PORT = int(os.environ.get("ENGINE_PORT", "8765"))
SCENARIO = os.environ.get("SCENARIO", "paradise")
CAMERA = os.environ.get("CAMERA", "")  # see vision/camera.py; empty = virtual table only
# Any web page open in a browser can connect to ws://localhost, so only the
# app's own pages may: Vite in dev (and Tauri dev, which loads it) and the
# built Tauri app. Comma-separated, to add e.g. a LAN address.
ENGINE_ORIGINS = os.environ.get(
    "ENGINE_ORIGINS", "http://localhost:1420,http://127.0.0.1:1420,tauri://localhost,http://tauri.localhost"
)
TICK_HZ = 10
# Don't restart the forecaster more often than this, or a map with no fire
# (where a forecast is instant) would round-trip the worker every tick.
FORECAST_MIN_TICKS = 3
# Recommendations rerun at most this often (a run is ~0.3 s in its own worker).
RECOMMEND_MIN_TICKS = 20
SQ_M_PER_ACRE = 4046.86

log = logging.getLogger("engine")


class Engine:
    def __init__(self) -> None:
        self.clients: set[ServerConnection] = set()
        self.tick = 0
        self.scenario = load_scenario(SCENARIO)
        self.tracker = TokenTracker()
        self.virtual = VirtualTable(self.tracker, self.scenario.width, self.scenario.height)
        self._sent_token_version = -1
        self.camera = camera.from_env(CAMERA, self.scenario)
        self._sent_feed_seq = 0
        self.fire = FireSim(self.scenario)
        self.effects = TokenEffects(self.scenario.width, self.scenario.height)
        self.forecaster = Forecaster()
        self._forecast_job: asyncio.Future[Forecast] | None = None
        self._forecast_started = -FORECAST_MIN_TICKS
        # Bumped on reset, so a forecast that was in flight when the map was
        # reset is dropped rather than shown over the fresh map.
        self._fire_epoch = 0
        # The newest finished forecast, or None before the first one (and
        # after a reset). Routing and the commander read it from here:
        # .tick is the sim tick it started from; .first_burn is float32
        # (N, H, W) ticks-after-.tick until each cell burns (inf = not by the
        # last horizon); .probability is float32 (len(HORIZONS_MIN), H, W).
        self.latest_forecast: Forecast | None = None
        # Evacuation routes (PLAN.md, Evacuation routing), replanned off the
        # tick loop whenever a forecast lands. No road layer means no routes.
        s = self.scenario
        self.roads = load_network(s.dir, s.width, s.height)
        self.route_tracker = RouteTracker()
        # Plan once here (no fire yet, so plain shortest paths). This also
        # builds the graph's lazy caches before any worker thread touches it.
        self.routes: list[Route] = []
        if self.roads is not None:
            self.routes, _ = self.route_tracker.choose(plan_routes(self.roads, None), {}, 0)
        self._routes_tick = 0
        self._route_job: asyncio.Task | None = None
        self._route_pending = False
        # Road edges with a cell burning right now, checked every tick so a
        # road the fire reaches between forecasts closes immediately.
        self._closed = np.zeros(len(self.roads.edges) if self.roads else 0, bool)
        self._bus_signature: tuple = ()
        # The last few events, for the commander's tools and briefings.
        self.recent_events: deque[Event] = deque(maxlen=20)
        # Crew recommendations, from their own worker after a forecast lands.
        self.recommender = Recommender()
        self.towns = [TownInfo(t.name, t.x, t.y, t.radius, t.population) for t in self.roads.towns] if self.roads else []
        self.recs: list[Recommendation] = []
        self._recs_tick = 0
        self._rec_job: asyncio.Future[list[Rec]] | None = None
        self._rec_started = -RECOMMEND_MIN_TICKS
        # Resource limits, scoring and rounds (sim/game.py). Towns come from the
        # road layer's towns.json, so no road layer means nothing to score.
        game_towns = [
            GameTown(t.name, t.x, t.y, t.radius, t.population, t.structures) for t in self.roads.towns
        ] if self.roads else []
        self.game = Game(self.scenario, game_towns)
        # Pause and speed (#54). Speed is sim steps per engine tick; the
        # fractional part carries over, so 0.5 steps every other tick.
        self.paused = False
        self.speed = 1.0
        self._step_budget = 0.0
        self._sent_inactive: list[str] = []
        # The incident commander: tools over this engine, plus unprompted
        # briefings from forecast and route events (no LLM needed for those).
        self.tools = CommanderTools(self)
        self.watcher = ForecastWatcher()
        self.briefings = BriefingQueue()
        self.commander = Commander(self.tools)
        self._query_task: asyncio.Task | None = None
        # Voice is off until a console turns it on (commander/voice.py).
        self.voice_mode = VoiceMode.OFF
        self.mac_voice = MacVoice()
        self._utterances = itertools.count(1)
        # Push-to-talk: the engine records and transcribes (commander/listen.py).
        exits = [z.name for z in self.roads.safe_zones] if self.roads else []
        roads = [speakable(n[n.index("(") + 1 : -1]) for n in exits if n.endswith(")")]
        roads = [r if r.startswith(("Highway", "State")) else ("the " + r if " " not in r else r) for r in roads]
        self.listener = Listener(vocabulary_prompt([t.name for t in self.towns], roads))

    def hello_msg(self) -> str:
        s = self.scenario
        return Hello(
            scenario=s.name,
            crew_radius=CREW_RADIUS,
            map_width=s.width,
            map_height=s.height,
            sim_minutes_per_tick=SIM_MINUTES_PER_TICK,
            forecast_horizons_min=list(HORIZONS_MIN),
            speech_to_text=self.listener.available,
        ).model_dump_json()

    def tokens_msg(self) -> str:
        return Tokens(tokens=self.tracker.tokens).model_dump_json()

    def state_msg(self) -> str:
        burning, burned = self.fire.counts()
        w = self.fire.wind
        return ScenarioState(
            tick=self.tick,
            running=not (self.paused or self.game.frozen),
            paused=self.paused,
            speed=self.speed,
            wind=WindState(speed_ms=w.speed_ms, from_deg=w.from_deg),
            burning_cells=burning,
            burned_cells=burned,
        ).model_dump_json()

    def score_msg(self) -> str:
        return self.score().model_dump_json()

    def score(self) -> Score:
        g, tick = self.game, self.fire.tick
        sandbox = g.phase == RoundPhase.SANDBOX
        types = {t.token_type for t in self.tracker.tokens} | set(g.limits)
        return Score(
            tick=tick,
            phase=g.phase,
            end_reason=g.end_reason,
            elapsed_min=g.elapsed_min(tick),
            duration_min=g.config["duration_min"],
            resources=[
                ResourceUse(token_type=t, limit=None if sandbox else g.limits.get(t), used=g.used.get(t, 0))
                for t in sorted(types)
            ],
            inactive_tokens=g.inactive,
            water_cooldowns=[
                WaterCooldown(id=k, ready_in_min=v * SIM_MINUTES_PER_TICK)
                for k, v in self.effects.water_ready_in(tick).items()
            ],
            people_total=sum(t.population for t in g.towns),
            people_evacuated=round(sum(g.evacuated)),
            structures_total=sum(t.structures for t in g.towns),
            structures_lost=sum(g.structures_lost),
            acres_burned=round(g.acres_burned, 1),
            towns=[
                TownScore(name=t.name, population=t.population, evacuated=round(e),
                          structures=t.structures, structures_lost=lost)
                for t, e, lost in zip(g.towns, g.evacuated, g.structures_lost)
            ],
        )

    def routes_msg(self) -> str:
        return routes_message(self.routes, self._routes_tick).model_dump_json()

    def recs_msg(self) -> str:
        return Recommendations(tick=self._recs_tick, recommendations=self.recs).model_dump_json()
    def vision_status_msg(self) -> str:
        if self.camera is None:
            status = VisionStatus(
                camera=CameraState.OFF,
                source="",
                fps=0,
                frame_width=0,
                frame_height=0,
                markers_seen=0,
                corners_seen=[],
                board_found=False,
            )
        else:
            status = self.camera.snapshot().status
        return status.model_dump_json()

    def poll_vision(self) -> None:
        """Pick up the camera thread's latest tokens and feed frame."""
        if self.camera is None:
            return
        snap = self.camera.snapshot()
        self.tracker.update(TokenSource.VISION, snap.tokens)
        if snap.feed_seq != self._sent_feed_seq and snap.feed_jpeg:
            self._sent_feed_seq = snap.feed_seq
            w, h = snap.feed_size
            broadcast(self.clients, pack_binary(BinaryType.CAMERA_FRAME, snap.feed_seq, w, h, snap.feed_jpeg))

    def sim_grid_frame(self) -> bytes:
        s = self.scenario
        return pack_binary(BinaryType.SIM_GRID, self.fire.tick, s.width, s.height, self.fire.state.tobytes())

    def forecast_frame(self) -> bytes:
        s = self.scenario
        f = self.latest_forecast
        if f is None:
            grids, tick = np.zeros((len(HORIZONS_MIN), s.height, s.width), np.uint8), self.fire.tick
        else:
            grids, tick = np.round(f.probability * 255).astype(np.uint8), f.tick
        return pack_binary(BinaryType.FORECAST_GRID, tick, s.width, s.height, grids.tobytes())

    async def handle_client(self, ws: ServerConnection) -> None:
        self.clients.add(ws)
        log.info("client connected (%d total)", len(self.clients))
        try:
            await ws.send(self.hello_msg())
            await ws.send(self.state_msg())
            await ws.send(self.tokens_msg())
            await ws.send(self.vision_status_msg())
            await ws.send(self.sim_grid_frame())
            await ws.send(self.forecast_frame())
            if self.roads is not None:
                await ws.send(self.routes_msg())
            await ws.send(self.recs_msg())
            await ws.send(self.score_msg())
            async for raw in ws:
                try:
                    msg = client_message_adapter.validate_json(raw)
                except ValidationError as e:
                    log.warning("bad message: %s", e)
                    continue
                self.dispatch(msg)
        except ConnectionClosed:
            pass
        finally:
            self.clients.discard(ws)
            log.info("client disconnected (%d total)", len(self.clients))

    def dispatch(self, msg) -> None:
        match msg:
            case VirtualTokenAdd() | VirtualTokenMove() | VirtualTokenRemove():
                self.virtual.handle(msg)
            case Ignite():
                self.fire.ignite(msg.x, msg.y)
                broadcast(self.clients, self.state_msg())
            case Reset():
                self.game.reset()
                self.reset_map()
            case StartRound():
                self.paused = False  # starting a round means playing it
                self.game.start(0)  # reset_map puts the fire back at tick 0
                self.reset_map()
                if (ig := self.game.ignition) is not None:
                    self.fire.ignite(*ig)
                    broadcast(self.clients, self.state_msg())
            case EndRound():
                phase = self.game.phase
                self.game.stop(self.fire.tick)
                broadcast(self.clients, self.score_msg())
                self.announce_round_end(phase)
            case SetRunning():
                self.paused = not msg.running
                self._step_budget = 0.0
                broadcast(self.clients, self.state_msg())
            case SetSpeed():
                self.speed = msg.speed
                broadcast(self.clients, self.state_msg())
            case StepOnce():
                if self.paused:
                    self.step_fire(steps=1)
                    broadcast(self.clients, self.state_msg())
            case AcceptRecommendation():
                self.accept_recommendation(msg.id)
            case CommanderQuery():
                self.ask(msg.text)
            case PttStart():
                self.ptt_start()
            case PttStop():
                self.ptt_stop()
            case SetVoice():
                self.voice_mode = msg.mode
                if msg.mode != VoiceMode.MAC:
                    self.mac_voice.interrupt()
            case SetWind():
                self.fire.set_wind(Wind(speed_ms=msg.speed_ms, from_deg=msg.from_deg % 360))
                broadcast(self.clients, self.state_msg())
        # Push token changes immediately rather than waiting for the next tick,
        # so dragging feels responsive.
        self.flush_tokens()

    def reset_map(self) -> None:
        """Put the fire out, drop everything derived from it, and tell the UI."""
        self.fire.reset()
        self.effects.reset()
        self._fire_epoch += 1
        self._forecast_started = -FORECAST_MIN_TICKS
        self.latest_forecast = None
        self.route_tracker.reset()
        self._closed[:] = False
        self.recent_events.clear()
        self.watcher.reset()
        self.briefings.reset()
        self.commander.reset()
        if self._query_task is not None:
            self._query_task.cancel()
        self.mac_voice.interrupt()
        if self.listener.recording:
            self.listener.stop()
        self.recs = []
        self._rec_started = -RECOMMEND_MIN_TICKS
        broadcast(self.clients, self.recs_msg())
        broadcast(self.clients, self.sim_grid_frame())
        broadcast(self.clients, self.forecast_frame())
        broadcast(self.clients, self.state_msg())
        broadcast(self.clients, self.score_msg())
        self.schedule_replan()

    def active_tokens(self) -> list[Token]:
        """Tokens within the round's limits; tokens over a limit do nothing."""
        active = self.game.active(self.tracker.tokens)
        if self.game.inactive != self._sent_inactive:
            self._sent_inactive = list(self.game.inactive)
            broadcast(self.clients, self.score_msg())
        return active

    def flush_tokens(self) -> None:
        if self.tracker.version != self._sent_token_version:
            self._sent_token_version = self.tracker.version
            broadcast(self.clients, self.tokens_msg())
            # A bus that appeared, moved a cell or left needs its route redone.
            sig = tuple(sorted((b[0], round(b[1]), round(b[2])) for b in self.buses()))
            if sig != self._bus_signature:
                self._bus_signature = sig
                self.schedule_replan()

    def buses(self) -> list[tuple[str, float, float]]:
        return [(t.id, t.x, t.y) for t in self.active_tokens() if t.token_type == TokenType.BUS]

    def broadcast_events(self, events: list[Event]) -> None:
        if events:
            self.recent_events.extend(events)
            self.briefings.offer(events, time.monotonic())
            broadcast(self.clients, Events(events=events).model_dump_json())

    def check_road_cuts(self) -> None:
        """Close roads the fire has reached since the last tick, and replan
        right away if one is on a route that's showing."""
        if self.roads is None:
            return
        hot = burning_edges(self.roads, self.fire.state, BURNING)
        newly = hot & ~self._closed
        self._closed = hot
        if not newly.any():
            return
        hit = [r for r in self.routes if r.edges and newly[r.edges].any()]
        if hit:
            tick = self.fire.tick
            self.broadcast_events([
                Event(kind=EventKind.ROAD_CUT, tick=tick, town=r.town,
                      text=f"Fire has reached the road from {r.town} to {r.safe_zone}.")
                for r in hit
            ])
            self.schedule_replan()

    def tick_fire(self) -> None:
        """Run this engine tick's share of sim steps, per pause and speed."""
        if self.paused:
            return
        self._step_budget += self.speed
        steps = int(self._step_budget)
        self._step_budget -= steps
        if steps:
            self.step_fire(steps)

    def step_fire(self, steps: int = 1) -> None:
        """Advance the fire `steps` ticks, then send one frame for all of them,
        so a fast sim doesn't flood the UI with frames it can't show."""
        if self.game.frozen:
            return  # the round is over; the map stays as it ended
        for _ in range(steps):
            if self.game.frozen:
                break  # the round is over; the map stays as it ended
            tokens = self.active_tokens()
            self.fire.set_suppression(self.effects.update(tokens, self.fire.tick))
            self.fire.step()
            self.check_road_cuts()
            self.score_step(tokens)
        broadcast(self.clients, self.sim_grid_frame())
        self.maybe_forecast()

    def score_step(self, tokens: list[Token]) -> None:
        phase = self.game.phase
        buses = [t for t in tokens if t.token_type == TokenType.BUS]
        cut = {r.town for r in self.routes if r.bus is None and r.status == "cut"}
        self.game.update(self.fire.tick, self.fire.state, buses, cut)
        if self.game.phase != phase:
            broadcast(self.clients, self.score_msg())
            self.announce_round_end(phase)

    def announce_round_end(self, before: RoundPhase) -> None:
        """When a round has just ended, brief the final score (every number from it)."""
        if before == RoundPhase.RUNNING and self.game.phase == RoundPhase.ENDED:
            text = round_summary(self.score())
            self.broadcast_events([Event(kind=EventKind.ROUND_ENDED, tick=self.fire.tick, town=None, text=text)])

    def maybe_forecast(self) -> None:
        if self._forecast_job is not None and not self._forecast_job.done():
            return
        if self.fire.tick - self._forecast_started < FORECAST_MIN_TICKS:
            return
        self._forecast_started = self.fire.tick
        epoch = self._fire_epoch
        job = self._forecast_job = self.forecaster.submit(self.fire.snapshot())
        job.add_done_callback(lambda f: self.forecast_done(f, epoch))

    def forecast_done(self, job: asyncio.Future[Forecast], epoch: int) -> None:
        if job.cancelled():
            return
        if (e := job.exception()) is not None:
            log.error("forecast failed: %r", e)
            return
        if epoch != self._fire_epoch:
            return
        self.latest_forecast = job.result()
        broadcast(self.clients, self.forecast_frame())
        self.schedule_replan()
        self.maybe_recommend()
        f = self.latest_forecast
        self.broadcast_events(self.watcher.update(self.fire.tick, self.tools.get_situation()["towns"], f.probability))

    def maybe_recommend(self) -> None:
        """Start a recommendation run if none is going and the last is a few
        seconds old. Uses the newest forecast's T+30 layer to find the front."""
        f = self.latest_forecast
        if f is None or not self.towns:
            return
        if self._rec_job is not None and not self._rec_job.done():
            return
        if self.fire.tick - self._rec_started < RECOMMEND_MIN_TICKS:
            return
        if self.game.frozen:
            return  # the round is over; nothing to recommend
        self._rec_started = tick = self.fire.tick
        epoch = self._fire_epoch
        snapshot = self.fire.snapshot()
        if self.crews_left() == 0:
            # Every crew is out (#77): recommend moving one instead of adding one.
            active = self.game.active(self.tracker.tokens)
            crews = [
                PlacedCrew(t.id, t.x, t.y, dataclasses.replace(
                    snapshot, suppression=self.effects.preview([o for o in active if o.id != t.id], tick)))
                for t in active if t.token_type == TokenType.CREW
            ]
            job = self.recommender.submit_moves(crews, snapshot.suppression, f.probability[0], self.towns, seed=tick)
        else:
            job = self.recommender.submit(snapshot, f.probability[0], self.towns, seed=tick)
        self._rec_job = job
        job.add_done_callback(lambda j: self.recommend_done(j, epoch, tick))

    def crews_left(self) -> int | None:
        """Crews that can still be placed this round, or None outside a round (no limit)."""
        g = self.game
        if g.phase != RoundPhase.RUNNING or TokenType.CREW not in g.limits:
            return None
        return max(0, g.limits[TokenType.CREW] - g.used.get(TokenType.CREW, 0))

    def recommend_done(self, job: asyncio.Future[list[Rec]], epoch: int, tick: int) -> None:
        if job.cancelled() or epoch != self._fire_epoch:
            return
        if (e := job.exception()) is not None:
            log.error("recommendation failed: %r", e)
            return
        acres_per_cell = self.scenario.cell_size_m**2 / SQ_M_PER_ACRE
        self.recs = [self.rec_message(r, f"r{tick}-{i}", acres_per_cell, self.place_near(r))
                     for i, r in enumerate(job.result())]
        self._recs_tick = tick
        broadcast(self.clients, self.recs_msg())

    def place_near(self, r: Rec) -> str | None:
        """Where a move's crew is now, for the card: 'near Pulga' if a named
        place is within 50 cells (~4.7 km), else 'in the north-west'."""
        if r.move_id is None:
            return None
        named = list(self.tools.places.values())
        if named:
            x, y, name = min(named, key=lambda p: (p[0] - r.from_x) ** 2 + (p[1] - r.from_y) ** 2)
            if (x - r.from_x) ** 2 + (y - r.from_y) ** 2 <= 50**2:
                return f"near {name}"
        w, h = self.scenario.width, self.scenario.height
        ns = "north" if r.from_y < h / 3 else "south" if r.from_y > 2 * h / 3 else ""
        ew = "west" if r.from_x < w / 3 else "east" if r.from_x > 2 * w / 3 else ""
        return f"in the {ns}-{ew}" if ns and ew else f"in the {ns or ew or 'middle'}"

    def rec_message(self, r: Rec, rec_id: str, acres_per_cell: float, from_place: str | None = None) -> Recommendation:
        def effects(es):
            return [TownEffectInfo(town=e.town, hits=e.hits, n=e.n, lo=round(e.lo, 3), hi=round(e.hi, 3)) for e in es]

        moving = next((t for t in self.tracker.tokens if t.id == r.move_id), None) if r.move_id else None
        return Recommendation(
            id=rec_id, token_type=TokenType.CREW, x=r.x, y=r.y,
            action=RecAction.MOVE if r.move_id else RecAction.PLACE,
            move_token=r.move_id, from_x=r.from_x, from_y=r.from_y,
            auto=r.move_id is None or (moving is not None and moving.source == "virtual"),
            benefit=round(r.benefit, 2), benefit_lo=round(r.benefit_lo, 2), benefit_hi=round(r.benefit_hi, 2),
            confidence=r.confidence, acres_saved=round(r.cells_saved * acres_per_cell, 1),
            saves=effects(r.saves), worsens=effects(r.worsens),
            protects=[TownShareInfo(town=p.town, share=p.share) for p in r.protects],
            text=describe(r, acres_per_cell, from_place),
        )

    def ask(self, question: str) -> None:
        """Answer a question in the background. A newer question cancels an
        older one that's still running, so the answer is always to the last ask."""
        if self._query_task is not None and not self._query_task.done():
            self._query_task.cancel()
        self._query_task = asyncio.create_task(self._answer(question))

    def ptt_start(self) -> None:
        self.mac_voice.interrupt()  # the console stops its own voice when the button goes down
        if not self.listener.available:
            self.send_transcript("", self.listener.reason)
            return
        try:
            self.listener.start()
        except Exception as err:  # no mic, or microphone permission denied
            self.send_transcript("", f"can't open the microphone: {err}")

    def ptt_stop(self) -> None:
        if self.listener.recording:
            asyncio.create_task(self._transcribe(self.listener.stop()))

    async def _transcribe(self, audio) -> None:
        try:
            text = await asyncio.to_thread(self.listener.transcribe, audio)
        except Exception as err:
            log.warning("transcription failed: %s", err)
            self.send_transcript("", "speech-to-text failed")
            return
        self.send_transcript(text, None if text else "didn't catch that")
        if text:
            self.ask(text)

    def send_transcript(self, text: str, error: str | None) -> None:
        broadcast(self.clients, Transcript(text=text, error=error).model_dump_json())

    def speak(self, utterance: str, kind: CommanderKind, text: str, urgent: bool = False) -> None:
        """Send text to whichever voice is on. Sentences of one answer share an utterance id."""
        if self.voice_mode == VoiceMode.CONSOLE:
            msg = CommanderSpeech(utterance=utterance, kind=kind, text=speakable(text), urgent=urgent)
            broadcast(self.clients, msg.model_dump_json())
        elif self.voice_mode == VoiceMode.MAC:
            self.mac_voice.speak(utterance, kind.value, speakable(text))

    async def _answer(self, question: str) -> None:
        utterance = f"a{next(self._utterances)}"
        ans = await self.commander.answer(
            question, on_sentence=lambda s: self.speak(utterance, CommanderKind.ANSWER, s)
        )
        msg = CommanderMessage(
            kind=CommanderKind.ANSWER,
            tick=self.fire.tick,
            text=ans.text,
            grounded=ans.grounded,  # templated, or LLM text that passed commander/guard.py
            event=None,
        )
        broadcast(self.clients, msg.model_dump_json())

    def accept_recommendation(self, rec_id: str) -> None:
        rec = next((r for r in self.recs if r.id == rec_id), None)
        if rec is None or not rec.auto:
            return  # stale card, or a physical token the operator has to move by hand
        if rec.action == RecAction.MOVE:
            if not any(t.id == rec.move_token for t in self.tracker.tokens):
                return  # that crew has been picked up since
            self.virtual.handle(VirtualTokenMove(id=rec.move_token, x=rec.x, y=rec.y))
        else:
            if self.crews_left() == 0:
                # A card from before the last crew went out: placing another
                # would be over the limit and do nothing (#77). Re-recommend.
                self._rec_started = -RECOMMEND_MIN_TICKS
                self.recs = []
                broadcast(self.clients, self.recs_msg())
                return
            self.virtual.handle(VirtualTokenAdd(token_type=rec.token_type, x=rec.x, y=rec.y))
        self.recs = [r for r in self.recs if r.id != rec_id]
        broadcast(self.clients, self.recs_msg())

    def schedule_replan(self) -> None:
        """Replan every town's route in a worker thread (~20 ms), one job at a
        time. Anything that asks while a job runs gets one more run after it,
        against whatever forecast is newest by then."""
        if self.roads is None:
            return
        if self._route_job is not None and not self._route_job.done():
            self._route_pending = True
            return
        self._route_pending = False
        self._route_job = asyncio.create_task(self.replan(self._fire_epoch))
        self._route_job.add_done_callback(lambda _: self._route_pending and self.schedule_replan())

    async def replan(self, epoch: int) -> None:
        f = self.latest_forecast
        tick = self.fire.tick
        first_burn = None if f is None else f.first_burn
        elapsed = 0 if f is None else tick - f.tick
        try:
            best, rescored = await asyncio.to_thread(
                replan_routes,
                self.roads,
                first_burn,
                self.route_tracker.held(),
                elapsed_ticks=elapsed,
                closed=self._closed.copy(),
                buses=self.buses(),
            )
        except Exception:
            log.exception("route planning failed")
            return
        if epoch != self._fire_epoch:
            return  # the map was reset while this was running
        self.routes, events = self.route_tracker.choose(best, rescored, tick)
        self._routes_tick = tick
        broadcast(self.clients, self.routes_msg())
        self.broadcast_events(events)

    async def run(self) -> None:
        self.recommender.warm()
        if self.listener.available:
            asyncio.get_running_loop().run_in_executor(None, self.listener.warm)
        period = 1 / TICK_HZ
        loop = asyncio.get_running_loop()
        next_tick = loop.time()
        while True:
            self.tick += 1
            self.poll_vision()
            self.flush_tokens()
            self.tick_fire()
            if (briefing := self.briefings.next(time.monotonic(), self.fire.tick, self.paused)) is not None:
                broadcast(self.clients, briefing.model_dump_json())
                urgent = briefing.event in (EventKind.NO_SAFE_ROUTE, EventKind.TOWN_THREATENED)
                self.speak(f"b{next(self._utterances)}", CommanderKind.BRIEFING, briefing.text, urgent)
            if self.tick % TICK_HZ == 0:
                broadcast(self.clients, self.state_msg())
                broadcast(self.clients, self.vision_status_msg())
                broadcast(self.clients, self.score_msg())
            next_tick += period
            await asyncio.sleep(max(0.0, next_tick - loop.time()))


def allowed_origins(setting: str = ENGINE_ORIGINS) -> list[str | None]:
    """Origins the WebSocket server accepts. None is a client that sends no
    Origin header at all: browsers always send one, so that's a script, a
    test or a tool on this machine, and refusing it would only get in the way."""
    return [o.strip() for o in setting.split(",") if o.strip()] + [None]


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    engine = Engine()
    try:
        async with serve(engine.handle_client, HOST, PORT, max_size=None, origins=allowed_origins()):
            log.info("listening on ws://%s:%d", HOST, PORT)
            await engine.run()
    finally:
        engine.forecaster.shutdown()
        engine.recommender.shutdown()
        if engine.camera is not None:
            engine.camera.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
