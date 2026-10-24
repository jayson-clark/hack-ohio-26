"""Forecasts follow suppression over time (#56): crews dig in, drops dry out."""

import numpy as np
import pytest

from forecast import burn_probability, rollout, rollout_paired
from protocol import Token, TokenSource, TokenType
from sim.effects import CREW_MAX, TokenEffects, crew_layer
from test_fire import H, W, snapshot_with_fire


def tok(i, tt, x, y, a=0.0):
    return Token(id=i, token_type=tt, x=x, y=y, angle=a, source=TokenSource.VIRTUAL)


def test_schedule_now_is_the_live_suppression_and_tracks_the_future():
    fx, live = TokenEffects(W, H), TokenEffects(W, H)
    toks = [tok("c1", TokenType.CREW, 20, 20), tok("w1", TokenType.WATER, 60, 40), tok("f", TokenType.FIREBREAK, 40, 30, 0.5)]
    for t in range(3):
        fx.update(toks, t)
        live.update(toks, t)
    sched = fx.schedule(toks, 3)
    for k in range(40):  # the schedule predicts the live grid exactly while tokens stay put
        assert np.array_equal(sched.at(k), live.update(toks, 3 + k)), k
    assert np.array_equal(fx.update(toks, 3), sched.at(0))  # and building it changed no state


def test_schedule_knows_what_changes():
    fx = TokenEffects(W, H)
    crew = [tok("c1", TokenType.CREW, 20, 20)]
    assert fx.schedule(crew, 0).varies  # a fresh crew is still digging in
    fx.update(crew, 0)
    assert fx.schedule(crew, 100).at(5).max() == pytest.approx(CREW_MAX)
    assert not fx.schedule([tok("f", TokenType.FIREBREAK, 40, 30)], 0).varies


def wall_snapshot(with_schedule: bool):
    """Fire running east into a crew placed this very tick, just ahead of it."""
    snap = snapshot_with_fire()
    fx = TokenEffects(W, H)
    crew = [tok("c1", TokenType.CREW, W // 2 + 16, H // 2)]
    sched = fx.schedule(crew, snap.tick)
    import dataclasses

    return dataclasses.replace(snap, suppression=fx.update(crew, snap.tick),
                               schedule=sched if with_schedule else None)


def test_forecast_credits_a_crew_that_is_still_digging_in():
    frozen = burn_probability(rollout(wall_snapshot(False), 16, 40, seed=0), 40)
    ramped = burn_probability(rollout(wall_snapshot(True), 16, 40, seed=0), 40)
    # Frozen at the crew's first-tick strength (zero), the forecast ignores it;
    # following its ramp-up, the ground it holds burns far less.
    ahead = (slice(H // 2 - 6, H // 2 + 7), slice(W // 2 + 12, W // 2 + 21))
    assert ramped[ahead].mean() < 0.6 * frozen[ahead].mean()


def test_a_crew_arriving_after_the_horizon_changes_nothing():
    snap = snapshot_with_fire()
    late = crew_layer(W, H, W / 2 + 10, H / 2, t_on=999)
    soon = crew_layer(W, H, W / 2 + 10, H / 2, t_on=0)
    first = rollout_paired(snap, 6, 30, [late, soon], seed=2)
    assert np.array_equal(first[1], first[0])  # identical draws, no effect
    assert np.isfinite(first[2]).sum() < np.isfinite(first[0]).sum()


def test_static_variants_still_work_and_match_layers_at_full_strength():
    snap = snapshot_with_fire()
    full = crew_layer(W, H, W / 2 + 10, H / 2, ramped=1.0)
    grid = (full.footprint * CREW_MAX).astype(np.float32)
    a = rollout_paired(snap, 6, 30, [full], seed=4)
    b = rollout_paired(snap, 6, 30, grid[None], seed=4)
    assert np.array_equal(a, b)


def test_engine_snapshot_carries_the_schedule_through_the_worker():
    import asyncio
    import pickle

    from protocol import VirtualTokenAdd
    from server import Engine

    async def go():
        e = Engine()
        try:
            e.fire.ignite(217.3, 54.5)
            e.virtual.handle(VirtualTokenAdd(token_type=TokenType.CREW, x=200, y=70))
            snap = e.snapshot()
            assert snap.schedule is not None and snap.schedule.varies  # the crew is digging in
            again = pickle.loads(pickle.dumps(snap))  # what the forecaster process receives
            assert np.array_equal(again.schedule.at(10), snap.schedule.at(10))
            f = await e.forecaster.submit(snap)
            assert f.first_burn.shape[1:] == snap.state.shape
        finally:
            e.forecaster.shutdown()
            e.recommender.shutdown()

    asyncio.run(go())
