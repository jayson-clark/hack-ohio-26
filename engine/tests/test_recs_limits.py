"""Recommendations respect the round's crew limit (#77)."""

import asyncio
import dataclasses
import math

import numpy as np

from forecast.recommend import PlacedCrew, Rec, TownEffect, describe, recommend_moves
from forecast.runner import run_forecast
from protocol import AcceptRecommendation, Recommendation, Token, TokenSource, TokenType, VirtualTokenAdd
from server import Engine
from sim.effects import TokenEffects, crew_footprint
from test_fire import H, W
from test_recommend import GAP, TOWN, chokepoint_snapshot


def test_preview_leaves_ramp_up_alone():
    fx = TokenEffects(W, H)
    crew = Token(id="c1", token_type=TokenType.CREW, x=20, y=20, angle=0, source=TokenSource.VIRTUAL)
    fx.update([crew], tick=0)
    without = fx.preview([], tick=10)
    assert without.max() == 0
    # The crew kept its start tick: at tick 10 it's halfway through its 20-tick ramp, not starting over.
    assert math.isclose(fx.update([crew], tick=10).max(), 0.45, abs_tol=1e-6)


def test_wasted_crew_is_told_to_move_to_the_gap():
    snap = chokepoint_snapshot()
    p30 = run_forecast(snap, n=16, seed=0).probability[0]
    corner = crew_footprint(W, H, 5.5, 5.5)  # a crew dug in far from the fire
    current = np.maximum(snap.suppression, corner)
    crew = PlacedCrew("v1", 5.5, 5.5, without=snap)
    moves = recommend_moves([crew], current, p30, [TOWN], n=12, seed=3)
    assert moves and moves[0].move_id == "v1" and (moves[0].from_x, moves[0].from_y) == (5.5, 5.5)
    assert math.hypot(moves[0].x - GAP[0], moves[0].y - GAP[1]) < 8 and moves[0].benefit > 0


def test_describe_a_move():
    r = Rec(1, 2, 50.0, 20.0, saves=[TownEffect("Concow", 5, 8)], move_id="v2")
    assert describe(r, 2.18, "near Pulga") == "Moving the crew near Pulga here keeps the fire out of Concow in 5 of 8 simulations."


def engine_in_round(crews: int, source=TokenSource.VIRTUAL) -> Engine:
    e = Engine()
    e.game.start(e.fire.tick)
    for i in range(crews):
        if source == TokenSource.VIRTUAL:
            e.virtual.handle(VirtualTokenAdd(token_type=TokenType.CREW, x=40 + 15 * i, y=40))
        else:
            e.tracker.update(TokenSource.VISION, [
                Token(id=f"p{j}", token_type=TokenType.CREW, x=40 + 15 * j, y=40, angle=0, source=source)
                for j in range(crews)
            ])
    e.game.active(e.tracker.tokens)
    return e


def shut(e):
    e.forecaster.shutdown()
    e.recommender.shutdown()


def test_crews_left_counts_down_only_in_a_round():
    e = Engine()
    try:
        assert e.crews_left() is None  # sandbox: no limit
    finally:
        shut(e)
    e = engine_in_round(3)
    try:
        assert e.crews_left() == 0
    finally:
        shut(e)


def test_no_crews_left_asks_for_moves(monkeypatch):
    e = engine_in_round(3)
    calls = []
    try:
        monkeypatch.setattr(e.recommender, "submit_moves", lambda *a, **k: calls.append(a) or asyncio.Future())
        monkeypatch.setattr(e.recommender, "submit", lambda *a, **k: (_ for _ in ()).throw(AssertionError("place")))
        e.fire.ignite(217.3, 54.5)
        active = e.game.active(e.tracker.tokens)
        for _ in range(25):  # let the crews dig in, as the engine's tick loop does
            e.fire.set_suppression(e.effects.update(active, e.fire.tick))
            e.fire.step()
        e.latest_forecast = run_forecast(e.fire.snapshot(), n=4, seed=0)

        async def go():
            e.maybe_recommend()

        asyncio.run(go())
        [(crews, current, *_)] = calls
        assert [c.id for c in crews] == ["v1", "v2", "v3"]
        assert current.max() > 0
        for c in crews:  # each "without" snapshot is missing exactly that crew's footprint
            assert c.without.suppression[int(c.y), int(c.x)] == 0 and current[int(c.y), int(c.x)] > 0
    finally:
        shut(e)


def rec(action, move_token=None, auto=True):
    return Recommendation(id="r1", token_type=TokenType.CREW, action=action, x=120.5, y=80.5, move_token=move_token,
                          from_x=40.0 if move_token else None, from_y=40.0 if move_token else None, auto=auto,
                          benefit=3.0, acres_saved=1.0, saves=[], worsens=[], protects=[], text="")


def test_accepting_a_move_moves_the_virtual_crew():
    e = engine_in_round(3)
    try:
        e.recs = [rec("move", "v1")]
        e.dispatch(AcceptRecommendation(id="r1"))
        moved = next(t for t in e.tracker.tokens if t.id == "v1")
        assert (moved.x, moved.y) == (120.5, 80.5) and len(e.tracker.tokens) == 3
    finally:
        shut(e)


def test_physical_crew_moves_are_advice_only():
    e = engine_in_round(3, source=TokenSource.VISION)
    try:
        r = e.rec_message(Rec(120.5, 80.5, 3.0, 1.0, move_id="p0", from_x=40.0, from_y=40.0), "r1", 2.18)
        assert r.action == "move" and r.auto is False
        e.recs = [r]
        e.dispatch(AcceptRecommendation(id="r1"))
        assert [(t.x, t.y) for t in e.tracker.tokens if t.id == "p0"] == [(40, 40)]
    finally:
        shut(e)


def test_stale_place_card_is_refused_when_no_crews_are_left():
    e = engine_in_round(3)
    try:
        e.recs = [rec("place")]
        e.dispatch(AcceptRecommendation(id="r1"))
        assert len(e.tracker.tokens) == 3 and e.recs == []
    finally:
        shut(e)


def test_moves_are_distinct_crews_and_spots():
    snap = chokepoint_snapshot()
    p30 = run_forecast(snap, n=16, seed=0).probability[0]
    a, b = crew_footprint(W, H, 5.5, 5.5), crew_footprint(W, H, 5.5, 58.5)
    current = np.maximum(snap.suppression, np.maximum(a, b))
    crews = [PlacedCrew("v1", 5.5, 5.5, without=dataclasses.replace(snap, suppression=b)),
             PlacedCrew("v2", 5.5, 58.5, without=dataclasses.replace(snap, suppression=a))]
    moves = recommend_moves(crews, current, p30, [TOWN], n=8, seed=1)
    assert len({m.move_id for m in moves}) == len(moves)
    for i, m in enumerate(moves):
        for o in moves[i + 1:]:
            assert math.hypot(m.x - o.x, m.y - o.y) >= 12
