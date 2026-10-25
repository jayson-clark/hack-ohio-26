"""The commander's simulation tools, on Paradise with a seeded fire."""

import asyncio
import json

import pytest

import commander.tools as tools_mod
from commander.tools import TOOL_SPECS, CommanderTools, compass
from forecast.runner import run_forecast
from server import Engine
from sim.fire import Wind


def burning_engine(ticks: int = 30) -> Engine:
    """An engine with the Camp Fire start burning under a NE wind, and a fresh forecast."""
    e = Engine()
    e.fire.set_wind(Wind(10, 45))
    e.fire.ignite(409.3, 118.5)
    for _ in range(ticks):
        e.fire.step()
    e.latest_forecast = run_forecast(e.fire.snapshot(), seed=0)
    return e


def with_engine(fn, ticks: int = 30):
    async def go():
        e = burning_engine(ticks)
        try:
            await e.recommender.warm()
            return await fn(e, CommanderTools(e))
        finally:
            e.forecaster.shutdown()
            e.long_forecaster.shutdown()
            e.recommender.shutdown()

    return asyncio.run(go())


def test_tool_specs_are_well_formed():
    names = [t["name"] for t in TOOL_SPECS]
    assert names == ["get_situation", "forecast_whatif", "evaluate_placement", "get_routes"]
    for t in TOOL_SPECS:
        schema = t["input_schema"]
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == set(schema["properties"])


def test_compass():
    assert [compass(d) for d in (0, 44, 90, 270, 315, 359)] == [
        "north", "north-east", "east", "west", "north-west", "north",
    ]


def test_situation_reports_every_town_from_the_forecast():
    async def check(e, tools):
        out = await tools.call("get_situation", {})
        json.dumps(out)  # must be plain JSON for the model
        assert out["wind"]["from"] == "north-east" and out["fire"]["active"]
        assert {t["town"] for t in out["towns"]} == {t.name for t in e.towns}
        pulga = next(t for t in out["towns"] if t["town"] == "Pulga")
        reach = pulga["fire_reaches_within_60_min"]
        assert reach["of"] == 32 and reach["simulations"] >= pulga["fire_reaches_within_30_min"]["simulations"]
        assert pulga["evacuation"]["exit"] or pulga["evacuation"]["status"] == "cut"

    with_engine(check)


def test_whatif_compares_with_the_current_forecast():
    async def check(e, tools):
        out = await tools.call("forecast_whatif", {"wind_from": "east", "wind_speed_ms": 12})
        json.dumps(out)
        assert out["hypothetical_wind"]["from"] == "east" and out["hypothetical_wind"]["speed_ms"] == 12
        row = out["towns"][0]
        assert "fire_reaches_within_60_min" in row and "current_forecast_reaches_within_60_min" in row
        bad = await tools.call("forecast_whatif", {"wind_from": "sideways", "wind_speed_ms": None})
        assert "error" in bad

    with_engine(check)


def test_placement_by_name_and_unknown_place():
    async def check(e, tools):
        out = await tools.call("evaluate_placement", {"place": "concow", "x": None, "y": None})
        json.dumps(out)
        assert out["placement"]["at"] == "Concow" and isinstance(out["helps"], bool)
        # A crew has to drive there first (#104), and the answer says from where and how long.
        assert out["placement"]["from_station"] and out["placement"]["minutes_to_arrive"] > 0
        bad = await tools.call("evaluate_placement", {"place": "Atlantis", "x": None, "y": None})
        assert "unknown place" in bad["error"] and "Paradise" in bad["error"]

    with_engine(check)


def test_routes_and_recent_changes():
    async def check(e, tools):
        out = await tools.call("get_routes", {})
        json.dumps(out)
        assert len(out["routes"]) == len(e.routes) and "recent_changes" in out

    with_engine(check)


def test_slow_tool_times_out_cleanly(monkeypatch):
    monkeypatch.setattr(tools_mod, "TOOL_TIMEOUT_S", 0.0001)

    async def check(e, tools):
        out = await tools.call("forecast_whatif", {"wind_from": "west", "wind_speed_ms": None})
        assert "took too long" in out["error"]

    with_engine(check)


def test_no_fire_means_no_whatif():
    async def go():
        e = Engine()
        try:
            out = await CommanderTools(e).call("forecast_whatif", {"wind_from": "west", "wind_speed_ms": None})
            assert "nothing is burning" in out["error"]
        finally:
            e.forecaster.shutdown()
            e.long_forecaster.shutdown()
            e.recommender.shutdown()

    asyncio.run(go())


@pytest.mark.parametrize("args", [{"bogus": 1}, {"wind_from": "west"}])
def test_bad_arguments_become_errors(args):
    async def go():
        e = Engine()
        try:
            out = await CommanderTools(e).call("forecast_whatif", args)
            assert "error" in out
        finally:
            e.forecaster.shutdown()
            e.long_forecaster.shutdown()
            e.recommender.shutdown()

    asyncio.run(go())
