import asyncio

import numpy as np
import pytest

from commander.briefings import evacuate_text
from protocol import EvacClock, EvacStatus, EventKind, OrderEvacuation
from routing.clearance import MOBILIZE_MIN, PEOPLE_PER_VEHICLE, compute_clock
from routing.roads import build_network
from server import Engine

W, H = 60, 20


def _net():
    """Big town A and small town B share one secondary road to the exit.
    A reaches the junction on a primary road, B on a tertiary one."""
    nodes = [[5, 10], [5, 3], [20, 10], [55, 10]]
    edges = [[0, 2, 1500, "primary"], [1, 2, 1600, "tertiary"], [2, 3, 3500, "secondary"]]
    towns = [
        {"name": "A", "x": 5, "y": 10, "radius": 2, "population": 2000 * PEOPLE_PER_VEHICLE, "structures": 1},
        {"name": "B", "x": 5, "y": 3, "radius": 1, "population": 200 * PEOPLE_PER_VEHICLE, "structures": 1},
    ]
    return build_network(nodes, edges, W, H, towns, [{"name": "Exit", "x": 55, "y": 10}])


def _clock(net, first_burn=None, orders=None, closed=None):
    clocks = compute_clock(net, first_burn, tick=0, forecast_tick=0, horizon_min=600, orders=orders or {},
                           evacuated=[0.0] * len(net.towns), minutes_per_tick=1.0, closed=closed)
    return {c.town: c for c in clocks}


def _fire_in_town(net, town: int, ticks: list[float]):
    """A forecast where the fire enters `town` at ticks[i] in rollout i and burns nothing else."""
    t = net.towns[town]
    fb = np.full((len(ticks), H, W), np.inf, np.float32)
    cy, cx = np.mgrid[:H, :W] + 0.5
    disk = np.hypot(cx - t.x, cy - t.y) <= t.radius
    for i, a in enumerate(ticks):
        fb[i][disk] = a
    return fb


def test_clearance_is_the_bottleneck_queue():
    c = _clock(_net())
    # 2,000 cars through the 1,100 an hour secondary road.
    assert c["A"].clearance_min == pytest.approx(2000 / 1100 * 60, abs=0.1)
    assert c["B"].clearance_min == pytest.approx(200 / 900 * 60, abs=0.1)  # its own tertiary road
    assert [x.safe_zone for x in c["A"].exits] == ["Exit"] and c["A"].exits[0].bottleneck_vph == 1100
    assert c["A"].status == EvacStatus.WATCH and c["A"].order_by_tick is None  # no forecast yet


def test_ordered_towns_share_the_road_fairly():
    alone = _clock(_net())
    with_a = _clock(_net(), orders={"A": 0})
    with_b = _clock(_net(), orders={"B": 0})
    # B merges into A's traffic and takes turns with it: 200 of its own plus
    # 200 of A's go through before B is clear.
    assert with_a["B"].clearance_min == pytest.approx(400 / 1100 * 60, abs=0.1)
    assert with_a["B"].shares_with == ["A"]
    # A waits for everything on the road.
    assert with_b["A"].clearance_min == pytest.approx(2200 / 1100 * 60, abs=0.1)
    assert with_b["A"].clearance_min > alone["A"].clearance_min
    assert with_a["A"].status == EvacStatus.EVACUATING and with_a["A"].people_per_min > 0


def test_order_by_and_status_follow_fire_arrival():
    net = _net()
    need = MOBILIZE_MIN + 2000 / 1100 * 60  # ~129 min until A's last car is out
    watch = _clock(net, _fire_in_town(net, 0, [300.0] * 32))["A"]
    assert watch.status == EvacStatus.WATCH and watch.order_by_tick == round(300 - need)
    assert watch.k_safe == 32 and watch.fire_tick == 300

    soon = _clock(net, _fire_in_town(net, 0, [need + 10] * 32))["A"]
    assert soon.status == EvacStatus.ORDER_SOON

    # Past the order-by time, but half the simulations still get everyone out.
    now = _clock(net, _fire_in_town(net, 0, [100.0] * 16 + [400.0] * 16))["A"]
    assert now.status == EvacStatus.ORDER_NOW and now.k_safe == 16

    late = _clock(net, _fire_in_town(net, 0, [100.0] * 32))["A"]
    assert late.status == EvacStatus.LATE and late.k_safe == 0


def test_fire_beyond_the_forecast_only_bounds_the_order_time():
    net = _net()
    c = _clock(net, _fire_in_town(net, 0, [np.inf] * 32))["A"]
    assert c.status == EvacStatus.WATCH and c.fire_tick is None and c.reach == 0
    assert c.order_by_bound and c.order_by_tick == round(600 - MOBILIZE_MIN - 2000 / 1100 * 60)


def test_evacuees_keep_to_bigger_roads():
    # A short residential cut-through and a slightly longer primary road.
    nodes = [[2, 10], [30, 10], [58, 10], [30, 2]]
    edges = [[0, 1, 2600, "residential"], [1, 2, 2600, "residential"],
             [0, 3, 2900, "primary"], [3, 2, 2900, "primary"]]
    town = {"name": "T", "x": 2, "y": 10, "radius": 1, "population": 1600, "structures": 1}
    net = build_network(nodes, edges, W, H, [town], [{"name": "Exit", "x": 58, "y": 10}])
    [c] = compute_clock(net, None, tick=0, forecast_tick=0, horizon_min=600, orders={}, evacuated=[0.0],
                        minutes_per_tick=1.0)
    assert c.exits[0].bottleneck_vph == 1800


def test_a_town_with_every_road_burning_is_trapped():
    net = _net()
    c = _clock(net, closed=np.ones(len(net.edges), bool))
    assert c["A"].status == EvacStatus.TRAPPED and c["A"].exits == [] and c["A"].last_car_out_tick is None


def test_evacuate_text_uses_the_clock_numbers():
    net = _net()
    c = _clock(net, _fire_in_town(net, 0, [100.0] * 16 + [400.0] * 16))["A"]
    text = evacuate_text(c, 0)
    assert text.startswith("Order A out now") and "3,200 people" in text and "1.7 hours" in text
    late = _clock(net, _fire_in_town(net, 0, [100.0] * 32))["A"]
    assert "0 of 32 simulations" in evacuate_text(late, 0)


def test_engine_orders_a_town_out_and_people_leave():
    async def run():
        engine = Engine()
        try:
            msg = EvacClock.model_validate_json(engine.clock_msg())
            assert {t.town for t in msg.towns} == {t.name for t in engine.towns}

            engine.dispatch(OrderEvacuation(town="Paradise", ordered=True))
            await engine._clock_job
            row = next(c for c in engine.evac_clock if c.town == "Paradise")
            assert row.status == EvacStatus.EVACUATING and row.ordered_tick == engine.fire.tick
            assert engine.evac_flows() == {}  # still mobilising

            engine.evac_orders["Paradise"] = engine.fire.tick - round(MOBILIZE_MIN)
            engine.score_step([])
            i = next(i for i, t in enumerate(engine.game.towns) if t.name == "Paradise")
            assert engine.game.evacuated[i] == pytest.approx(row.people_per_min)

            engine.dispatch(OrderEvacuation(town="Paradise", ordered=False))
            assert "Paradise" not in engine.evac_orders
        finally:
            engine.forecaster.shutdown()
            engine.long_forecaster.shutdown()

    asyncio.run(run())


def test_engine_announces_a_town_once_when_its_order_comes_due():
    async def run():
        engine = Engine()
        try:
            net = engine.roads
            i = next(i for i, t in enumerate(net.towns) if t.name == "Paradise")
            fb = np.full((32, net.height, net.width), np.inf, np.float32)
            fb.reshape(32, -1)[:, engine.tools.masks[i].ravel()] = 30.0
            engine.long_forecast = type("F", (), {"tick": 0, "first_burn": fb})()
            clocks = engine.compute_clock(0)
            events = engine.evac_events(clocks, 0)
            # Butte Creek Canyon's disk overlaps Paradise's, so it's due too.
            assert (EventKind.EVACUATE_NOW, "Paradise") in [(e.kind, e.town) for e in events]
            assert engine.evac_events(clocks, 0) == []  # said once
        finally:
            engine.forecaster.shutdown()
            engine.long_forecaster.shutdown()

    asyncio.run(run())
