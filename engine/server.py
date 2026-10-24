"""Engine entry point: WebSocket server plus the main loop.

Run with `uv run server.py` from engine/. The engine holds all state; UI
windows are views that can connect and disconnect at any time.
"""

import asyncio
import logging
import os
from collections import deque

from pydantic import ValidationError
from websockets.asyncio.server import ServerConnection, broadcast, serve
from websockets.exceptions import ConnectionClosed

import numpy as np

from forecast.recommend import Rec, Recommender, TownInfo, describe
from forecast.runner import HORIZONS_MIN, Forecast, Forecaster
from protocol import (
    AcceptRecommendation,
    BinaryType,
    CameraState,
    Event,
    EventKind,
    Events,
    Hello,
    Ignite,
    Reset,
    ScenarioState,
    SetWind,
    TokenType,
    Tokens,
    TokenSource,
    VirtualTokenAdd,
    VirtualTokenMove,
    VirtualTokenRemove,
    VisionStatus,
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
from vision import camera
from vision.tokens import TokenTracker
from vision.virtual import VirtualTable

HOST = os.environ.get("ENGINE_HOST", "localhost")
PORT = int(os.environ.get("ENGINE_PORT", "8765"))
SCENARIO = os.environ.get("SCENARIO", "paradise")
CAMERA = os.environ.get("CAMERA", "")  # see vision/camera.py; empty = virtual table only
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
            running=True,
            wind=WindState(speed_ms=w.speed_ms, from_deg=w.from_deg),
            burning_cells=burning,
            burned_cells=burned,
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
                self.fire.reset()
                self.effects.reset()
                self._fire_epoch += 1
                self._forecast_started = -FORECAST_MIN_TICKS
                self.latest_forecast = None
                self.route_tracker.reset()
                self._closed[:] = False
                self.recent_events.clear()
                self.recs = []
                self._rec_started = -RECOMMEND_MIN_TICKS
                broadcast(self.clients, self.recs_msg())
                broadcast(self.clients, self.sim_grid_frame())
                broadcast(self.clients, self.forecast_frame())
                broadcast(self.clients, self.state_msg())
                self.schedule_replan()
            case AcceptRecommendation():
                self.accept_recommendation(msg.id)
            case SetWind():
                self.fire.set_wind(Wind(speed_ms=msg.speed_ms, from_deg=msg.from_deg % 360))
                broadcast(self.clients, self.state_msg())
        # Push token changes immediately rather than waiting for the next tick,
        # so dragging feels responsive.
        self.flush_tokens()

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
        return [(t.id, t.x, t.y) for t in self.tracker.tokens if t.token_type == TokenType.BUS]

    def broadcast_events(self, events: list[Event]) -> None:
        if events:
            self.recent_events.extend(events)
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

    def step_fire(self) -> None:
        self.fire.set_suppression(self.effects.update(self.tracker.tokens, self.fire.tick))
        self.fire.step()
        broadcast(self.clients, self.sim_grid_frame())
        self.check_road_cuts()
        self.maybe_forecast()

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
            self.step_fire()
            if self.tick % TICK_HZ == 0:
                broadcast(self.clients, self.state_msg())
                broadcast(self.clients, self.vision_status_msg())
            next_tick += period
            await asyncio.sleep(max(0.0, next_tick - loop.time()))


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    engine = Engine()
    try:
        async with serve(engine.handle_client, HOST, PORT, max_size=None):
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
