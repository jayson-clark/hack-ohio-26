"""Re-routing between forecasts: hysteresis, live road cuts, and buses."""

import asyncio

import numpy as np

from protocol import EventKind
from routing.evac import Route, burning_edges, plan_routes, replan_routes
from routing.roads import build_network
from routing.tracker import MIN_DWELL_TICKS, RouteTracker
from server import Engine
from sim.fire import BURNING


def _route(edges, cost, risk=0.0, status="clear", zone="Exit", town="T"):
    return Route(town=town, safe_zone=None if status == "cut" else zone, status=status, risk=risk,
                 nodes=list(range(len(edges) + 1)), edges=list(edges), cost=cost)


def test_near_equal_routes_dont_flicker():
    tr = RouteTracker()
    a, b = _route([1, 2], 100.0), _route([3, 4], 98.0)
    shown, _ = tr.choose([a], {}, tick=0)
    assert shown[0].edges == [1, 2]
    for tick in range(1, 100, 3):
        # B is the "best" by a hair every other forecast; A stays on screen.
        best = b if tick % 2 else a
        shown, events = tr.choose([best], {"T": _route([1, 2], 100.0)}, tick)
        assert shown[0].edges == [1, 2] and not events


def test_clearly_better_route_waits_for_dwell_then_switches():
    tr = RouteTracker()
    tr.choose([_route([1, 2], 100.0, risk=0.6)], {}, tick=0)
    better = _route([3, 4], 50.0, risk=0.1)
    shown, events = tr.choose([better], {"T": _route([1, 2], 100.0, risk=0.6)}, tick=1)
    assert shown[0].edges == [1, 2] and not events  # too soon
    shown, events = tr.choose([better], {"T": _route([1, 2], 100.0, risk=0.6)}, tick=MIN_DWELL_TICKS)
    assert shown[0].edges == [3, 4]
    assert [e.kind for e in events] == [EventKind.ROUTE_CHANGED]
    assert "likely to burn" in events[0].text


def test_cut_route_switches_at_once_and_no_route_is_announced_once():
    tr = RouteTracker()
    tr.choose([_route([1, 2], 100.0)], {}, tick=0)
    shown, events = tr.choose([_route([3, 4], 120.0)], {"T": _route([1, 2], 0.0, status="cut")}, tick=1)
    assert shown[0].edges == [3, 4] and "is cut" in events[0].text
    cut = _route([], 0.0, status="cut")
    _, events = tr.choose([cut], {"T": _route([3, 4], 0.0, status="cut")}, tick=2)
    assert [e.kind for e in events] == [EventKind.NO_SAFE_ROUTE]
    _, events = tr.choose([cut], {}, tick=3)
    assert not events


def _two_road_net():
    # Same layout as test_routing: direct road along y=10, detour via y=2.
    W, H = 40, 20
    nodes = [[2, 10], [20, 10], [38, 10], [2, 2], [38, 2]]
    edges = [[0, 1, 1700, "primary"], [1, 2, 1700, "primary"],
             [0, 3, 750, "tertiary"], [3, 4, 3400, "tertiary"], [4, 2, 750, "tertiary"]]
    town = {"name": "T", "x": 2, "y": 10, "radius": 1, "population": 1, "structures": 1}
    return build_network(nodes, edges, W, H, [town], [{"name": "Exit", "x": 38, "y": 10}])


def test_burning_road_closes_its_edge_and_forces_the_detour():
    net = _two_road_net()
    state = np.ones((net.height, net.width), np.uint8)
    state[10, 25] = BURNING  # on the direct road's second edge
    closed = burning_edges(net, state, BURNING)
    assert closed.tolist() == [False, True, False, False, False]
    [r] = plan_routes(net, None, closed=closed, minutes_per_tick=1.0)
    assert r.length_m == 4900 and 1 not in r.edges


def test_replan_rescores_the_held_route_under_the_new_forecast():
    net = _two_road_net()
    [direct] = plan_routes(net, None, minutes_per_tick=1.0)
    closed = np.zeros(len(net.edges), bool)
    closed[1] = True
    best, rescored = replan_routes(net, None, {"T": (direct.nodes, direct.edges)},
                                   closed=closed, minutes_per_tick=1.0)
    assert rescored["T"].status == "cut" and best[0].status == "clear"


def test_bus_gets_its_own_route_from_where_it_stands():
    net = _two_road_net()
    routes = plan_routes(net, None, buses=[("v7", 3.0, 2.5)], minutes_per_tick=1.0)
    bus = next(r for r in routes if r.bus == "v7")
    assert bus.town == "Bus v7" and bus.key == "bus:v7"
    assert bus.points[0] == [2.0, 2.0] and bus.safe_zone == "Exit"


def test_engine_replans_when_fire_reaches_a_shown_route():
    async def run():
        engine = Engine()
        try:
            route = next(r for r in engine.routes if len(r.edges) > 2)
            eid = route.edges[len(route.edges) // 2]
            net = engine.roads
            cells = net.sample_cell[net.sample_start[eid]:]
            engine.fire.state.reshape(-1)[cells[0]] = BURNING
            engine.check_road_cuts()
            assert engine._closed[eid] and engine._route_job is not None
            await engine._route_job
            new = next(r for r in engine.routes if r.key == route.key)
            assert eid not in new.edges
        finally:
            engine.forecaster.shutdown()
            engine.long_forecaster.shutdown()

    asyncio.run(run())


def test_reroute_to_the_same_exit_says_another_road():
    tr = RouteTracker()
    tr.choose([_route([1, 2], 100.0)], {}, tick=0)
    _, events = tr.choose([_route([3, 4], 120.0)], {"T": _route([1, 2], 0.0, status="cut")}, tick=1)
    assert events[0].text == "Rerouting T by another road to Exit: the current road is cut."
