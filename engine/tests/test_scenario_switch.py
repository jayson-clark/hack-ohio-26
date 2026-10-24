"""Runtime scenario switching (#57): load_scenario rebuilds the world."""

import asyncio
import json

from protocol import Hello, LoadScenario, TokenType, VirtualTokenAdd, client_message_adapter
from server import Engine

def test_load_scenario_message_round_trips():
    raw = LoadScenario(scenario="valley").model_dump_json()
    msg = client_message_adapter.validate_json(raw)
    assert isinstance(msg, LoadScenario) and msg.scenario == "valley"

def test_switch_scenario_rebuilds_the_world():
    async def run():
        engine = Engine()
        try:
            assert engine.scenario.name == "paradise"
            pw, ph = engine.scenario.width, engine.scenario.height
            assert engine.fire.state.shape == (ph, pw)

            engine.switch_scenario("valley")

            assert engine.scenario.name == "valley"
            vw, vh = engine.scenario.width, engine.scenario.height
            assert (vw, vh) != (pw, ph)  # the valley is a different size
            # Everything scenario-derived was rebuilt to the new size.
            assert engine.fire.state.shape == (vh, vw)
            assert (engine.effects.width, engine.effects.height) == (vw, vh)
            assert engine.roads is not None and engine.roads.width == vw
            assert {t.name for t in engine.game.towns} == {"Millbrook", "Cedar Flats", "Ridgeview"}
            # Fire and forecast state were reset for the new map.
            assert engine.tick == 0 and engine.latest_forecast is None
            assert engine.fire.counts() == (0, 0)
        finally:
            engine.forecaster.shutdown()
            engine.recommender.shutdown()

    asyncio.run(run())

def test_switch_scenario_hello_reports_the_new_map():
    async def run():
        engine = Engine()
        try:
            engine.switch_scenario("valley")
            hello = Hello.model_validate_json(engine.hello_msg())
            assert hello.scenario == "valley"
            assert hello.map_width == engine.scenario.width
            assert hello.map_height == engine.scenario.height
        finally:
            engine.forecaster.shutdown()
            engine.recommender.shutdown()

    asyncio.run(run())

def test_switch_to_same_scenario_is_a_noop():
    async def run():
        engine = Engine()
        try:
            fire_before = engine.fire
            engine.switch_scenario("paradise")  # already on paradise
            assert engine.fire is fire_before  # nothing was rebuilt
        finally:
            engine.forecaster.shutdown()
            engine.recommender.shutdown()

    asyncio.run(run())

def test_switch_to_unknown_scenario_is_ignored():
    async def run():
        engine = Engine()
        try:
            engine.switch_scenario("does-not-exist")
            assert engine.scenario.name == "paradise"  # stayed put, no crash
        finally:
            engine.forecaster.shutdown()
            engine.recommender.shutdown()

    asyncio.run(run())

def test_switch_clears_old_map_state():
    async def run():
        engine = Engine()
        try:
            engine.dispatch(VirtualTokenAdd(token_type=TokenType.CREW, x=240, y=180))
            assert engine.tracker.tokens  # a Paradise token, off the valley's 160x120 grid
            engine.switch_scenario("valley")
            s = engine.scenario
            assert engine.tracker.tokens == []
            # Dispatch is rebuilt from the valley's own stations.json.
            assert {st.name for st in engine.stations} == {
                "Millbrook Station", "Cedar Flats Station", "Valley Air Attack Base"}
            assert engine.unit_router is not None and engine.dispatcher.units
            # The commander's town masks are rebuilt for the new grid.
            assert engine.tools.masks.shape[1:] == (s.height, s.width)
            # Held routes belong to the new map's towns.
            assert {r.town for r in engine.routes if r.bus is None} <= {t.name for t in engine.towns}
        finally:
            engine.forecaster.shutdown()
            engine.recommender.shutdown()

    asyncio.run(run())

def test_failed_load_falls_back_to_the_previous_scenario(monkeypatch):
    async def run():
        engine = Engine()
        try:
            import server

            real = server.load_network

            def broken(d, w, h):
                if d.name == "valley":
                    raise RuntimeError("bad roads.json")
                return real(d, w, h)

            monkeypatch.setattr(server, "load_network", broken)
            engine.switch_scenario("valley")
            assert engine.scenario.name == "paradise"
            assert engine.fire.state.shape == (engine.scenario.height, engine.scenario.width)
        finally:
            engine.forecaster.shutdown()
            engine.recommender.shutdown()

    asyncio.run(run())


def test_switch_keeps_only_the_new_maps_routes():
    """Routes held from the old map never survive a switch, even for a town
    with the same name, and the new map's first routes stay held (as at
    startup) so the first replan there still gets hysteresis."""
    import dataclasses

    async def run():
        engine = Engine()
        try:
            engine.switch_scenario("valley")
            fresh = {r.key: r.edges for r in engine.routes}
            engine.switch_scenario("paradise")
            # A same-named town on the old map, holding a route on the old graph.
            old = engine.routes[0]
            engine.route_tracker.shown["Millbrook"] = dataclasses.replace(old, town="Millbrook", eta_min=0.1, cost=0.1)
            engine.switch_scenario("valley")
            assert {r.key: r.edges for r in engine.routes} == fresh
            n = len(engine.roads.edges)
            held = engine.route_tracker.held()
            assert set(held) == set(fresh) and all(e < n for _, edges in held.values() for e in edges)
        finally:
            engine.forecaster.shutdown()
            engine.recommender.shutdown()

    asyncio.run(run())
