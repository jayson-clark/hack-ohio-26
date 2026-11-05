"""Online conformal burn envelope (#12)."""

import numpy as np
import pytest

from uq.conformal import ALPHA, MARGIN_STEP, EnvelopeLedger, OnlineEnvelope, dilate


def test_threshold_then_margin_as_theta_falls():
    env = OnlineEnvelope(theta=0.3, lam_min=1 / 32)
    assert env.threshold == 0.3 and env.margin == 0
    env.theta = 1 / 32 - 2.5 * MARGIN_STEP  # below what a forecast can express
    assert env.threshold == 1 / 32 and env.margin == 3
    p = np.zeros((9, 9), np.float32)
    p[4, 4] = 0.5
    assert env.envelope(p).sum() == 7 * 7  # the cell plus 3 king moves


def test_misses_widen_and_clean_forecasts_tighten():
    env = OnlineEnvelope(theta=0.5, lam_min=1 / 32)
    shown = np.zeros((4, 4), bool)
    new = np.zeros((4, 4), bool)
    new[0, :2] = True
    assert env.update(shown, new) == 1.0 and env.theta < 0.5  # all missed: lower the cutoff
    t = env.theta
    assert env.update(np.ones((4, 4), bool), new) == 0.0 and env.theta > t  # none missed: tighten
    assert env.update(shown, np.zeros((4, 4), bool)) is None  # nothing burned: no information


def test_long_run_miss_reaches_target_for_an_overconfident_forecast():
    """The forecast says p but the truth burns with chance 1.8p (it ignores,
    say, a wind shift). The fixed 50% contour misses a lot; the online
    envelope learns a lower cutoff and its long-run miss lands near alpha."""
    rng = np.random.default_rng(0)
    env = OnlineEnvelope(theta=0.5, lam_min=1 / 32)
    misses, fixed = [], []
    for _ in range(600):
        p = rng.beta(0.6, 2.0, size=(32, 32)).astype(np.float32)
        burned = rng.random((32, 32)) < np.minimum(1.0, 1.8 * p)
        fixed.append(float((burned & (p < 0.5)).sum() / max(burned.sum(), 1)))
        misses.append(env.update(env.envelope(p), burned))
    assert np.mean(fixed) > 2 * ALPHA
    assert abs(np.mean(misses[200:]) - ALPHA) < 0.02


def test_ledger_scores_each_envelope_when_its_horizon_passes():
    led = EnvelopeLedger((30.0, 60.0), (0.5, 0.5), n_rollouts=32)
    h, w = 10, 10
    prob = np.zeros((2, h, w), np.float32)
    prob[:, :, :5] = 0.9  # the forecast expects the west half
    lit = np.zeros((h, w), bool)
    lit[:, 0] = True
    led.issue(0, prob, lit, ~lit)
    burned = lit.copy()
    burned[:, :8] = True  # the fire got to x = 7: x 5-7 were outside the envelope
    assert led.mature(29, burned) == []  # not yet
    [(h30, miss30)] = led.mature(30, burned)
    assert h30 == 0 and abs(miss30 - 3 / 7) < 1e-9  # 3 of the 7 newly burned columns were missed
    [(h60, miss60)] = led.mature(60, burned)
    assert h60 == 1
    assert led.envs[0].scored == 1 and led.envs[1].scored == 1 and miss60 == miss30
    led.issue(100, prob, lit, ~lit)
    led.clear_pending()
    assert led.mature(1000, burned) == []


def test_dilate():
    m = np.zeros((5, 5), bool)
    m[2, 2] = True
    assert dilate(m, 1).sum() == 9 and dilate(m, 2).sum() == 25


def test_engine_scores_envelopes_and_sends_them():
    import asyncio
    import json

    from forecast.runner import run_forecast
    from server import Engine

    async def go():
        e = Engine()
        e.emulator = None  # calibration needs only the simulator: no learned emulator (#113)
        try:
            e.fire.ignite(409.3, 118.5)  # the Camp Fire origin near Pulga, in the extended map (#197)
            for _ in range(5):
                e.step_fire()
            done = asyncio.get_running_loop().create_future()
            done.set_result(run_forecast(e.snapshot(), n=8, seed=0))
            e.forecast_done(done, e._fire_epoch)
            msg = json.loads(e.envelope_msg())
            assert msg["type"] == "forecast_envelope" and msg["horizons_min"] == [30, 60]
            assert msg["scored"] == [0, 0]
            for _ in range(61):
                e.fire.step()
                e.envelope.mature(e.fire.tick, e.fire.state >= 2)
            assert [env.scored for env in e.envelope.envs] == [1, 1]
            e.switch_scenario("marshall")  # a new map learns from its own warm start
            assert [env.scored for env in e.envelope.envs] == [0, 0]
        finally:
            e.forecaster.shutdown()
            e.recommender.shutdown()

    asyncio.run(go())


# --- Score maps, loss curves and the DtACI-inspired controller (#227) -------------------

from uq.conformal import (  # noqa: E402
    DTACI_RATES, MAX_MARGIN, DtACIEnvelope, RiskCurve, ScoreMap, envelope_scores, theta_floor,
)


def _old_envelope(p, theta, lam):
    """The envelope as it was computed before score maps: cutoff, then dilation."""
    import math
    m = 0 if theta >= lam else min(MAX_MARGIN, math.ceil((lam - theta) / MARGIN_STEP))
    s = p >= max(theta, lam)
    return dilate(s, m) if m else s


def test_score_map_envelope_matches_cutoff_plus_dilation():
    rng = np.random.default_rng(1)
    lam = 1 / 32
    p = (rng.binomial(32, rng.beta(0.3, 3.0, size=(40, 40))) / 32).astype(np.float32)
    p[:, 30:] = 0  # room for the margin rings
    sm = ScoreMap.of(p, lam)
    for theta in np.concatenate([np.linspace(theta_floor(lam) - 0.05, 1.0, 301), [lam, lam - MARGIN_STEP]]):
        assert (sm.envelope(theta) == _old_envelope(p, theta, lam)).all(), theta
    assert np.isinf(envelope_scores(np.zeros((5, 5), np.float32), lam)).all()  # nothing to grow from


def test_risk_curve_loss_and_integral_match_brute_force():
    rng = np.random.default_rng(2)
    s = np.concatenate([rng.choice([0.03, 0.1, 0.5, 0.9], 50), [-np.inf] * 5])
    v, c = np.unique(s, return_counts=True)
    curve = RiskCurve(v, c)
    lo = -0.2
    for t in (-0.1, 0.05, 0.1, 0.3, 1.0):
        assert curve.loss(t) == np.mean(s < t)
        u = np.linspace(lo, t, 20001)
        brute = np.mean([np.mean(s < x) for x in u]) * (t - lo)
        assert abs(curve.integral(t, lo) - brute) < 1e-3
    assert np.allclose(curve.loss(np.array([0.05, 0.3])), [np.mean(s < 0.05), np.mean(s < 0.3)])


def test_capped_curve_equals_recording_at_that_cap():
    rng = np.random.default_rng(3)
    lam = 1 / 32
    p = np.zeros((80, 80), np.float32)
    p[35:45, 35:45] = 0.5
    cells = rng.random((80, 80)) < 0.3
    wide = ScoreMap.of(p, lam, max_margin=40).curve(cells).capped(lam, 10)
    direct = ScoreMap.of(p, lam, max_margin=10).curve(cells)
    assert np.array_equal(wide.values, direct.values) and np.array_equal(wide.counts, direct.counts)


def _curve(scores):
    v, c = np.unique(np.asarray(scores, np.float64), return_counts=True)
    return RiskCurve(v, c)


def test_every_controller_widens_after_misses_and_tightens_after_clean_forecasts():
    lam = 1 / 32
    missed = _curve([0.01] * 9 + [0.9])  # 90% of new fire had p ~ 0.01: missed at any useful cutoff
    clean = _curve([0.9] * 10)  # all of it inside
    aci = OnlineEnvelope(lam_min=lam, theta=0.3)
    dt = DtACIEnvelope(lam_min=lam, theta0=0.3)
    for env in (aci, dt):
        before = env.theta
        experts = env.experts.copy() if env is dt else None
        env.learn(missed, env.state())
        assert env.theta < before  # wider
        if env is dt:
            assert (dt.experts < experts).all()
            assert dt.experts[-1] < dt.experts[0]  # the fastest expert moved most
        before = env.theta
        env.learn(clean, env.state())
        assert env.theta > before  # tighter


def test_dtaci_weights_move_to_the_expert_that_would_have_done_better():
    lam = 1 / 32
    dt = DtACIEnvelope(lam_min=lam, theta0=0.3)
    # Two forecasts land at once, both issued before the experts moved, so
    # each is charged with what the expert showed at issue (the same knob).
    issued = dt.state()
    dt.learn(_curve([0.01] * 9 + [0.9]), issued)
    assert np.allclose(dt.weights, 1 / len(DTACI_RATES))  # same knobs at issue: no information
    # Now the experts differ; a run of big misses favours the ones that went wider.
    for _ in range(10):
        dt.learn(_curve([0.05] * 8 + [0.9] * 2), dt.state())
    assert dt.weights[-1] > dt.weights[0]
    assert abs(dt.weights.sum() - 1) < 1e-9 and (dt.weights >= dt.sigma / len(dt.weights) - 1e-12).all()


def test_dtaci_long_run_miss_reaches_target_for_an_overconfident_forecast():
    rng = np.random.default_rng(0)
    env = DtACIEnvelope(lam_min=1 / 32, theta0=0.5)
    misses = []
    for _ in range(600):
        p = rng.beta(0.6, 2.0, size=(32, 32)).astype(np.float32)
        burned = rng.random((32, 32)) < np.minimum(1.0, 1.8 * p)
        sm = ScoreMap.of(p, env.lam_min)
        misses.append(env.learn(sm.curve(burned), env.state()))
    assert abs(np.mean(misses[200:]) - ALPHA) < 0.02


def test_widest_envelope_failing_is_reported_and_the_knob_stays_clipped():
    lam = 1 / 32
    for env in (OnlineEnvelope(lam_min=lam, theta=0.2), DtACIEnvelope(lam_min=lam, theta0=0.2)):
        far = _curve([-np.inf] * 5 + [0.5] * 5)  # half the new fire beyond any margin
        for _ in range(120):
            env.learn(far, env.state())
        assert env.infeasible == 120
        assert env.theta >= env.floor and env.margin == MAX_MARGIN and env.threshold == lam  # widest, not past it
        assert env.saturated > 0


@pytest.mark.parametrize("method", ["aci", "dtaci"])
def test_ledger_skips_forecasts_with_nothing_new_burning(method):
    led = EnvelopeLedger((30.0,), (0.5,), n_rollouts=32, method=method)
    prob = np.zeros((1, 6, 6), np.float32)
    lit = np.zeros((6, 6), bool)
    lit[0, 0] = True
    led.issue(0, prob, lit, ~lit)
    theta = led.envs[0].theta
    assert led.mature(30, lit) == []
    assert led.envs[0].empty == 1 and led.envs[0].scored == 0 and led.envs[0].theta == theta


@pytest.mark.parametrize("method", ["aci", "dtaci"])
def test_ledger_scores_late_forecasts_at_their_own_horizon_in_order(method):
    led = EnvelopeLedger((30.0, 60.0), (0.5, 0.5), n_rollouts=32, method=method, record=True)
    h, w = 10, 10
    prob = np.zeros((2, h, w), np.float32)
    prob[:, :, :5] = 0.9
    lit = np.zeros((h, w), bool)
    lit[:, 0] = True
    led.issue(0, prob, lit, ~lit)
    led.issue(10, prob, lit, ~lit)
    burn = np.full((h, w), np.inf, np.float32)
    burn[:, 0] = 0
    burn[:, 1:5] = 20  # inside the envelope, by tick 20
    burn[:, 5:9] = 35  # outside it, after the first T+30 horizon
    now = np.isfinite(burn)
    # Scored late (tick 100), but each forecast only on what burned by its horizon.
    out = led.mature(100, now, burn)
    assert [(s.horizon, s.issue_tick) for s in led.log] == [(0, 0), (0, 10), (1, 0), (1, 10)]
    assert out[0] == (0, 0.0)  # T+30 from tick 0: only the inside columns had burned by tick 30
    assert abs(out[1][1] - 4 / 8) < 1e-9  # T+30 from tick 10 (horizon 40): 4 of 8 new columns missed
    # Without burn ticks the tick-0 forecast would be charged for the later burning too.
    led2 = EnvelopeLedger((30.0,), (0.5,), n_rollouts=32, method=method)
    led2.issue(0, prob[:1], lit, ~lit)
    assert led2.mature(100, now)[0][1] > 0


def test_ledger_dtaci_charges_each_expert_with_its_knobs_at_issue():
    led = EnvelopeLedger((30.0,), (0.3,), n_rollouts=32, method="dtaci")
    env = led.envs[0]
    env.experts = np.linspace(0.05, 0.5, len(env.rates))  # experts disagree at issue
    h, w = 8, 8
    prob = np.zeros((1, h, w), np.float32)
    prob[0, :, :4] = 0.4
    prob[0, :, 4:] = 0.1
    lit = np.zeros((h, w), bool)
    lit[:, 0] = True
    led.issue(0, prob, lit, ~lit)
    env.experts = np.full(len(env.rates), 0.5)  # moved since: must not matter for this forecast
    led.mature(30, np.ones((h, w), bool))  # everything burned, half of it at p = 0.1
    # Experts at issue below 0.1 caught it all; those above missed half: weight moves to the low ones.
    assert env.weights[0] > env.weights[-1]


def test_compare_replay_matches_the_live_ledger():
    """eval.conformal_compare replays recorded forecasts; it must give the
    same misses as running the ledger live on the same fire."""
    from eval import conformal_compare as cc
    from eval.run import IGNITIONS
    from forecast.runner import HORIZONS_MIN, horizon_ticks, run_forecast
    from scenario import load_scenario
    from sim.fire import BURNING, FUEL, FireSim

    ticks, every, n, seed = 40, 5, 8, 1
    ep = cc.record("reversal", seed, ticks, every, n)
    for method in ("aci", "dtaci"):
        scen = load_scenario("paradise")
        wind, _ = cc.schedule("reversal", seed)
        sim = FireSim(scen, seed=seed)
        sim.set_wind(wind(0))
        sim.ignite(*IGNITIONS[seed % len(IGNITIONS)], radius=2)
        led = EnvelopeLedger(tuple(horizon_ticks(m) for m in HORIZONS_MIN), cc.WARM, n, method=method)
        burn = np.full(sim.state.shape, np.inf, np.float32)
        burn[sim.state >= BURNING] = 0
        live = [[], []]
        for tick in range(ticks + 61):
            if tick <= ticks and tick % every == 0 and (sim.state == BURNING).any():
                f = run_forecast(sim.snapshot(), n=n, seed=seed * 1000 + tick)
                led.issue(tick, f.probability, sim.state >= BURNING, sim.state == FUEL)
            sim.set_wind(wind(tick))
            sim.step()
            burn[(sim.state >= BURNING) & np.isinf(burn)] = sim.tick
            for hi, miss in led.mature(sim.tick, sim.state >= BURNING, burn):
                live[hi].append(miss)
        replayed = cc.replay(ep, method, n=n)
        for hi in range(2):
            assert np.allclose(live[hi], [s.miss for s in replayed[hi]])
            assert len(live[hi]) > 3


# --- Time-to-impact intervals (#13) ---------------------------------------------------

from uq.conformal import ArrivalCalibrator, OnlineQuantile, arrival_quantiles, bucket_of  # noqa: E402


def test_online_quantile_settles_at_alpha_misses():
    rng = np.random.default_rng(0)
    q = OnlineQuantile()
    scores = rng.exponential(20.0, size=5000) - 10.0  # minutes outside the raw range
    misses = []
    for s in scores:
        misses.append(s > q.q)
        q.update(float(s))
    assert abs(np.mean(misses[1000:]) - ALPHA) < 0.02
    assert abs(q.q - np.quantile(scores, 1 - ALPHA)) < 8.0


def test_arrival_calibrator_scores_cells_as_they_burn_or_run_out():
    cal = ArrivalCalibrator(cell_m=94.0, unit_radius=0.0)  # radius 0: each unit is one cell
    n, h, w = 20, 4, 4
    fb = np.full((n, h, w), np.inf, np.float32)
    fb[:, 0, :] = np.linspace(10, 20, n)[:, None]  # row 0: predicted 10-20 ticks out
    unburned = np.ones((h, w), bool)
    cal.issue(0, fb, unburned, 1.0, horizon_ticks=100)
    burn = np.full((h, w), np.inf, np.float32)
    burn[0, 0] = 30  # 10 ticks after the range: a miss
    burn[0, 1] = 15  # inside
    assert cal.mature(30, burn, 1.0) == 2
    b = cal.buckets[bucket_of(15.0)]
    assert b.scored == 2 and b.misses == 1
    # The other two row-0 cells never burn: scored once the forecast runs out.
    assert cal.mature(10_000, burn, 1.0) == 2 and cal.censored == 2


def test_calibrated_interval_widens_after_misses():
    cal = ArrivalCalibrator(cell_m=94.0)
    for _ in range(40):
        cal.buckets[0].update(15.0)  # always 15 min outside
    lo, hi = cal.interval(10.0, 15.0, 20.0)
    assert lo < 10.0 and hi > 20.0
    assert arrival_quantiles(np.array([1.0, 2.0, 3.0, np.inf]))[2] == np.inf


def test_town_board_carries_calibrated_eta_once_a_long_forecast_lands():
    import asyncio

    from forecast.rollout import rollout
    from forecast.runner import LongForecast
    from server import Engine

    async def go():
        e = Engine()
        e.emulator = None  # calibration needs only the simulator: no learned emulator (#113)
        try:
            e.fire.ignite(409.3, 118.5)  # the Camp Fire origin near Pulga, in the extended map (#197)
            for _ in range(10):
                e.step_fire()
            assert all(t.eta_lo_min is None for t in e.tools.town_threats())
            snap = e.snapshot()
            e.long_forecast = LongForecast(tick=snap.tick, horizon_min=240, first_burn=rollout(snap, 16, 240, seed=0))
            threats = {t.town: t for t in e.tools.town_threats()}
            pulga = threats["Pulga"]  # next to the Camp Fire origin
            assert pulga.eta_lo_min is not None and pulga.eta_lo_min >= 0
            assert pulga.eta_hi_min is None or pulga.eta_hi_min >= pulga.eta_lo_min
            row = next(r for r in e.tools._town_table() if r["town"] == "Pulga")
            assert "fire_arrival_90pct_range_minutes" in row
        finally:
            e.forecaster.shutdown()
            e.recommender.shutdown()

    asyncio.run(go())


def test_town_sized_units_score_first_fire_anywhere_inside():
    """A disk's arrival is its earliest cell, like a town's."""
    cal = ArrivalCalibrator(cell_m=94.0, unit_radius=1.0)
    n, h, w = 10, 5, 5
    fb = np.full((n, h, w), 50.0, np.float32)
    fb[:, 2, 3] = 10.0  # one cell of the centre disk burns early
    cal._rng = np.random.default_rng(0)
    cal.issue(0, fb, np.ones((h, w), bool), 1.0, horizon_ticks=100)
    units = cal._pending[0].units
    lo = cal._pending[0].lo
    for u, low in zip(units, lo):
        assert low == fb[0].ravel()[u].min()
