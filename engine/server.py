"""Engine entry point: WebSocket server plus the main loop.

Run with `uv run server.py` from engine/. The engine holds all state; UI
windows are views that can connect and disconnect at any time.
"""

import asyncio
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
from commander.briefings import BriefingQueue, ForecastWatcher
from commander.voice import MacVoice, speakable
from commander.tools import CommanderTools
from forecast.recommend import Rec, Recommender, TownInfo, describe
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
from sim.effects import TokenEffects
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

    def hello_msg(self) -> str:
        s = self.scenario
        return Hello(
            scenario=s.name,
            map_width=s.width,
            map_height=s.height,
            sim_minutes_per_tick=SIM_MINUTES_PER_TICK,
            forecast_horizons_min=list(HORIZONS_MIN),
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
        ).model_dump_json()

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
                self.game.stop(self.fire.tick)
                broadcast(self.clients, self.score_msg())
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
        self._rec_started = tick = self.fire.tick
        epoch = self._fire_epoch
        job = self._rec_job = self.recommender.submit(self.fire.snapshot(), f.probability[0], self.towns, seed=tick)
        job.add_done_callback(lambda j: self.recommend_done(j, epoch, tick))

    def recommend_done(self, job: asyncio.Future[list[Rec]], epoch: int, tick: int) -> None:
        if job.cancelled() or epoch != self._fire_epoch:
            return
        if (e := job.exception()) is not None:
            log.error("recommendation failed: %r", e)
            return
        acres_per_cell = self.scenario.cell_size_m**2 / SQ_M_PER_ACRE
        self.recs = [self.rec_message(r, f"r{tick}-{i}", acres_per_cell) for i, r in enumerate(job.result())]
        self._recs_tick = tick
        broadcast(self.clients, self.recs_msg())

    @staticmethod
    def rec_message(r: Rec, rec_id: str, acres_per_cell: float) -> Recommendation:
        def effects(es):
            return [TownEffectInfo(town=e.town, hits=e.hits, n=e.n) for e in es]

        return Recommendation(
            id=rec_id, token_type=TokenType.CREW, x=r.x, y=r.y,
            benefit=round(r.benefit, 2), acres_saved=round(r.cells_saved * acres_per_cell, 1),
            saves=effects(r.saves), worsens=effects(r.worsens),
            protects=[TownShareInfo(town=p.town, share=p.share) for p in r.protects],
            text=describe(r, acres_per_cell),
        )

    def ask(self, question: str) -> None:
        """Answer a question in the background. A newer question cancels an
        older one that's still running, so the answer is always to the last ask."""
        if self._query_task is not None and not self._query_task.done():
            self._query_task.cancel()
        self._query_task = asyncio.create_task(self._answer(question))

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
        if rec is None:
            return  # stale card: a newer run replaced it
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
        period = 1 / TICK_HZ
        loop = asyncio.get_running_loop()
        next_tick = loop.time()
        while True:
            self.tick += 1
            self.poll_vision()
            self.flush_tokens()
            self.tick_fire()
            if (briefing := self.briefings.next(time.monotonic())) is not None:
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
