"""Plan what-ifs (#123) and the town board (#122), on Paradise with a seeded fire."""

import asyncio
import json

import numpy as np

from forecast.plan import evaluate_plan
from forecast.recommend import TownInfo
from forecast.runner import run_forecast
from protocol import BinaryType, EvaluatePlan, PlanOrder, Situation, WindState
from server import Engine
from sim.effects import SuppressionSchedule, crew_layer
from sim.fire import Wind

IGNITION = (217.3, 54.5)  # the Camp Fire origin


def burning_engine(ticks: int = 30) -> Engine:
    e = Engine()
    e.fire.set_wind(Wind(10, 45))
    e.fire.ignite(*IGNITION)
    for _ in range(ticks):
        e.fire.step()
    e.latest_forecast = run_forecast(e.fire.snapshot(), seed=0)
    return e


class Capture:
    """Everything the engine broadcasts, in order."""

    def __init__(self, monkeypatch) -> None:
        self.sent: list = []
        monkeypatch.setattr("server.broadcast", lambda clients, msg: self.sent.append(msg))

    @property
    def json(self) -> list[dict]:
        return [json.loads(m) for m in self.sent if isinstance(m, str)]


def test_situation_lists_every_town_with_ranges():
    e = burning_engine()
    try:
        msg = Situation.model_validate_json(e.situation_msg())
        assert {t.town for t in msg.towns} == {t.name for t in e.towns}
        assert msg.forecast_tick == e.latest_forecast.tick
        for t in msg.towns:
            assert t.within_30 is not None and t.within_60 is not None
            assert t.within_30.k <= t.within_60.k <= t.within_60.n == 32
            assert 0 <= t.within_60.lo <= t.within_60.hi <= 1
            if t.median_min is not None:
                assert t.soonest_min is not None and t.soonest_min <= t.median_min
        assert any(t.structures > 0 for t in msg.towns)
    finally:
        e.forecaster.shutdown()
        e.recommender.shutdown()


def test_situation_before_any_forecast_has_no_ranges():
    e = Engine()
    try:
        msg = Situation.model_validate_json(e.situation_msg())
        assert msg.forecast_tick is None and msg.towns
        assert all(t.within_30 is None and t.median_min is None for t in msg.towns)
    finally:
        e.forecaster.shutdown()
        e.recommender.shutdown()


def test_paired_plan_with_no_orders_changes_nothing():
    e = burning_engine()
    try:
        s = e.scenario
        empty = SuppressionSchedule(np.zeros((s.height, s.width), np.float32), [])
        out = evaluate_plan(e.snapshot(), empty, e.towns, e.fire.wind, 60, 1.0, n=8, seed=3)
        assert out.acres_base == out.acres_plan and out.acres_saved[0] == 0
        assert all(t.saves == 0 and t.worsens == 0 for t in out.towns)
        assert out.grids.shape == (2, s.height, s.width) and (out.grids[0] == out.grids[1]).all()
    finally:
        e.forecaster.shutdown()
        e.recommender.shutdown()


def test_a_line_of_crews_ahead_of_the_fire_saves_acres():
    e = burning_engine()
    try:
        s = e.scenario
        x, y = IGNITION
        # NE wind pushes the fire south-west; dig in on that side straight away.
        crews = [crew_layer(s.width, s.height, x - dx, y + dy, ramped=1.0) for dx, dy in ((6, 6), (10, 2), (2, 10))]
        plan = SuppressionSchedule(np.zeros((s.height, s.width), np.float32), crews)
        out = evaluate_plan(e.snapshot(), plan, e.towns, e.fire.wind, 60, 1.0, n=12, seed=1)
        assert out.acres_plan < out.acres_base
        assert out.acres_saved[0] > 0
    finally:
        e.forecaster.shutdown()
        e.recommender.shutdown()


def test_evaluate_plan_message_round_trip(monkeypatch):
    client = Capture(monkeypatch)

    async def go():
        e = burning_engine()
        try:
            await e.recommender.warm()
            x, y = IGNITION
            msg = EvaluatePlan(id=7, orders=[PlanOrder(token_type="crew", x=x - 8, y=y + 8)],
                               wind=WindState(speed_ms=4, from_deg=90), horizon_min=60)
            await e.evaluate_plan(msg)
            [res] = [m for m in client.json if m["type"] == "plan_result"]
            assert res["id"] == 7 and res["error"] is None and res["n"] > 0
            assert res["wind"] == {"speed_ms": 4, "from_deg": 90}
            [order] = res["orders"]
            assert order["counted"] and order["station"] and order["eta_min"] > 0
            assert {t["town"] for t in res["towns"]} == {t.name for t in e.towns}
            [grid] = [m for m in client.sent if isinstance(m, bytes)]
            assert grid[0] == BinaryType.PLAN_GRID and int.from_bytes(grid[4:8], "little") == 7
            assert len(grid) == 12 + 2 * e.scenario.width * e.scenario.height
        finally:
            e.forecaster.shutdown()
            e.recommender.shutdown()

    asyncio.run(go())


def test_plan_with_nothing_burning_says_so(monkeypatch):
    client = Capture(monkeypatch)

    async def go():
        e = Engine()
        try:
            await e.evaluate_plan(EvaluatePlan(id=1, orders=[], wind=None))
            [res] = [m for m in client.json if m["type"] == "plan_result"]
            assert res["error"] and res["towns"] == []
        finally:
            e.forecaster.shutdown()
            e.recommender.shutdown()

    asyncio.run(go())


def test_a_plan_replaced_while_waiting_is_skipped(monkeypatch):
    client = Capture(monkeypatch)

    async def go():
        e = burning_engine()
        try:
            e._plan_latest = 2  # plan 2 arrived while plan 1 waited for the worker
            await e.evaluate_plan(EvaluatePlan(id=1, orders=[], wind=None, horizon_min=60))
            assert not [m for m in client.json if m["type"] == "plan_result"]
        finally:
            e.forecaster.shutdown()
            e.recommender.shutdown()

    asyncio.run(go())
