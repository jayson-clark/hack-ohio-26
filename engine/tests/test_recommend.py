"""Crew placement recommendations."""

import asyncio
import math

import numpy as np

from forecast.recommend import Rec, TownEffect, TownInfo, TownShare, candidates, describe, recommend
from forecast.runner import run_forecast
from protocol import Recommendation, TokenType
from server import Engine
from sim.effects import CREW_RADIUS
from sim.fire import FireSim, Wind, build_layers
from test_fire import H, W, flat, run

GAP = (51.0, 32.0)  # the only way through the wall


def chokepoint_snapshot():
    """Fire in the west, a town in the east, and an unburnable wall between
    them with one gap: the place a single crew can save the town."""
    scen = flat()
    fuel = np.ones((H, W), np.float32)
    fuel[:, 49:54] = 0.0
    fuel[28:37, 49:54] = 1.0
    sim = FireSim(scen, seed=0)
    sim.layers = build_layers(scen, fuel=fuel)
    sim.reset()
    sim.set_wind(Wind(8, 270))
    sim.ignite(30, 32, radius=3)
    return run(sim, 12).snapshot()


TOWN = TownInfo("Eastville", 80, 32, 8, 1000)


def test_chokepoint_ranks_first_and_saves_the_town():
    snap = chokepoint_snapshot()
    f = run_forecast(snap, n=16, seed=0)
    # 75 minutes' look-ahead: long enough for the fire to reach the town, short
    # enough that one crew at the gap can keep it out.
    recs = recommend(snap, f.probability[0], [TOWN], k=8, n=12, seed=3, horizon=75)
    assert recs, "expected at least one helpful placement"
    best = recs[0]
    assert math.hypot(best.x - GAP[0], best.y - GAP[1]) < 8, best
    [save] = best.saves
    # A crew is 0.9 suppression, not a wall, so it holds the gap often but not always.
    # The shown counts come from the fresh-seed check (16 rollouts).
    assert save.town == "Eastville" and save.n == 16 and save.hits / save.n >= 0.25
    assert save.lo < save.hits / save.n < save.hi
    # Only shown because even the low end of its benefit interval helps (#11).
    assert best.benefit_lo > 0 and best.benefit_lo <= best.benefit <= best.benefit_hi
    assert best.confidence in ("high", "moderate")
    assert all(r.benefit > 0 for r in recs)
    assert [r.benefit for r in recs] == sorted((r.benefit for r in recs), reverse=True)


def test_candidates_sit_on_the_front_and_keep_apart():
    snap = chokepoint_snapshot()
    p30 = run_forecast(snap, n=16, seed=0).probability[0]
    spots = candidates(snap, p30, [TOWN], k=6)
    assert spots
    for i, (x, y) in enumerate(spots):
        assert 0.2 <= p30[int(y), int(x)] <= 0.8
        for x2, y2 in spots[i + 1:]:
            assert math.hypot(x - x2, y - y2) >= 2 * CREW_RADIUS


def test_no_front_no_recommendations():
    snap = FireSim(flat(), seed=0).snapshot()  # nothing burning
    assert recommend(snap, np.zeros((H, W), np.float32), [TOWN]) == []


def test_describe_reads_naturally():
    saves = Rec(1, 2, 50.0, 20.0, saves=[TownEffect("Paradise", 6, 8)], worsens=[TownEffect("Concow", 1, 8)])
    assert describe(saves, 2.18) == (
        "A crew here keeps the fire out of Paradise in 6 of 8 simulations, but pushes it into Concow in 1 of 8."
    )
    shield = Rec(1, 2, 700.0, 100.0, protects=[TownShare("Paradise", 0.123)])
    assert describe(shield, 2.18) == "A crew here shields Paradise: about 12% less of it burns in the next two hours."
    acres = Rec(1, 2, 30.0, 143.0)
    assert describe(acres, 2.18) == "A crew here holds back about 310 acres over the next two hours."


def test_accepting_a_recommendation_places_a_virtual_crew():
    async def run_engine():
        engine = Engine()
        try:
            engine.recs = [Recommendation(id="r5-0", token_type=TokenType.CREW, action="place", x=120.5, y=80.5,
                                          move_token=None, from_x=None, from_y=None, auto=True, benefit=3.0,
                                          benefit_lo=1.0, benefit_hi=5.0, confidence="moderate", station=None, eta_min=None, fire_arrival_min=None, act_by_min=None,
                                          acres_saved=10.0, acres_saved_lo=5.0, acres_saved_hi=15.0, saves=[], worsens=[], protects=[], text="")]
            engine.accept_recommendation("r5-0")
            [crew] = engine.tracker.tokens
            assert crew.token_type == TokenType.CREW and (crew.x, crew.y) == (120.5, 80.5)
            assert engine.recs == []
            engine.accept_recommendation("r5-0")  # stale id: ignored
            assert len(engine.tracker.tokens) == 1
        finally:
            engine.forecaster.shutdown()
            engine.long_forecaster.shutdown()
            engine.recommender.shutdown()

    asyncio.run(run_engine())


def test_two_hour_lookahead_keeps_the_chokepoint_and_says_when_to_act():
    """The default two-hour look-ahead: one crew only delays the fire past the
    gap, so it may not keep the town clear, but the gap is still the best
    spot. It comes with when fire reaches the crew's area and how long the
    operator can wait before dispatching (arrival minus travel time)."""
    snap = chokepoint_snapshot()
    p30 = run_forecast(snap, n=16, seed=0).probability[0]
    late = np.full(p30.shape, 5.0)  # every spot is 5 min away
    [best, *_] = recommend(snap, p30, [TOWN], n=12, seed=3, eta=late)
    assert math.hypot(best.x - GAP[0], best.y - GAP[1]) < 8, best
    assert best.benefit_lo > 0
    assert best.fire_arrival_min is not None and best.fire_arrival_min > 0
    assert best.act_by_min == round(best.fire_arrival_min - 5.0, 1)


def _tired_at_gap(fade_at: int):
    """The chokepoint world with a crew holding the gap, tiring from `fade_at`."""
    from forecast.recommend import TiredCrew
    from sim.effects import crew_layer

    snap = chokepoint_snapshot()
    keep = crew_layer(W, H, *GAP, ramped=1.0, wind_from=snap.wind.from_deg)
    keep.fade_at = fade_at
    return snap, TiredCrew("c1", *GAP, snap, keep, relief_at=15, relief_eta_min=15.0)


def test_relieving_a_crew_that_tires_at_the_chokepoint_is_recommended():
    """#178: the crew holding the only gap starts to tire now; a fresh crew
    15 minutes out keeps the town safer, so it's a relieve card."""
    from forecast.recommend import recommend_reliefs

    _, crew = _tired_at_gap(fade_at=0)
    [r] = recommend_reliefs([crew], [TOWN], seed=1, horizon=75)
    assert r.relieve_id == "c1" and r.benefit_lo > 0 and r.eta_min == 15.0
    assert r.act_by_min == -15.0  # it's tiring already: send relief now
    assert describe(r, 2.18, station="Station 35").startswith("Relieving this crew with a fresh one from Station 35")


def test_a_crew_that_stays_fresh_is_not_worth_relieving():
    from forecast.recommend import recommend_reliefs

    _, crew = _tired_at_gap(fade_at=500)  # fresh for the whole look-ahead
    assert recommend_reliefs([crew], [TOWN], seed=1, horizon=75) == []
