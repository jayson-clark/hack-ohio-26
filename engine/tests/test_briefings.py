"""Unprompted briefings: forecast-driven events and the briefing queue."""

import asyncio
from collections import Counter

import numpy as np

from commander.briefings import MIN_GAP_S, STALE_S, STALE_SIM_MIN, BriefingQueue, ForecastWatcher, threatened_text
from forecast.runner import run_forecast
from protocol import CommanderKind, Event, EventKind
from server import Engine
from sim.fire import Wind

H, W = 20, 30
QUIET = np.zeros((2, H, W), np.float32)


def row(town, k30, k60=None, n=32, median=None, hot=False, exit_="Chico (Skyway)", status="clear"):
    return {
        "town": town,
        "fire_inside_town_now": hot,
        "fire_reaches_within_30_min": {"simulations": k30, "of": n},
        "fire_reaches_within_60_min": {"simulations": k30 if k60 is None else k60, "of": n},
        "median_minutes_until_fire": median,
        "evacuation": {"status": status, "exit": exit_, "drive_minutes": 12.0},
    }


def kinds(events):
    return [(e.kind, e.town) for e in events]


def test_threat_is_announced_once_with_numbers_and_the_way_out():
    w = ForecastWatcher()
    [e] = w.update(10, [row("Paradise", 24, median=22)], QUIET)
    assert e.kind == EventKind.TOWN_THREATENED
    assert e.text == ("Paradise is threatened: fire reaches it within 30 minutes in 24 of 32 simulations, "
                      "about 22 minutes out. Evacuate toward Chico (Skyway).")
    assert w.update(13, [row("Paradise", 30)], QUIET) == []


def test_hovering_near_the_line_does_not_chatter_and_safe_needs_two_calm_forecasts():
    # Thresholds are on the 90% Wilson interval for k of 32 (#11): threatened once
    # the low end reaches 50% (k >= 21), calm once the high end is under 50% (k <= 11).
    w = ForecastWatcher()
    assert w.update(0, [row("Magalia", 20)], QUIET) == []  # 20/32 might still be luck
    [e] = w.update(1, [row("Magalia", 22)], QUIET)
    assert e.kind == EventKind.TOWN_THREATENED
    for k in (16, 19, 13, 20):  # in between: no chatter
        assert w.update(2, [row("Magalia", k)], QUIET) == []
    assert w.update(3, [row("Magalia", 5)], QUIET) == []  # one calm forecast isn't enough
    [safe] = w.update(4, [row("Magalia", 4)], QUIET)
    assert safe.kind == EventKind.TOWN_SAFE
    assert w.update(5, [row("Magalia", 18)], QUIET) == []  # not re-threatened until the low end clears 50%


def test_fire_inside_a_town_counts_as_threatened():
    [e] = ForecastWatcher().update(0, [row("Pulga", 2, hot=True)], QUIET)
    assert e.text == "Fire is inside Pulga."


def test_cut_route_is_mentioned():
    assert threatened_text(row("Concow", 30, status="cut", exit_=None)).endswith("Its way out is cut.")


def test_forecast_shift_names_the_town_the_fire_turned_toward():
    w = ForecastWatcher()
    east = np.zeros((2, H, W), np.float32)
    east[1, :, 20:] = 1.0
    west = np.zeros((2, H, W), np.float32)
    west[1, :, :10] = 1.0
    w.update(0, [row("Paradise", 0, 2), row("Pulga", 0, 20)], east)
    [e] = w.update(40, [row("Paradise", 0, 25), row("Pulga", 0, 3)], west)
    assert e.kind == EventKind.FORECAST_SHIFT and e.town == "Paradise"
    assert e.text == "The forecast has shifted: the fire is now heading toward Paradise."


def ev(kind, town, tick=1):
    return Event(kind=kind, tick=tick, town=town, text=f"{kind} {town}")


def test_queue_orders_by_priority_and_rate_limits():
    q = BriefingQueue()
    q.offer([ev(EventKind.TOWN_SAFE, "A"), ev(EventKind.ROUTE_CHANGED, "B"), ev(EventKind.TOWN_THREATENED, "C")], 0.0)
    first = q.next(0.0, 1)
    assert first.kind == CommanderKind.BRIEFING and first.event == EventKind.TOWN_THREATENED and first.grounded
    assert q.next(1.0, 1) is None  # too soon
    assert q.next(MIN_GAP_S, 1).event == EventKind.ROUTE_CHANGED
    assert q.next(2 * MIN_GAP_S, 1).event == EventKind.TOWN_SAFE


def test_queue_dedupes_and_drops_stale_news():
    q = BriefingQueue()
    q.offer([ev(EventKind.TOWN_THREATENED, "A")], 0.0)
    assert q.next(0.0, 1) is not None
    q.offer([ev(EventKind.TOWN_THREATENED, "A")], MIN_GAP_S)  # same news again, soon after: dropped
    assert q.next(MIN_GAP_S, 1) is None
    q.offer([ev(EventKind.ROUTE_CHANGED, "B")], 100.0)
    assert q.next(100.0 + STALE_S + 1, 1) is None  # waited too long


def test_no_safe_route_absorbs_the_road_cut_for_the_same_town():
    q = BriefingQueue()
    q.offer([ev(EventKind.ROAD_CUT, "A"), ev(EventKind.ROAD_CUT, "B")], 0.0)
    q.offer([ev(EventKind.NO_SAFE_ROUTE, "A"), ev(EventKind.ROUTE_CHANGED, "A")], 0.5)
    assert kinds(p.event for p in q.pending) == [(EventKind.ROAD_CUT, "B"), (EventKind.NO_SAFE_ROUTE, "A")]


def test_steady_paradise_fire_does_not_storm():
    async def go():
        e = Engine()
        try:
            e.fire.set_wind(Wind(10, 45))
            e.fire.ignite(409.3, 118.5)  # the Camp Fire origin near Pulga, in the extended map (#197)
            events = []
            for tick in range(1, 121):
                e.fire.step()
                if tick % 6 == 0:
                    e.latest_forecast = f = run_forecast(e.fire.snapshot(), n=16, seed=tick)
                    events += e.watcher.update(e.fire.tick, e.tools.get_situation()["towns"], f.probability)
            per_town = Counter((ev.kind, ev.town) for ev in events)
            assert per_town[(EventKind.TOWN_THREATENED, "Pulga")] == 1
            assert max(per_town.values()) <= 2, per_town
            assert sum(per_town.values()) <= 8, per_town
        finally:
            e.forecaster.shutdown()
            e.long_forecaster.shutdown()
            e.recommender.shutdown()

    asyncio.run(go())


def test_older_urgent_news_is_not_starved_by_newer_news():
    q = BriefingQueue()
    q.offer([ev(EventKind.NO_SAFE_ROUTE, "Pulga")], 0.0)
    q.offer([ev(EventKind.TOWN_THREATENED, "Concow")], 3.0)
    assert q.next(3.0, 1).event == EventKind.NO_SAFE_ROUTE
    assert q.next(3.0 + MIN_GAP_S, 1).event == EventKind.TOWN_THREATENED


def test_news_expires_in_sim_time_when_the_sim_runs_fast():
    # #82: at 4x, a briefing queued at T+260 surfaced after T+904. Now it's dropped.
    q = BriefingQueue()
    q.offer([ev(EventKind.NO_SAFE_ROUTE, "Pulga", tick=255)], 0.0)
    q.offer([ev(EventKind.TOWN_THREATENED, "Magalia", tick=260)], 0.5)
    assert q.next(0.5, 260).event == EventKind.NO_SAFE_ROUTE
    # 8 s later the sim is 600 minutes on: Magalia's threat is history.
    assert q.next(0.5 + MIN_GAP_S, 860) is None and q.pending == []


def test_news_within_the_sim_window_is_still_said():
    q = BriefingQueue()
    q.offer([ev(EventKind.TOWN_THREATENED, "Concow", tick=100)], 0.0)
    assert q.next(1.0, 100 + int(STALE_SIM_MIN)).event == EventKind.TOWN_THREATENED


def test_paused_says_nothing_and_lets_nothing_expire():
    q = BriefingQueue()
    q.offer([ev(EventKind.TOWN_THREATENED, "Concow", tick=100)], 0.0)
    assert q.next(5.0, 100, paused=True) is None
    assert q.next(5.0 + STALE_S * 3, 100, paused=True) is None  # a long pause
    msg = q.next(5.0 + STALE_S * 3 + 1, 100)  # resumed: still true, so said
    assert msg is not None and msg.event == EventKind.TOWN_THREATENED
