"""Future-wind scenarios for the forecast ensemble (#228)."""

import math

import numpy as np

from forecast.rollout import rollout, rollout_paired
from forecast.runner import run_forecast
from forecast.wind import WindScenarios, factors, sample_paths
from sim.fire import FireSim, Wind, advance, wind_factors

QUIET = WindScenarios(shift_rate_per_h=0.0, gust_prob=0.0)  # wander only


def _wander(paths, wind):
    return (paths.from_deg - wind.from_deg + 180.0) % 360.0 - 180.0


def test_paths_are_reproducible_and_seed_dependent():
    w = Wind(10.0, 45.0)
    a = sample_paths(w, 16, 60, WindScenarios(), np.random.default_rng(3))
    b = sample_paths(w, 16, 60, WindScenarios(), np.random.default_rng(3))
    c = sample_paths(w, 16, 60, WindScenarios(), np.random.default_rng(4))
    assert np.array_equal(a.speed_ms, b.speed_ms) and np.array_equal(a.from_deg, b.from_deg)
    assert not np.array_equal(a.from_deg, c.from_deg)
    assert a.speed_ms.shape == (60, 16) and (a.speed_ms >= 0).all()
    assert ((a.from_deg >= 0) & (a.from_deg < 360)).all()


def test_wander_is_temporally_correlated_and_grows_with_lead_time():
    w = Wind(10.0, 90.0)
    m = QUIET
    p = sample_paths(w, 4000, 240, m, np.random.default_rng(0))
    d = _wander(p, w)
    rho = math.exp(-1.0 / m.persistence_min)
    # Lag-1 correlation of the wander, late in the path where it is near stationary.
    x, y = d[150:-1].ravel(), d[151:].ravel()
    assert abs(np.corrcoef(x, y)[0, 1] - rho) < 0.01
    # Spread grows with lead time, as sd * sqrt(1 - rho^(2t)): small at first, the prior sd later.
    for t in (1, 10, 60, 239):
        want = m.dir_sd_deg * math.sqrt(1 - rho ** (2 * (t + 1)))
        assert abs(d[t].std() - want) < 0.08 * want + 0.1
    assert d[0].std() < 0.2 * m.dir_sd_deg  # the next minute looks like now
    s = np.log(p.speed_ms / w.speed_ms)
    assert abs(s[239].std() - m.speed_sd * math.sqrt(1 - rho ** 480)) < 0.02


def test_abrupt_shifts_happen_at_the_configured_rate():
    w = Wind(10.0, 0.0)
    m = WindScenarios(dir_sd_deg=0.0, speed_sd=0.0, shift_rate_per_h=0.5, gust_prob=0.0)
    p = sample_paths(w, 20000, 60, m, np.random.default_rng(1))
    turned = np.abs(_wander(p, w)[-1]) > 1.0
    assert abs(turned.mean() - (1 - math.exp(-0.5))) < 0.015  # P(at least one shift in an hour)
    size = np.abs(_wander(p, w)[-1][turned])
    assert size.min() >= 0 and size.max() <= 180.0 + 1e-3


def test_no_shift_model_keeps_the_wind_without_wander():
    w = Wind(7.0, 200.0)
    m = WindScenarios(dir_sd_deg=0.0, speed_sd=0.0, shift_rate_per_h=0.0, gust_prob=0.0)
    p = sample_paths(w, 5, 30, m, np.random.default_rng(0))
    assert np.allclose(p.speed_ms, 7.0) and np.allclose(p.from_deg, 200.0)


def test_vectorized_factors_match_wind_factors():
    v = np.array([0.0, 3.0, 10.0, 18.0])
    d = np.array([0.0, 45.0, 200.0, 359.0])
    want = np.stack([wind_factors(Wind(float(a), float(b))) for a, b in zip(v, d)], axis=1)
    assert np.allclose(factors(v, d), want, rtol=1e-6)


def _sim(seed=0, wind=Wind(12.0, 45.0)):
    from scenario import load_scenario
    from eval.run import IGNITIONS

    sim = FireSim(load_scenario("paradise"), seed=seed)
    sim.set_wind(wind)
    sim.ignite(*IGNITIONS[0], radius=2)
    for _ in range(20):
        sim.step()
    return sim


def test_per_row_ember_wind_equal_to_the_wind_reproduces_the_scalar_path():
    sim = _sim(wind=Wind(14.0, 45.0))  # above the ember threshold
    snap = sim.snapshot()
    n = 6
    outs = []
    for each in (None, (np.full(n, 14.0, np.float32), np.full(n, 45.0, np.float32))):
        st = np.repeat(snap.state[None], n, axis=0)
        bl = np.repeat(snap.burn_left[None], n, axis=0)
        rng = np.random.default_rng(5)
        for _ in range(15):
            advance(st, bl, snap.layers, snap.wind, snap.suppression, rng, wind_each=each)
        outs.append(st)
    assert np.array_equal(outs[0], outs[1])


def test_forecast_uses_the_model_and_constant_wind_is_unchanged():
    snap = _sim().snapshot()
    base = run_forecast(snap, n=8, seed=2)
    plain = rollout(snap, 8, 60, seed=2)
    assert base.wind_model is None and np.array_equal(base.first_burn, plain)  # default: constant wind
    ens = run_forecast(snap, n=8, seed=2, wind_model=WindScenarios(shift_rate_per_h=1.0))
    again = run_forecast(snap, n=8, seed=2, wind_model=WindScenarios(shift_rate_per_h=1.0))
    assert np.array_equal(ens.first_burn, again.first_burn)  # reproducible
    assert not np.array_equal(ens.first_burn, base.first_burn)
    assert ens.probability.shape == base.probability.shape and ens.wind_model is not None


def test_paired_rollouts_share_wind_paths_across_variants():
    snap = _sim().snapshot()
    zero = np.zeros_like(snap.suppression)
    first = rollout_paired(snap, 6, 30, [zero, zero], seed=1, wind_model=WindScenarios(shift_rate_per_h=1.0))
    assert np.array_equal(first[0], first[1]) and np.array_equal(first[0], first[2])


def test_forecast_sees_nothing_after_issue():
    """Two fires identical up to issue, with different winds afterwards, get
    identical forecasts: the ensemble is built from the wind at issue only."""
    a, b = _sim(seed=4), _sim(seed=4)
    snap_a, snap_b = a.snapshot(), b.snapshot()
    a.set_wind(Wind(18.0, 225.0))  # the future differs...
    for _ in range(30):
        a.step()
        b.step()
    m = WindScenarios()
    fa = run_forecast(snap_a, n=8, seed=9, wind_model=m)
    fb = run_forecast(snap_b, n=8, seed=9, wind_model=m)
    assert np.array_equal(fa.first_burn, fb.first_burn)  # ...the forecasts don't
