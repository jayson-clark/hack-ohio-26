"""Paired rollouts (common random numbers) and ensemble wind spread."""

import numpy as np

from forecast import WindSpread, burn_probability, rollout, rollout_paired
from forecast.runner import run_forecast
from test_fire import H, W, snapshot_with_fire


def test_zero_effect_variants_match_the_baseline_exactly():
    snap = snapshot_with_fire()
    first = rollout_paired(snap, 6, 25, np.zeros((3, H, W), np.float32), seed=4)
    assert first.shape == (4, 6, H, W)
    for k in range(1, 4):
        assert np.array_equal(first[k], first[0])
    # And the baseline is just the ordinary forecast for that seed.
    assert np.array_equal(first[0], rollout(snap, 6, 25, seed=4))


def test_pairing_removes_noise_that_independent_runs_have():
    snap = snapshot_with_fire()
    # Suppression in a corner the fire can't reach in 20 ticks: no real effect.
    far = np.zeros((1, H, W), np.float32)
    far[0, :5, :5] = 0.9
    paired = rollout_paired(snap, 8, 20, far, seed=1)
    assert np.array_equal(paired[1], paired[0])
    # Two separate forecasts of the same "no effect" disagree on luck alone.
    a, b = rollout(snap, 8, 20, seed=1), rollout(snap, 8, 20, seed=2)
    assert not np.array_equal(a, b)


def test_paired_crew_effect_is_one_sided_where_it_matters():
    snap = snapshot_with_fire()
    wall = np.zeros((1, H, W), np.float32)
    wall[0, :, W // 2 + 12 : W // 2 + 15] = 1.0
    first = rollout_paired(snap, 8, 30, wall, seed=0)
    burned = np.isfinite(first)
    # Past the wall nothing burns with it; without it, something does.
    assert not burned[1][:, :, W // 2 + 12 :].any()
    assert burned[0][:, :, W // 2 + 12 :].any()


def test_wind_spread_is_seeded_and_keeps_pairs_aligned():
    snap = snapshot_with_fire()
    spread = WindSpread(speed_frac=0.3, dir_deg=25)
    a = rollout(snap, 8, 25, seed=5, wind_spread=spread)
    assert np.array_equal(a, rollout(snap, 8, 25, seed=5, wind_spread=spread))
    plain = rollout(snap, 8, 25, seed=5)
    assert not np.array_equal(a, plain)
    # Spread widens the forecast: more cells with a non-zero, non-certain chance.
    def uncertain(first):
        p = burn_probability(first, 25)
        return ((p > 0) & (p < 1)).sum()
    assert uncertain(a) > uncertain(plain)
    paired = rollout_paired(snap, 8, 25, np.zeros((2, H, W), np.float32), seed=5, wind_spread=spread)
    assert np.array_equal(paired[2], paired[0]) and np.array_equal(paired[0], a)


def test_run_forecast_records_its_wind_spread():
    snap = snapshot_with_fire()
    assert run_forecast(snap, n=4, seed=0).wind_spread is None
    spread = WindSpread()
    assert run_forecast(snap, n=4, seed=0, wind_spread=spread).wind_spread == spread
