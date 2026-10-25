"""Runtime scenario switching (#57): load_scenario rebuilds the world."""

import asyncio
import json

from protocol import Hello, LoadScenario, TokenType, VirtualTokenAdd, client_message_adapter
from server import Engine

def test_load_scenario_message_round_trips():
    raw = LoadScenario(scenario="marshall").model_dump_json()
    msg = client_message_adapter.validate_json(raw)
    assert isinstance(msg, LoadScenario) and msg.scenario == "marshall"

def test_switch_scenario_rebuilds_the_world():
    async def run():
        engine = Engine()
        try:
            assert engine.scenario.name == "paradise"
            pw, ph = engine.scenario.width, engine.scenario.height
            assert engine.fire.state.shape == (ph, pw)

            engine.switch_scenario("marshall")

            assert engine.scenario.name == "marshall"
            vw, vh = engine.scenario.width, engine.scenario.height
            assert (vw, vh) != (pw, ph)  # marshall is a different size
            # Everything scenario-derived was rebuilt to the new size.
            assert engine.fire.state.shape == (vh, vw)
            assert (engine.effects.width, engine.effects.height) == (vw, vh)
            assert engine.roads is not None and engine.roads.width == vw
            assert {t.name for t in engine.game.towns} == {"Louisville", "Superior", "Marshall", "Eldorado Springs"}
            # Fire and forecast state were reset for the new map.
            assert engine.tick == 0 and engine.latest_forecast is None
            assert engine.fire.counts() == (0, 0)
        finally:
            engine.forecaster.shutdown()
            engine.long_forecaster.shutdown()
            engine.recommender.shutdown()

    asyncio.run(run())

def test_switch_scenario_hello_reports_the_new_map():
    async def run():
        engine = Engine()
        try:
            engine.switch_scenario("marshall")
            hello = Hello.model_validate_json(engine.hello_msg())
            assert hello.scenario == "marshall"
            assert hello.map_width == engine.scenario.width
            assert hello.map_height == engine.scenario.height
        finally:
            engine.forecaster.shutdown()
            engine.long_forecaster.shutdown()
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
            engine.long_forecaster.shutdown()
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
            engine.long_forecaster.shutdown()
            engine.recommender.shutdown()

    asyncio.run(run())

def test_switch_clears_old_map_state():
    async def run():
        engine = Engine()
        try:
            engine.dispatch(VirtualTokenAdd(token_type=TokenType.CREW, x=240, y=180))
            assert engine.tracker.tokens  # a Paradise token, off marshall's 192x144 grid
            engine.switch_scenario("marshall")
            s = engine.scenario
            assert engine.tracker.tokens == []
            # Dispatch is rebuilt from marshall's own stations.json.
            names = {st.name for st in engine.stations}
            assert "Jeffco Airtanker Base" in names and "Louisville Fire Department Station #1" in names
            assert not any("Paradise" in n or "Chico" in n for n in names)
            assert engine.unit_router is not None and engine.dispatcher.units
            # The commander's town masks are rebuilt for the new grid.
            assert engine.tools.masks.shape[1:] == (s.height, s.width)
            # Held routes belong to the new map's towns.
            assert {r.town for r in engine.routes if r.bus is None} <= {t.name for t in engine.towns}
        finally:
            engine.forecaster.shutdown()
            engine.long_forecaster.shutdown()
            engine.recommender.shutdown()

    asyncio.run(run())

def test_failed_load_falls_back_to_the_previous_scenario(monkeypatch):
    async def run():
        engine = Engine()
        try:
            import server

            real = server.load_network

            def broken(d, w, h):
                if d.name == "marshall":
                    raise RuntimeError("bad roads.json")
                return real(d, w, h)

            monkeypatch.setattr(server, "load_network", broken)
            engine.switch_scenario("marshall")
            assert engine.scenario.name == "paradise"
            assert engine.fire.state.shape == (engine.scenario.height, engine.scenario.width)
        finally:
            engine.forecaster.shutdown()
            engine.long_forecaster.shutdown()
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
            engine.switch_scenario("marshall")
            fresh = {r.key: r.edges for r in engine.routes}
            engine.switch_scenario("paradise")
            # A same-named town on the old map, holding a route on the old graph.
            old = engine.routes[0]
            engine.route_tracker.shown["Superior"] = dataclasses.replace(old, town="Superior", eta_min=0.1, cost=0.1)
            engine.switch_scenario("marshall")
            assert {r.key: r.edges for r in engine.routes} == fresh
            n = len(engine.roads.edges)
            held = engine.route_tracker.held()
            assert set(held) == set(fresh) and all(e < n for _, edges in held.values() for e in edges)
        finally:
            engine.forecaster.shutdown()
            engine.long_forecaster.shutdown()
            engine.recommender.shutdown()

    asyncio.run(run())


def test_scenario_sets_its_own_wind():
    """game.json's wind is where a scenario starts, in free play and at each
    round's start; without one it's the default NE wind."""
    from protocol import SetWind, StartRound
    from sim.fire import DEFAULT_WIND

    async def run():
        engine = Engine()
        try:
            assert engine.fire.wind == DEFAULT_WIND  # paradise has none
            engine.switch_scenario("marshall")
            assert (engine.fire.wind.speed_ms, engine.fire.wind.from_deg) == (15, 255)
            engine.dispatch(SetWind(speed_ms=3, from_deg=90))
            assert engine.fire.wind.speed_ms == 3  # exercise control can still change it
            engine.dispatch(StartRound())
            assert (engine.fire.wind.speed_ms, engine.fire.wind.from_deg) == (15, 255)
        finally:
            engine.forecaster.shutdown()
            engine.recommender.shutdown()

    asyncio.run(run())
