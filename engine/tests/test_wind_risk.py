"""Forecast-time alignment, leakage and the shift-risk model (#231). Synthetic
data only: no network."""

import numpy as np

from forecast.wind_risk import ShiftRisk, constant, fit, persistence
from weather import dataset as D
from weather.obs import from_uv, to_uv


def _series(t, speed, from_deg, window_s=600.0):
    u, v = to_uv(speed, from_deg)
    return D.Series(np.asarray(t, float), u, v, window_s)


def test_uv_round_trip_has_no_wraparound():
    s, d = from_uv(*to_uv([5.0, 5.0, 3.0], [359.0, 1.0, 180.0]))
    assert np.allclose(s, [5, 5, 3]) and np.allclose(d, [359, 1, 180])
    # 359 and 1 degrees are 2 degrees apart, not 358.
    u1, v1 = to_uv(5.0, 359.0)
    u2, v2 = to_uv(5.0, 1.0)
    assert abs(D.angle_between(u1, v1, u2, v2) - 2.0) < 1e-9


def test_wind_at_uses_only_the_past_window():
    t = np.arange(0, 3600, 60.0)
    s = _series(t, np.full(len(t), 5.0), np.where(t < 1800, 90.0, 270.0))
    u, v, n = D.wind_at(s, np.array([1799.0, 1800.0 + 540.0]))
    assert n[0] == 10 and n[1] == 10
    assert np.allclose(from_uv(u[0], v[0])[1], 90.0)  # the window (1199, 1799] is all before the change
    assert np.allclose(from_uv(u[1], v[1])[1], 270.0)


def test_features_do_not_change_when_the_future_does():
    """Onboard features at t depend only on observations up to t; changing
    everything after t leaves them, and the forecast features, unchanged."""
    t = np.arange(0, 6 * 3600, 60.0)
    rng = np.random.default_rng(0)
    speed, dirs = 4 + 3 * rng.random(len(t)), 360 * rng.random(len(t))
    a = _series(t, speed, dirs)
    later = t > 3 * 3600
    speed2, dirs2 = speed.copy(), dirs.copy()
    speed2[later], dirs2[later] = 15.0, 123.0
    b = _series(t, speed2, dirs2)
    issue = np.array([2 * 3600.0, 3 * 3600.0])
    fa, fb = D.onboard_features(a, issue, -120.0), D.onboard_features(b, issue, -120.0)
    for k in D.ONBOARD:
        assert np.allclose(fa[k], fb[k], equal_nan=True), k
    # Targets do look ahead, and see the change.
    ua, va, _ = D.wind_at(a, issue + 3600)
    ub, vb, _ = D.wind_at(b, issue + 3600)
    assert not np.allclose(ua, ub)


def _run(init, u, v):
    n = 48
    return {"init": np.array(init, float), "u": np.full(n, u, np.float32), "v": np.full(n, v, np.float32),
            "gust": np.full(n, 9.0, np.float32), "u_sd": np.zeros(n, np.float32), "v_sd": np.zeros(n, np.float32)}


def test_preloaded_run_respects_the_publication_delay():
    inits = np.array([0.0, 6 * 3600.0, 12 * 3600.0])
    assert D.preloaded_run(inits, 6 * 3600 + 30 * 60) == 0  # the 6 h run isn't out until 7 h
    assert D.preloaded_run(inits, 7 * 3600) == 1
    assert D.preloaded_run(inits, 0.5 * 3600) is None


def test_forecast_slots_are_forecast_hours_from_one():
    run = _run(0.0, 1.0, 0.0)
    run["u"] = np.arange(1, 49, dtype=np.float32)  # slot k holds forecast hour k + 1
    assert D.forecast_at(run, 3600.0, "u") == 1.0
    assert D.forecast_at(run, 1.5 * 3600, "u") == 1.5
    assert np.isnan(D.forecast_at(run, 0.5 * 3600, "u"))  # hour 0 isn't in a forecast store


def test_forecast_features_use_only_runs_published_before_issue():
    runs = {0.0: _run(0.0, 5.0, 0.0), 6 * 3600.0: _run(6 * 3600.0, -5.0, 0.0)}
    t = np.array([6.5 * 3600, 7.5 * 3600])
    f = D.forecast_features(runs, t, 60, np.array([5.0, 5.0]), np.array([0.0, 0.0]))
    assert f["f_init"][0] == 0.0 and f["f_init"][1] == 6 * 3600.0
    assert np.isclose(f["f_err_now"][0], 0.0) and np.isclose(f["f_err_now"][1], 10.0)
    assert np.isclose(f["f_age"][0], 6.5)


def test_targets():
    u0, v0 = to_uv(np.array([5.0, 5.0, 5.0, 1.0, 3.0]), np.array([0.0, 0.0, 0.0, 0.0, 0.0]))
    u1, v1 = to_uv(np.array([5.0, 5.0, 5.0, 5.0, 9.0]), np.array([30.0, 90.0, 200.0, 180.0, 0.0]))
    t = D.shift_targets(u0, v0, u1, v1)
    assert t["shift"].tolist() == [False, True, True, False, False]  # calm at t: no direction to shift from
    assert t["reversal"].tolist() == [False, False, True, False, False]
    assert t["surge"].tolist() == [False, False, False, False, True]


def test_logistic_fit_recovers_signal_and_round_trips(tmp_path):
    rng = np.random.default_rng(1)
    x = rng.normal(size=(4000, 3))
    p = 1 / (1 + np.exp(-(1.5 * x[:, 0] - 1.0 * x[:, 1] - 1.0)))
    y = (rng.random(4000) < p).astype(float)
    m = fit(x, y, ["a", "b", "c"], l2=0.1)
    assert m.weights[0] > 1.0 and m.weights[1] < -0.6 and abs(m.weights[2]) < 0.2
    m.save(tmp_path / "m.json")
    m2 = ShiftRisk.load(tmp_path / "m.json")
    assert np.allclose(m2.predict(x[:5]), m.predict(x[:5]))
    c = constant(y)
    assert np.allclose(c.predict(x[:3]), y.mean())
    assert (persistence().predict(x[:3]) == 0).all()


def test_fit_stays_sane_with_rare_events_and_wide_features():
    """1% events and features on very different scales (the real data's
    shape) must not make Newton diverge: the fit must beat the base rate."""
    rng = np.random.default_rng(2)
    n = 30000
    x = np.column_stack([rng.normal(0, 2, n), rng.uniform(0, 180, n), rng.uniform(0, 19, n)])
    logit = -5.0 + 0.03 * x[:, 1] + 0.1 * x[:, 2]
    y = (rng.random(n) < 1 / (1 + np.exp(-logit))).astype(float)
    m = fit(x, y, ["a", "b", "c"])
    p = m.predict(x)
    assert np.isfinite(m.bias) and abs(m.bias) < 20 and np.all(np.abs(m.weights) < 20)
    assert abs(p.mean() - y.mean()) < 0.003  # a logistic fit's mean matches the base rate
    assert np.mean((p - y) ** 2) < np.mean((y.mean() - y) ** 2)  # better than the constant rate


def test_a_longer_latency_loads_an_older_forecast():
    runs = {0.0: _run(0.0, 5.0, 0.0), 6 * 3600.0: _run(6 * 3600.0, -5.0, 0.0)}
    t = np.array([7.5 * 3600])
    fresh = D.forecast_features(runs, t, 60, np.array([5.0]), np.array([0.0]))
    stale = D.forecast_features(runs, t, 60, np.array([5.0]), np.array([0.0]), latency_h=7.0, max_age_h=19.0)
    assert fresh["f_init"][0] == 6 * 3600.0 and stale["f_init"][0] == 0.0
    assert np.isclose(fresh["f_age"][0], 1.5) and np.isclose(stale["f_age"][0], 7.5)


# --- Stage 2: conditional shift rates and the real-wind replay ---------------------------

def test_rate_per_hour_inverts_the_poisson_probability():
    from forecast.wind_risk import MAX_RATE_PER_H, rate_per_hour

    for p in (0.0, 0.05, 0.22, 0.63):
        r = rate_per_hour(p)
        assert np.isclose(1 - np.exp(-r), p)  # P(at least one shift within the hour)
    assert rate_per_hour(0.9999) == MAX_RATE_PER_H


def test_given_wind_paths_replace_sampling_and_are_shared_by_rollouts():
    from forecast.runner import run_forecast
    from forecast.wind import WindPaths, WindScenarios
    from scenario import load_scenario
    from sim.fire import FireSim, Wind

    sim = FireSim(load_scenario("paradise"), seed=0)
    sim.set_wind(Wind(12.0, 45.0))
    sim.ignite(409.3, 118.5, radius=2)
    for _ in range(10):
        sim.step()
    snap = sim.snapshot()
    turn = WindPaths(np.full((61, 1), 12.0, np.float32), np.full((61, 1), 225.0, np.float32))
    a = run_forecast(snap, n=6, seed=3, wind_paths=turn)
    b = run_forecast(snap, n=6, seed=3, wind_paths=turn, wind_model=WindScenarios(shift_rate_per_h=4.0))
    assert np.array_equal(a.first_burn, b.first_burn)  # given paths win over a sampler
    same = WindPaths(np.full((61, 1), 12.0, np.float32), np.full((61, 1), 45.0, np.float32))
    c = run_forecast(snap, n=6, seed=3, wind_paths=same)
    d = run_forecast(snap, n=6, seed=3, wind_model=None)
    assert np.array_equal(c.first_burn, d.first_burn)  # a constant given path is the constant-wind forecast
    assert not np.array_equal(a.first_burn, d.first_burn)


def test_replay_wind_holds_gaps_and_uses_observations_in_order():
    from eval.wind_replay import observed_wind

    t = np.concatenate([np.arange(0, 1200, 60.0), np.arange(3000, 4800, 60.0)])  # a 30-min gap
    s = _series(t, np.full(len(t), 6.0), np.where(t < 2000, 90.0, 270.0))
    sp, fr = observed_wind(s, 600.0, 60)
    assert np.allclose(sp, 6.0) and np.isfinite(fr).all()
    assert np.allclose(fr[:10], 90.0)  # before the gap: the old wind, then held through the gap
    assert np.allclose(fr[-5:], 270.0)


def test_replay_ignitions_are_near_the_real_origin_and_seeded():
    from eval.wind_replay import IGNITION_RADIUS, STATIONS, ignition

    scen, origin = STATIONS["BJC"]
    a, b = ignition(scen, origin, 7), ignition(scen, origin, 7)
    assert a == b and np.hypot(a[0] - origin[0], a[1] - origin[1]) <= IGNITION_RADIUS + 1
