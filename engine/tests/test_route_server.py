"""Routes on the wire: the message shape, and the engine's replan scheduling."""

import asyncio
import json

import numpy as np

from forecast.runner import Forecast
from protocol import Routes
from routing.evac import plan_routes, routes_message
from routing.roads import load_network
from scenario import load_scenario
from server import Engine


def test_routes_message_round_trips_as_plain_json():
    s = load_scenario("paradise")
    net = load_network(s.dir, s.width, s.height)
    raw = routes_message(plan_routes(net, None), tick=7).model_dump_json()
    msg = Routes.model_validate_json(raw)
    assert msg.tick == 7 and len(msg.routes) == len(net.towns)
    first = json.loads(raw)["routes"][0]
    assert first["status"] == "clear" and isinstance(first["eta_min"], float)
    assert all(len(p) == 2 for p in first["points"])


def _burning_everywhere(engine: Engine) -> Forecast:
    s = engine.scenario
    fb = np.zeros((4, s.height, s.width), np.float32)  # every cell already burning
    return Forecast(tick=engine.fire.tick, horizons_ticks=(30.0, 60.0), first_burn=fb,
                    probability=np.ones((2, s.height, s.width), np.float32))


def test_engine_replans_when_a_forecast_lands():
    async def run():
        engine = Engine()
        try:
            assert engine.routes and all(r.status == "clear" for r in engine.routes)
            engine.latest_forecast = _burning_everywhere(engine)
            engine.schedule_replan()
            await engine._route_job
            assert all(r.status == "cut" for r in engine.routes)
        finally:
            engine.forecaster.shutdown()

    asyncio.run(run())


def test_replan_started_before_a_reset_is_dropped():
    async def run():
        engine = Engine()
        try:
            before = engine.routes
            engine.latest_forecast = _burning_everywhere(engine)
            engine.schedule_replan()
            engine._fire_epoch += 1  # what Reset does, while the job is in flight
            await engine._route_job
            assert engine.routes is before
        finally:
            engine.forecaster.shutdown()

    asyncio.run(run())


def test_request_during_a_replan_runs_once_more_after_it():
    async def run():
        engine = Engine()
        try:
            engine.schedule_replan()
            first = engine._route_job
            engine.latest_forecast = _burning_everywhere(engine)
            engine.schedule_replan()  # busy: queued, not started
            assert engine._route_job is first and engine._route_pending
            await first
            await asyncio.sleep(0)  # let the done-callback start the follow-up
            assert engine._route_job is not first
            await engine._route_job
            assert all(r.status == "cut" for r in engine.routes)
        finally:
            engine.forecaster.shutdown()

    asyncio.run(run())
