"""Fire units come from stations; tokens are orders (#104)."""

import json
import math

import numpy as np
import pytest

from protocol import Token, TokenSource, TokenType, VirtualTokenAdd
from routing.roads import build_network
from routing.units import TANKER_MAX_WIND_MS, TURNOUT_MIN, Station, UnitRouter
from sim.dispatch import Dispatcher

W, H = 40, 20
CELL_M = 94.0


def two_road_net():
    # A direct road along y=10 and a detour via y=2, from (2, 10) to (38, 10).
    nodes = [[2, 10], [20, 10], [38, 10], [2, 2], [38, 2]]
    edges = [[0, 1, 1700, "primary"], [1, 2, 1700, "primary"],
             [0, 3, 750, "tertiary"], [3, 4, 3400, "tertiary"], [4, 2, 750, "tertiary"]]
    return build_network(nodes, edges, W, H)


def tok(i, tt, x, y):
    return Token(id=i, token_type=tt, x=x, y=y, angle=0.0, source=TokenSource.VIRTUAL)


@pytest.fixture
def router():
    return UnitRouter(two_road_net(), CELL_M)


def test_ground_eta_drives_the_road_and_detours_round_fire(router):
    eta, path = router.ground_eta(2, 10, 38, 10)
    assert eta == pytest.approx(3400 * 60 / 50_000, rel=1e-6)  # 3.4 km at 50 km/h, on-road both ends
    assert path[0] == [2, 10] and path[-1] == [38, 10]
    closed = np.zeros(5, bool)
    closed[1] = True  # the direct road burns
    router.refresh(closed)
    detour, _ = router.ground_eta(2, 10, 38, 10)
    assert detour == pytest.approx(4900 * 60 / 50_000, rel=1e-6)
    closed[:] = True
    router.refresh(closed)
    assert router.ground_eta(2, 10, 38, 10)[0] == math.inf


def test_grid_matches_point_eta_and_adds_the_hike(router):
    grid = router.ground_grid(2, 10)
    eta, _ = router.ground_eta(2, 10, 38.5, 10.5)
    assert grid[10, 38] == pytest.approx(eta, rel=1e-4)
    assert grid[18, 38] > grid[10, 38]  # 8 cells off the road is a walk


STATIONS = [
    Station("West", 2, 10, "ground", {"crew": 1}),
    Station("East", 38, 10, "ground", {"crew": 1}),
    Station("Air", -50, 10, "air", {"water": 1}),
]


def step(d, tokens, tick, wind=8.0, closed=None):
    return {t.id for t in d.update(tokens, tick, wind, closed)}


def test_nearest_unit_goes_and_the_token_acts_only_on_arrival(router):
    d = Dispatcher(STATIONS, router)
    crew = tok("c1", TokenType.CREW, 36, 10)
    assert step(d, [crew], 0) == set()
    [u] = [u for u in d.units if u.token_id == "c1"]
    assert u.station.name == "East" and u.status == "en_route"
    arrive = u.arrive_tick
    assert arrive == math.ceil(TURNOUT_MIN + router.ground_eta(38, 10, 36, 10)[0])
    assert step(d, [crew], arrive - 1) == set()
    assert step(d, [crew], arrive) == {"c1"}
    assert [e.kind for e in d.take_events()] == ["arrived"]


def test_out_of_units_means_the_token_waits_and_removal_frees_one(router):
    d = Dispatcher(STATIONS, router)
    a, b, c = (tok(i, TokenType.CREW, 20, 10) for i in ("a", "b", "c"))
    step(d, [a, b, c], 0)
    assert {u.token_id for u in d.units if u.token_type == TokenType.CREW} == {"a", "b"}
    step(d, [b, c], 1)  # a is picked up: its unit is free for c
    assert {u.token_id for u in d.units if u.token_type == TokenType.CREW} == {"b", "c"}


def test_moving_a_token_reroutes_its_unit(router):
    d = Dispatcher(STATIONS, router)
    step(d, [tok("c1", TokenType.CREW, 36, 10)], 0)
    [u] = [u for u in d.units if u.token_id == "c1"]
    first = u.arrive_tick
    step(d, [tok("c1", TokenType.CREW, 36, 10)], first)
    assert u.status == "working"
    step(d, [tok("c1", TokenType.CREW, 4, 10)], first + 1)  # moved across the map
    assert u.status == "en_route" and u.arrive_tick > first + 1


def test_tankers_wait_out_high_wind_then_fly(router):
    d = Dispatcher(STATIONS, router)
    water = tok("w1", TokenType.WATER, 20, 10)
    assert step(d, [water], 0, wind=TANKER_MAX_WIND_MS + 1) == set()
    [u] = [u for u in d.units if u.token_type == TokenType.WATER]
    assert u.status == "grounded" and [e.kind for e in d.take_events()] == ["grounded"]
    step(d, [water], 5, wind=TANKER_MAX_WIND_MS + 1)  # still too windy on the retry
    step(d, [water], 10, wind=TANKER_MAX_WIND_MS + 1)
    assert u.status == "grounded" and d.take_events() == []  # announced once, not every retry
    step(d, [water], 15, wind=5.0)  # retry in calm air
    assert u.status == "en_route"


def test_blocked_when_fire_cuts_every_road(router):
    d = Dispatcher([Station("West", 2, 10, "ground", {"crew": 1})], router)
    closed = np.ones(5, bool)
    assert step(d, [tok("c1", TokenType.CREW, 38, 10)], 0, closed=closed) == set()
    [u] = d.units
    assert u.status == "blocked" and [e.kind for e in d.take_events()] == ["blocked"]


def test_no_stations_means_tokens_act_at_once():
    d = Dispatcher([], None)
    assert step(d, [tok("c1", TokenType.CREW, 5, 5)], 0) == {"c1"}


def test_eta_grid_uses_free_units_and_respects_wind(router):
    d = Dispatcher(STATIONS, router)
    crews = d.eta_grid(TokenType.CREW, 8.0)
    assert crews[10, 36] < crews[10, 4] + 30  # finite everywhere on this little map
    assert np.isfinite(d.eta_grid(TokenType.WATER, 8.0)).all()
    assert np.isinf(d.eta_grid(TokenType.WATER, TANKER_MAX_WIND_MS + 1)).all()


def test_engine_tokens_wait_for_their_unit_and_units_go_on_the_wire():
    import asyncio

    from server import Engine

    async def go():
        e = Engine()
        try:
            hello = json.loads(e.hello_msg())
            assert {s["kind"] for s in hello["stations"]} == {"ground", "air"}
            e.fire.ignite(217.3, 54.5)
            e.virtual.handle(VirtualTokenAdd(token_type=TokenType.CREW, x=200, y=70))
            e.step_fire()
            assert e.fire.suppression.max() == 0  # the crew isn't there yet
            units = json.loads(e.units_msg())["units"]
            [moving] = [u for u in units if u["status"] == "en_route"]
            assert moving["eta_min"] > 0 and len(moving["path"]) >= 2
            for _ in range(int(moving["eta_min"]) + 2):
                e.step_fire()
            assert e.fire.suppression.max() > 0  # on scene and digging in
        finally:
            e.forecaster.shutdown()
            e.recommender.shutdown()

    asyncio.run(go())


def test_recommendations_skip_unreachable_spots_and_credit_late_arrival_less():
    from forecast.recommend import recommend
    from forecast.runner import run_forecast
    from test_recommend import TOWN, chokepoint_snapshot

    snap = chokepoint_snapshot()
    p30 = run_forecast(snap, n=16, seed=0).probability[0]
    soon = np.zeros(p30.shape)
    late = np.full(p30.shape, 45.0)
    never = np.full(p30.shape, np.inf)
    now = recommend(snap, p30, [TOWN], n=12, seed=3, eta=soon)
    later = recommend(snap, p30, [TOWN], n=12, seed=3, eta=late)
    assert recommend(snap, p30, [TOWN], n=12, seed=3, eta=never) == []
    assert now and now[0].eta_min == 0
    assert not later or later[0].benefit < now[0].benefit  # a crew 45 min out helps less, or not at all
