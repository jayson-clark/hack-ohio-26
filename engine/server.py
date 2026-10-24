"""Engine entry point: WebSocket server plus the main loop.

Run with `uv run server.py` from engine/. The engine holds all state; UI
windows are views that can connect and disconnect at any time.
"""

import asyncio
import logging
import os

from pydantic import ValidationError
from websockets.asyncio.server import ServerConnection, broadcast, serve
from websockets.exceptions import ConnectionClosed

import numpy as np

from forecast.runner import HORIZONS_MIN, Forecast, Forecaster
from protocol import (
    BinaryType,
    Hello,
    Ignite,
    Reset,
    ScenarioState,
    SetWind,
    Tokens,
    VirtualTokenAdd,
    VirtualTokenMove,
    VirtualTokenRemove,
    WindState,
    client_message_adapter,
    pack_binary,
)
from scenario import load_scenario
from sim.effects import TokenEffects
from sim.fire import SIM_MINUTES_PER_TICK, FireSim, Wind
from vision.tokens import TokenTracker
from vision.virtual import VirtualTable

HOST = os.environ.get("ENGINE_HOST", "localhost")
PORT = int(os.environ.get("ENGINE_PORT", "8765"))
SCENARIO = os.environ.get("SCENARIO", "paradise")
TICK_HZ = 10
# Don't restart the forecaster more often than this, or a map with no fire
# (where a forecast is instant) would round-trip the worker every tick.
FORECAST_MIN_TICKS = 3

log = logging.getLogger("engine")


class Engine:
    def __init__(self) -> None:
        self.clients: set[ServerConnection] = set()
        self.tick = 0
        self.scenario = load_scenario(SCENARIO)
        self.tracker = TokenTracker()
        self.virtual = VirtualTable(self.tracker, self.scenario.width, self.scenario.height)
        self._sent_token_version = -1
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
            await ws.send(self.sim_grid_frame())
            await ws.send(self.forecast_frame())
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
                broadcast(self.clients, self.sim_grid_frame())
                broadcast(self.clients, self.forecast_frame())
                broadcast(self.clients, self.state_msg())
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

    def step_fire(self) -> None:
        self.fire.set_suppression(self.effects.update(self.tracker.tokens, self.fire.tick))
        self.fire.step()
        broadcast(self.clients, self.sim_grid_frame())
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

    async def run(self) -> None:
        period = 1 / TICK_HZ
        loop = asyncio.get_running_loop()
        next_tick = loop.time()
        while True:
            self.tick += 1
            self.flush_tokens()
            self.step_fire()
            if self.tick % TICK_HZ == 0:
                broadcast(self.clients, self.state_msg())
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


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
