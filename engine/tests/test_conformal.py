"""Online conformal burn envelope (#12)."""

import numpy as np

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
        try:
            e.fire.ignite(217.3, 54.5)
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
