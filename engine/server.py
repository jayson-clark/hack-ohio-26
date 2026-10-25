"""Engine entry point: WebSocket server plus the main loop.

Run with `uv run server.py` from engine/. The engine holds all state; UI
windows are views that can connect and disconnect at any time.
"""

import asyncio
import dataclasses
import json
import itertools
import logging
import os
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor

from pydantic import ValidationError
from websockets.asyncio.server import ServerConnection, broadcast, serve
from websockets.exceptions import ConnectionClosed

import numpy as np

from commander.agent import Commander
from commander.briefings import BriefingQueue, ForecastWatcher, evacuate_text, round_summary
from commander.listen import Listener, vocabulary_prompt
from commander.voice import MacVoice, speakable
from commander.tools import CommanderTools
from forecast.plan import PLAN_ROLLOUTS, PlanOutcome, evaluate_plan
from forecast.recommend import PlacedCrew, Rec, Recommender, TownInfo, describe
from forecast.runner import EVAC_HORIZON_MIN, HORIZONS_MIN, Forecast, Forecaster, LongForecast, LongForecaster
from protocol import (
    AcceptRecommendation,
    CalibrationStep,
    BinaryType,
    CommanderKind,
    CommanderMessage,
    CommanderQuery,
    CommanderSpeech,
    CameraState,
    EndRound,
    EvacStatus,
    EvaluatePlan,
    Event,
    EventKind,
    Events,
    Hello,
    Ignite,
    KofN,
    LoadScenario,
    OrderEvacuation,
    PlanOrderResult,
    PlanResult,
    PlanTown,
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
    Situation,
    StartRound,
    StepOnce,
    Token,
    TokenType,
    Transcript,
    StationInfo,
    UnitInfo,
    Units,
    UnitStatus,
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
from routing.clearance import MOBILIZE_MIN, TownClock, clock_message, compute_clock
from routing.evac import Route, burning_edges, plan_routes, replan_routes, routes_message
from routing.tracker import RouteTracker
from routing.roads import load_network
from scenario import ASSETS, load_scenario
from sim.effects import CREW_RADIUS, SuppressionSchedule, TokenEffects
from sim.fire import BURNING, SIM_MINUTES_PER_TICK, FireSim, Wind
from uq.mc import wilson
from sim.dispatch import Dispatcher
from sim.game import Game, GameTown
from routing.units import TURNOUT_MIN, Station, UnitRouter
from vision import camera
from vision.projector import Calibrator
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
PREVIEW_MIN_TICKS = 5  # engine ticks (0.5 s) between emulator previews (#113)


def _load_emulator():
    """The learned fire emulator, or None without the ml extra or its weights."""
    try:
        from emulator.model import load_emulator

        emu = load_emulator()
    except Exception as e:  # a broken ML install must never stop the engine
        log.warning("fire emulator unavailable: %r", e)
        return None
    log.info("fire emulator %s", "loaded" if emu else "not installed (uv run --extra ml); Monte Carlo only")
    return emu
# Recommendations rerun at most this often (a run is ~0.3 s in its own worker).
RECOMMEND_MIN_TICKS = 20
LONG_FORECAST_MIN_TICKS = 10  # sim ticks between the evacuation clock's long forecasts (#121)
SQ_M_PER_ACRE = 4046.86

log = logging.getLogger("engine")


class Engine:
    def __init__(self) -> None:
        self.clients: set[ServerConnection] = set()
        self.tick = 0
        self._sent_token_version = -1
        self._sent_feed_seq = 0
        self.forecaster = Forecaster()
        # The learned fire emulator (#113), if MLX and its weights are there:
        # an instant forecast preview whenever the wind, tokens or fire change,
        # shown until the next Monte Carlo forecast replaces it. Routing, the
        # commander and recommendations only ever use Monte Carlo forecasts.
        # MLX ties its streams to the thread that loaded the model, so one
        # dedicated thread loads the emulator and runs every preview.
        self._emu_thread = ThreadPoolExecutor(max_workers=1, thread_name_prefix="emulator")
        self.emulator = self._emu_thread.submit(_load_emulator).result()
        self._preview: tuple[int, np.ndarray] | None = None  # (tick, (2, H, W) probabilities)
        self._preview_job: asyncio.Task | None = None
        self._preview_sig: tuple | None = None
        self._preview_tick = 0
        self._ignitions = 0
        self._forecast_job: asyncio.Future[Forecast] | None = None
        self._forecast_started = -FORECAST_MIN_TICKS
        # The evacuation clock's long forecast (#121), in its own workers, and
        # the clock's recomputes, in a thread like route replans.
        self.long_forecaster = LongForecaster()
        self._long_job: asyncio.Task | None = None
        self._long_started = -LONG_FORECAST_MIN_TICKS
        self._clock_job: asyncio.Task | None = None
        self._clock_pending = False
        # Bumped on reset and on a scenario switch, so a forecast in flight
        # when the map changed is dropped rather than shown over the new map.
        self._fire_epoch = 0
        # The newest finished forecast, or None before the first one (and
        # after a reset). Routing and the commander read it from here:
        # .tick is the sim tick it started from; .first_burn is float32
        # (N, H, W) ticks-after-.tick until each cell burns (inf = not by the
        # last horizon); .probability is float32 (len(HORIZONS_MIN), H, W).
        self.latest_forecast: Forecast | None = None
        self.route_tracker = RouteTracker()
        self._routes_tick = 0
        self._route_job: asyncio.Task | None = None
        self._route_pending = False
        self._bus_signature: tuple = ()
        # The last few events, for the commander's tools and briefings.
        self.recent_events: deque[Event] = deque(maxlen=20)
        # Crew recommendations, from their own worker after a forecast lands.
        self.recommender = Recommender()
        self.recs: list[Recommendation] = []
        self._recs_tick = 0
        self._rec_job: asyncio.Future[list[Rec]] | None = None
        self._rec_started = -RECOMMEND_MIN_TICKS
        # Pause and speed (#54). Speed is sim steps per engine tick; the
        # fractional part carries over, so 0.5 steps every other tick.
        self.paused = False
        self.speed = 1.0
        self._step_budget = 0.0
        self._sent_inactive: list[str] = []
        # Plans run one at a time; one that a newer plan replaced while it
        # waited is skipped, so editing a plan quickly never builds a queue.
        self._plan_lock = asyncio.Lock()
        self._plan_latest = 0
        # Everything derived from the scenario (the map, layers, routing, game,
        # dispatch and the speech vocabulary) lives in load(), so a scenario
        # switch (#57) can rebuild it. It runs before the commander below,
        # whose tools read the scenario when they're built.
        self.tracker = TokenTracker()
        self.camera = None
        self.load(SCENARIO)
        # The incident commander: tools over this engine, plus unprompted
        # briefings from forecast and route events (no LLM needed for those).
        # They read the engine's live attributes; switch_scenario rebuilds the
        # tools' grid-sized town masks.
        self.tools = CommanderTools(self)
        self.watcher = ForecastWatcher()
        self.briefings = BriefingQueue()
        self.commander = Commander(self.tools)
        self._query_task: asyncio.Task | None = None
        # Voice is off until a console turns it on (commander/voice.py).
        self.voice_mode = VoiceMode.OFF
        self.mac_voice = MacVoice()
        self._utterances = itertools.count(1)

    def load(self, name: str) -> None:
        """Build (or rebuild) every scenario-derived piece of state. Called
        once at startup and again on a load_scenario message. Does not touch
        the worker processes, pause/speed, voice, the commander or the token
        tracker; switch_scenario handles those."""
        self.scenario = load_scenario(name)
        s = self.scenario
        self.virtual = VirtualTable(self.tracker, s.width, s.height)
        # The camera's homography is per scenario; stop the old capture thread
        # rather than leaving it running beside the new one.
        if self.camera is not None:
            self.camera.stop()
        self.camera = camera.from_env(CAMERA, s)
        # Projector calibration (map -> projector), saved in calibration.json.
        # Another scenario keeps the rig's camera -> projector and re-derives
        # the map part once the camera sees the new board.
        self.calibrator = Calibrator(s)
        self.fire = FireSim(s)
        self.effects = TokenEffects(s.width, s.height)
        # Evacuation routes (PLAN.md, Evacuation routing), replanned off the
        # tick loop whenever a forecast lands. No road layer means no routes.
        self.roads = load_network(s.dir, s.width, s.height)
        # Plan once here (no fire yet, so plain shortest paths). This also
        # builds the graph's lazy caches before any worker thread touches it.
        # Held routes refer to the previous graph's nodes and edges, so drop them
        # before choosing: a town with the same name on both maps would
        # otherwise keep the old map's route.
        self.route_tracker.reset()
        self.routes: list[Route] = []
        if self.roads is not None:
            self.routes, _ = self.route_tracker.choose(plan_routes(self.roads, None), {}, 0)
        # Road edges with a cell burning right now, checked every tick so a
        # road the fire reaches between forecasts closes immediately.
        self._closed = np.zeros(len(self.roads.edges) if self.roads else 0, bool)
        self.towns = [TownInfo(t.name, t.x, t.y, t.radius, t.population) for t in self.roads.towns] if self.roads else []
        # Resource limits, scoring and rounds (sim/game.py). Towns come from the
        # road layer's towns.json, so no road layer means nothing to score.
        game_towns = [
            GameTown(t.name, t.x, t.y, t.radius, t.population, t.structures) for t in self.roads.towns
        ] if self.roads else []
        self.game = Game(s, game_towns)
        # The evacuation clock (#121): orders given (town -> sim tick), the long
        # forecast it reads, and the latest clock. Computed once here with no
        # forecast, which also builds the graph's caches before any thread does.
        self.evac_orders: dict[str, int] = {}
        self.long_forecast: LongForecast | None = None
        self._evac_due: set[str] = set()  # towns already told to order out
        self.evac_clock: list[TownClock] = []
        self._clock_tick = 0
        if self.roads is not None:
            self.evac_clock = self.compute_clock(0)
        # Fire units come from stations (#104): a crew, dozer or tanker token is
        # an order, and acts on the fire only once its unit gets there. No
        # stations.json (or no roads) means tokens act at once, as before.
        path = s.dir / "stations.json"
        self.stations = [Station(**st) for st in json.loads(path.read_text())["stations"]] if path.exists() else []
        self.unit_router = UnitRouter(self.roads, s.cell_size_m) if self.roads and self.stations else None
        self.dispatcher = Dispatcher(self.stations if self.unit_router else [], self.unit_router)
        self._acting: list[Token] = []  # tokens acting on the fire (within limits, unit arrived)
        # Cleared on every load, so a new scenario's units are always sent.
        self._units_sig: tuple = ()
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
            stations=[StationInfo(name=s.name, x=s.x, y=s.y, kind=s.kind) for s in self.stations],
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

    def clock_msg(self) -> str:
        f = self.long_forecast
        return clock_message(self.evac_clock, self._clock_tick, None if f is None else f.tick,
                             EVAC_HORIZON_MIN).model_dump_json()

    def routes_msg(self) -> str:
        return routes_message(self.routes, self._routes_tick).model_dump_json()

    def recs_msg(self) -> str:
        return Recommendations(tick=self._recs_tick, recommendations=self.recs).model_dump_json()

    def situation_msg(self) -> str:
        f = self.latest_forecast
        return Situation(tick=self.fire.tick, forecast_tick=None if f is None else f.tick,
                         towns=self.tools.town_threats()).model_dump_json()
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

    def calibration_msg(self) -> str:
        return self.calibrator.message_model().model_dump_json()

    def poll_vision(self) -> None:
        """Pick up the camera thread's latest tokens and feed frame."""
        if self.camera is None:
            return
        self.camera.find_pattern(self.calibrator.finding)
        snap = self.camera.snapshot()
        if self.calibrator.poll(snap.pattern, snap.board):
            broadcast(self.clients, self.calibration_msg())
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
        pv = self._preview
        if pv is not None and (f is None or pv[0] > f.tick):
            grids, tick = np.round(pv[1] * 255).astype(np.uint8), pv[0]  # emulator preview (#113)
        elif f is None:
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
            await ws.send(self.calibration_msg())
            await ws.send(self.sim_grid_frame())
            await ws.send(self.forecast_frame())
            if self.roads is not None:
                await ws.send(self.routes_msg())
                await ws.send(self.clock_msg())
            await ws.send(self.recs_msg())
            await ws.send(self.units_msg())
            await ws.send(self.situation_msg())
            if self.recent_events:
                # So a window opened mid-incident has the recent log, not an empty one.
                await ws.send(Events(events=list(self.recent_events)).model_dump_json())
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
                self._ignitions += 1
                broadcast(self.clients, self.state_msg())
            case Reset():
                self.game.reset()
                self.reset_map()
            case LoadScenario():
                self.switch_scenario(msg.scenario)
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
            case OrderEvacuation():
                self.order_evacuation(msg.town, msg.ordered)
            case EvaluatePlan():
                self._plan_latest = msg.id
                asyncio.create_task(self.evaluate_plan(msg))
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
            case CalibrationStep():
                self.calibrator.step(msg.action, self.camera is not None)
                broadcast(self.clients, self.calibration_msg())
            case SetWind():
                self.fire.set_wind(Wind(speed_ms=msg.speed_ms, from_deg=msg.from_deg % 360))
                broadcast(self.clients, self.state_msg())
        # Push token changes immediately rather than waiting for the next tick,
        # so dragging feels responsive.
        self.flush_tokens()

    def switch_scenario(self, name: str) -> None:
        """Load another scenario and rebuild the world around it. The fire,
        layers, routing, game, dispatch and vocabulary are rebuilt, virtual
        tokens are cleared (their coordinates belong to the old map; camera
        tokens follow the camera), and every window re-reads terrain from the
        fresh hello. An unknown or broken scenario is ignored with a log."""
        if name == self.scenario.name:
            return
        if not (ASSETS / name).is_dir():
            log.warning("load_scenario: no scenario %r under %s", name, ASSETS)
            return
        # Stop anything tied to the old listener before load() replaces it.
        if self.listener.recording:
            self.listener.stop()
        previous = self.scenario.name
        try:
            self.load(name)
        except Exception as e:  # a bad scenario shouldn't take the engine down
            # load() replaces self.scenario first, so rebuild by the old name.
            log.error("load_scenario %r failed: %r; staying on %s", name, e, previous)
            self.load(previous)
            return
        log.info("switched to scenario %s (%dx%d)", name, self.scenario.width, self.scenario.height)
        # Drop fire-derived and commander state, like a reset does, then tell
        # every window about the new map. hello first: the map size can change,
        # so the UI must re-read terrain before it interprets any grid.
        self.tick = 0
        self._preview_tick = -PREVIEW_MIN_TICKS  # the throttle counts engine ticks, which just restarted
        self.fire.reset()
        self.effects.reset()
        self._fire_epoch += 1
        self._forecast_started = -FORECAST_MIN_TICKS
        self.latest_forecast = None
        self._preview = None
        self._closed[:] = False
        self._bus_signature = ()
        self.tracker.update(TokenSource.VIRTUAL, [])
        # load() already reset the route tracker (held routes belong to the old graph).
        self._routes_tick = 0
        self.tools.on_scenario()
        self._sent_inactive = []
        self._sent_token_version = -1
        self.recent_events.clear()
        self.watcher.reset()
        self.briefings.reset()
        self.commander.reset()
        if self._query_task is not None:
            self._query_task.cancel()
        self.mac_voice.interrupt()
        self.recs = []
        self._rec_started = -RECOMMEND_MIN_TICKS
        broadcast(self.clients, self.hello_msg())
        broadcast(self.clients, self.state_msg())
        broadcast(self.clients, self.tokens_msg())
        broadcast(self.clients, self.vision_status_msg())
        broadcast(self.clients, self.sim_grid_frame())
        broadcast(self.clients, self.forecast_frame())
        self._long_started = -LONG_FORECAST_MIN_TICKS
        if self.roads is not None:
            broadcast(self.clients, self.routes_msg())
            broadcast(self.clients, self.clock_msg())
        broadcast(self.clients, self.recs_msg())
        broadcast(self.clients, self.score_msg())
        broadcast(self.clients, self.calibration_msg())

    def reset_map(self) -> None:
        """Put the fire out, drop everything derived from it, and tell the UI."""
        self.fire.reset()
        self.effects.reset()
        self._fire_epoch += 1
        self._forecast_started = -FORECAST_MIN_TICKS
        self.latest_forecast = None
        self._preview = None
        self.route_tracker.reset()
        self._closed[:] = False
        self.evac_orders.clear()
        self.long_forecast = None
        self._long_started = -LONG_FORECAST_MIN_TICKS
        self._evac_due.clear()
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
        self.dispatcher.reset()
        self._acting = []
        broadcast(self.clients, self.recs_msg())
        broadcast(self.clients, self.units_msg())
        broadcast(self.clients, self.sim_grid_frame())
        broadcast(self.clients, self.forecast_frame())
        broadcast(self.clients, self.state_msg())
        broadcast(self.clients, self.score_msg())
        broadcast(self.clients, self.situation_msg())
        self.schedule_replan()
        self.schedule_clock()

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
        self.schedule_clock()
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
            closed = self._closed if self.roads is not None else None
            self._acting = self.dispatcher.update(tokens, self.fire.tick, self.fire.wind.speed_ms, closed)
            self.fire.set_suppression(self.effects.update(self._acting, self.fire.tick))
            self.fire.step()
            self.check_road_cuts()
            self.score_step(tokens)
        broadcast(self.clients, self.sim_grid_frame())
        self.flush_dispatch()
        self.maybe_forecast()
        self.maybe_long_forecast()

    def score_step(self, tokens: list[Token]) -> None:
        phase = self.game.phase
        buses = [t for t in tokens if t.token_type == TokenType.BUS]
        cut = {r.town for r in self.routes if r.bus is None and r.status == "cut"}
        self.game.update(self.fire.tick, self.fire.state, buses, cut, self.evac_flows())
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
        job = self._forecast_job = self.forecaster.submit(self.snapshot())
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
        if self._preview is not None and self._preview[0] <= self.latest_forecast.tick:
            self._preview = None  # Monte Carlo has caught up
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
        snapshot = self.snapshot()
        if self.crews_left() == 0:
            # Every crew is out (#77): recommend moving one instead of adding one.
            active = self.game.active(self.tracker.tokens)
            crews = []
            for t in active:
                if t.token_type != TokenType.CREW:
                    continue
                others = self.effects.schedule([o for o in active if o.id != t.id], tick)
                [keep] = self.effects.schedule([t], tick).layers  # this crew, carrying on where it is
                without = dataclasses.replace(snapshot, suppression=others.at(0), schedule=others)
                eta = self.dispatcher.eta_from(t.x, t.y) if self.dispatcher.units else None
                crews.append(PlacedCrew(t.id, t.x, t.y, without, keep, eta))
            job = self.recommender.submit_moves(crews, f.probability[0], self.towns, seed=tick)
        else:
            eta = self.dispatcher.eta_grid(TokenType.CREW, self.fire.wind.speed_ms) if self.dispatcher.units else None
            job = self.recommender.submit(snapshot, f.probability[0], self.towns, seed=tick, eta=eta)
        self._rec_job = job
        job.add_done_callback(lambda j: self.recommend_done(j, epoch, tick))

    def snapshot(self):
        """The fire now, plus the suppression schedule of the tokens acting on
        it, so forecasts credit crews still digging in and drops drying out
        (#56), plus units still on their way, from when they'll arrive (#104)."""
        tick = self.fire.tick
        sched = self.effects.schedule(self._acting, tick)
        tokens = {t.id: t for t in self.tracker.tokens}
        for u in self.dispatcher.pending():
            t = tokens.get(u.token_id)
            layer = self.effects.arrival_layer(t, max(0, u.arrive_tick - tick)) if t is not None else None
            if layer is not None:
                sched.layers.append(layer)
        return dataclasses.replace(self.fire.snapshot(), schedule=sched)

    def units_msg(self) -> str:
        tick, mpt = self.fire.tick, SIM_MINUTES_PER_TICK
        units = []
        for u in self.dispatcher.units:
            x, y = u.position(tick)
            units.append(UnitInfo(
                id=u.id, station=u.station.name, token_type=u.token_type, status=UnitStatus(u.status),
                token_id=u.token_id, x=round(float(x), 2), y=round(float(y), 2),
                eta_min=round((u.arrive_tick - tick) * mpt, 1) if u.status == "en_route" else None,
                path=u.path if u.status == "en_route" else [],
            ))
        return Units(tick=tick, units=units).model_dump_json()

    def flush_dispatch(self) -> None:
        """Send dispatch events (arrived, blocked, grounded) and unit positions."""
        kinds = {"arrived": EventKind.UNIT_ARRIVED, "blocked": EventKind.UNIT_BLOCKED,
                 "grounded": EventKind.TANKERS_GROUNDED}
        events = [Event(kind=kinds[e.kind], tick=self.fire.tick, town=None, text=e.text)
                  for e in self.dispatcher.take_events()]
        self.broadcast_events(events)
        sig = tuple((u.id, u.status, u.token_id, u.arrive_tick) for u in self.dispatcher.units)
        moving = any(u.status == "en_route" for u in self.dispatcher.units)
        if sig != self._units_sig or (moving and self.tick % 3 == 0):
            self._units_sig = sig
            broadcast(self.clients, self.units_msg())

    def best_station(self, token_type: TokenType, x: float, y: float) -> tuple[str | None, float | None]:
        """Which station's free unit would reach (x, y) first, and in how many minutes."""
        free = [u for u in self.dispatcher.units if u.token_type == token_type and u.status == "available"]
        best = (None, None)
        for u in free:
            m, _ = self.dispatcher._eta(u, u.home, (x, y), self.fire.wind.speed_ms)
            if m != float("inf") and (best[1] is None or m < best[1]):
                best = (u.station.name, round(m + TURNOUT_MIN, 1))
        return best

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
        station = None
        if self.dispatcher.units:
            if r.move_id:
                unit = next((u for u in self.dispatcher.units if u.token_id == r.move_id), None)
                station = unit.station.name if unit else None
            else:
                station, _ = self.best_station(TokenType.CREW, r.x, r.y)
        return Recommendation(
            id=rec_id, token_type=TokenType.CREW, x=r.x, y=r.y,
            action=RecAction.MOVE if r.move_id else RecAction.PLACE,
            move_token=r.move_id, from_x=r.from_x, from_y=r.from_y,
            auto=r.move_id is None or (moving is not None and moving.source == "virtual"),
            benefit=round(r.benefit, 2), benefit_lo=round(r.benefit_lo, 2), benefit_hi=round(r.benefit_hi, 2),
            confidence=r.confidence, acres_saved=round(r.cells_saved * acres_per_cell, 1),
            saves=effects(r.saves), worsens=effects(r.worsens),
            protects=[TownShareInfo(town=p.town, share=p.share) for p in r.protects],
            station=station, eta_min=r.eta_min,
            text=describe(r, acres_per_cell, from_place, station),
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

    def plan_arrivals(self, orders, wind_ms: float) -> list[PlanOrderResult]:
        """Which free unit would take each order and when it could act (#123).
        Greedy, in order: each order takes the fastest unit not already taken,
        the way dispatch would send them one after another."""
        if not self.dispatcher.units:
            return [PlanOrderResult(token_type=o.token_type, x=o.x, y=o.y, station=None, eta_min=0.0,
                                    counted=o.token_type != TokenType.BUS) for o in orders]
        taken: set[str] = set()
        out = []
        for o in orders:
            best = None
            for u in self.dispatcher.units:
                if u.token_type != o.token_type or u.status != "available" or u.id in taken:
                    continue
                m, _ = self.dispatcher._eta(u, u.home, (o.x, o.y), wind_ms)
                if m != float("inf") and (best is None or m < best[1]):
                    best = (u, m + TURNOUT_MIN)
            if best is not None:
                taken.add(best[0].id)
            out.append(PlanOrderResult(
                token_type=o.token_type, x=o.x, y=o.y,
                station=None if best is None else best[0].station.name,
                eta_min=None if best is None else round(best[1], 1),
                counted=best is not None,
            ))
        return out

    async def evaluate_plan(self, msg: EvaluatePlan) -> None:
        """Run the operator's plan against doing nothing (#123) in the
        Recommender worker, then broadcast the result and its PLAN_GRID."""
        async with self._plan_lock:
            if self._plan_latest and msg.id != self._plan_latest:
                return  # a newer plan came in while this one waited
            await self._evaluate_plan(msg)

    async def _evaluate_plan(self, msg: EvaluatePlan) -> None:
        w = msg.wind
        wind = self.fire.wind if w is None else Wind(speed_ms=max(0.0, w.speed_ms), from_deg=w.from_deg % 360)
        horizon = min(max(msg.horizon_min, 30.0), 240.0)
        tick, epoch = self.fire.tick, self._fire_epoch
        orders = self.plan_arrivals(msg.orders, wind.speed_ms)

        def reply(error: str | None, outcome: PlanOutcome | None = None) -> None:
            empty = KofN(k=0, n=0, lo=0.0, hi=1.0)
            o = outcome
            broadcast(self.clients, PlanResult(
                id=msg.id, tick=tick, n=0 if o is None else o.n, horizon_min=horizon,
                wind=WindState(speed_ms=wind.speed_ms, from_deg=wind.from_deg), orders=orders,
                acres_base=0 if o is None else round(o.acres_base, 1),
                acres_plan=0 if o is None else round(o.acres_plan, 1),
                acres_saved=0 if o is None else round(o.acres_saved[0], 1),
                acres_saved_lo=0 if o is None else round(o.acres_saved[1], 1),
                acres_saved_hi=0 if o is None else round(o.acres_saved[2], 1),
                people_base=0 if o is None else round(o.people_base),
                people_plan=0 if o is None else round(o.people_plan),
                towns=[] if o is None else [
                    PlanTown(town=t.town, base=self._kofn(t.base_hits, o.n) or empty,
                             plan=self._kofn(t.plan_hits, o.n) or empty, saves=t.saves, worsens=t.worsens,
                             base_median_min=t.base_median_min, plan_median_min=t.plan_median_min)
                    for t in o.towns
                ],
                error=error,
            ).model_dump_json())

        if not self.fire.counts()[0]:
            return reply("Nothing is burning, so there's nothing to plan against.")
        tokens = [Token(id=f"plan{i}", token_type=o.token_type, x=o.x, y=o.y, angle=0.0, source=TokenSource.VIRTUAL)
                  for i, o in enumerate(orders) if o.counted]
        layers = [self.effects.arrival_layer(t, int(round((o.eta_min or 0) / SIM_MINUTES_PER_TICK)))
                  for t, o in zip(tokens, [o for o in orders if o.counted])]
        s = self.scenario
        plan = SuppressionSchedule(np.zeros((s.height, s.width), np.float32), [l for l in layers if l is not None])
        acres_per_cell = s.cell_size_m**2 / SQ_M_PER_ACRE
        try:
            outcome = await self.recommender.run(
                evaluate_plan, self.snapshot(), plan, self.towns, wind,
                int(round(horizon / SIM_MINUTES_PER_TICK)), acres_per_cell, PLAN_ROLLOUTS, tick)
        except Exception as e:
            log.exception("plan evaluation failed")
            return reply(f"The plan couldn't be simulated: {e}")
        if epoch != self._fire_epoch:
            return reply("The map was reset while the plan ran.")
        reply(None, outcome)
        broadcast(self.clients, pack_binary(BinaryType.PLAN_GRID, msg.id, s.width, s.height, outcome.grids.tobytes()))

    @staticmethod
    def _kofn(k: int, n: int) -> KofN | None:
        if n == 0:
            return None
        lo, hi = wilson(k, n)
        return KofN(k=k, n=n, lo=round(float(lo), 3), hi=round(float(hi), 3))

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
        broadcast(self.clients, self.situation_msg())
        self.broadcast_events(events)

    def maybe_long_forecast(self) -> None:
        """Start the evacuation clock's long forecast if none is running and
        the last is LONG_FORECAST_MIN_TICKS old."""
        if self.roads is None or (self._long_job is not None and not self._long_job.done()):
            return
        if self.fire.tick - self._long_started < LONG_FORECAST_MIN_TICKS:
            return
        self._long_started = self.fire.tick
        epoch = self._fire_epoch
        self._long_job = asyncio.create_task(self.long_forecaster.run(self.snapshot()))
        self._long_job.add_done_callback(lambda j: self.long_forecast_done(j, epoch))

    def long_forecast_done(self, job: asyncio.Task, epoch: int) -> None:
        if job.cancelled() or epoch != self._fire_epoch:
            return
        if (e := job.exception()) is not None:
            log.error("long forecast failed: %r", e)
            return
        self.long_forecast = job.result()
        self.schedule_clock()

    def order_evacuation(self, town: str, ordered: bool) -> None:
        """Order a town out (from now), or take the order back."""
        if not any(t.name == town for t in self.towns):
            return
        if ordered:
            self.evac_orders.setdefault(town, self.fire.tick)
        else:
            self.evac_orders.pop(town, None)
        self.schedule_clock()

    def evac_flows(self) -> dict[str, float]:
        """People a sim minute leaving each ordered town whose cars are moving."""
        tick, orders = self.fire.tick, self.evac_orders
        return {c.town: c.people_per_min for c in self.evac_clock
                if c.status == EvacStatus.EVACUATING and c.town in orders
                and (tick - orders[c.town]) * SIM_MINUTES_PER_TICK >= MOBILIZE_MIN}

    def compute_clock(self, tick: int) -> list[TownClock]:
        f = self.long_forecast
        return compute_clock(
            self.roads,
            None if f is None else f.first_burn,
            tick=tick,
            forecast_tick=tick if f is None else f.tick,
            horizon_min=EVAC_HORIZON_MIN,
            orders=dict(self.evac_orders),
            evacuated=list(self.game.evacuated),
            minutes_per_tick=SIM_MINUTES_PER_TICK,
            closed=self._closed.copy(),
        )

    def schedule_clock(self) -> None:
        """Recompute the evacuation clock in a worker thread (tens of ms), one
        job at a time, like schedule_replan."""
        if self.roads is None:
            return
        if self._clock_job is not None and not self._clock_job.done():
            self._clock_pending = True
            return
        self._clock_pending = False
        self._clock_job = asyncio.create_task(self.recompute_clock(self._fire_epoch))
        self._clock_job.add_done_callback(lambda _: self._clock_pending and self.schedule_clock())

    async def recompute_clock(self, epoch: int) -> None:
        tick = self.fire.tick
        try:
            clocks = await asyncio.to_thread(self.compute_clock, tick)
        except Exception:
            log.exception("evacuation clock failed")
            return
        if epoch != self._fire_epoch:
            return
        self.evac_clock, self._clock_tick = clocks, tick
        broadcast(self.clients, self.clock_msg())
        self.broadcast_events(self.evac_events(clocks, tick))

    def evac_events(self, clocks: list[TownClock], tick: int) -> list[Event]:
        """An evacuate_now event when a town that isn't ordered out reaches
        its order time, once until it drops back to watch."""
        events = []
        for c in clocks:
            if c.status in (EvacStatus.ORDER_NOW, EvacStatus.LATE) and c.town not in self._evac_due:
                self._evac_due.add(c.town)
                events.append(Event(kind=EventKind.EVACUATE_NOW, tick=tick, town=c.town, text=evacuate_text(c, tick)))
            elif c.status == EvacStatus.WATCH:
                self._evac_due.discard(c.town)
        return events

    def maybe_preview(self) -> None:
        """Start an emulator preview when what the forecast depends on has
        changed (wind, tokens, a new ignition, a reset) since the last one, at
        most every PREVIEW_MIN_TICKS engine ticks, off the tick loop."""
        if self.emulator is None or (self._preview_job is not None and not self._preview_job.done()):
            return
        if self.tick - self._preview_tick < PREVIEW_MIN_TICKS or not (self.fire.state == BURNING).any():
            return
        tokens = tuple((t.id, round(t.x), round(t.y)) for t in self.active_tokens())
        sig = (self._fire_epoch, self.fire.wind, tokens, self._ignitions)
        if sig == self._preview_sig:
            return
        self._preview_sig, self._preview_tick = sig, self.tick
        snap, epoch = self.snapshot(), self._fire_epoch
        loop = asyncio.get_running_loop()
        self._preview_job = asyncio.ensure_future(loop.run_in_executor(self._emu_thread, self.emulator.forecast, snap))
        self._preview_job.add_done_callback(lambda j: self.preview_done(j, snap.tick, epoch))

    def preview_done(self, job: asyncio.Task, tick: int, epoch: int) -> None:
        if job.cancelled() or epoch != self._fire_epoch:
            return
        if (e := job.exception()) is not None:
            log.error("emulator preview failed: %r", e)
            return
        f = self.latest_forecast
        if f is not None and f.tick >= tick:
            return  # a Monte Carlo forecast at least as new already landed
        self._preview = (tick, job.result())
        broadcast(self.clients, self.forecast_frame())

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
            self.maybe_preview()
            if (briefing := self.briefings.next(time.monotonic(), self.fire.tick, self.paused)) is not None:
                broadcast(self.clients, briefing.model_dump_json())
                urgent = briefing.event in (EventKind.NO_SAFE_ROUTE, EventKind.TOWN_THREATENED, EventKind.EVACUATE_NOW)
                self.speak(f"b{next(self._utterances)}", CommanderKind.BRIEFING, briefing.text, urgent)
            if self.tick % TICK_HZ == 0:
                broadcast(self.clients, self.state_msg())
                broadcast(self.clients, self.vision_status_msg())
                broadcast(self.clients, self.score_msg())
                if self.evac_orders:
                    self.schedule_clock()  # people left and the queues change as towns empty
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
        engine.long_forecaster.shutdown()
        engine.recommender.shutdown()
        if engine.camera is not None:
            engine.camera.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
