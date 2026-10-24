"""The headless evaluation harness (#14): small, fast runs that exercise every part."""

import numpy as np

from eval.run import Arrival, Results, _score_arrivals, markdown, run_episode, schedule, summarize
from forecast.recommend import TownInfo
from forecast.runner import Forecast
from routing.roads import load_network
from scenario import load_scenario


def test_schedules():
    assert schedule("steady", 0)(100).from_deg == 45
    shift = schedule("shift", 0)
    assert shift(59).from_deg == 45 and shift(60).from_deg == 270
    gusty = schedule("gusty", 3)
    assert gusty(0) == schedule("gusty", 3)(0)  # seeded
    assert gusty(0) != gusty(15) or gusty(15) != gusty(30)


def test_arrival_ranges_handle_rollouts_that_never_burn():
    # Interpolating quantiles between inf values gives NaN, which silently
    # counted as "not covered". Order statistics keep inf.
    h, w = 4, 4
    fb = np.full((16, h, w), np.inf, np.float32)
    fb[:, 0, 0] = np.arange(16) + 1.0  # every rollout burns (0, 0) at 1..16
    fb[:12, 0, 1] = 5.0  # (0, 1) burns at 5 in 12 rollouts, never in 4
    f = Forecast(tick=0, horizons_ticks=(30.0, 60.0), first_burn=fb, probability=np.zeros((2, h, w), np.float32))
    live = np.full((h, w), np.inf, np.float32)
    live[0, 0], live[0, 1] = 8.0, 40.0
    acc = Arrival()
    _score_arrivals(f, live, np.ones((h, w), bool), issue=0, acc=acc)
    assert acc.total.sum() == 2 and acc.covered.sum() == 2
    assert all(np.isfinite(s).all() for s in acc.scores)


def test_small_episodes_fill_every_section():
    s = load_scenario("paradise")
    net = load_network(s.dir, s.width, s.height)
    towns = [TownInfo(t.name, t.x, t.y, t.radius, t.population) for t in net.towns]
    res = Results()
    for ep in (0, 3):  # Camp Fire origin, and the ignition between Magalia and Paradise
        run_episode(s, net, towns, "shift", ep, ticks=40, every=10, n=4, res=res, rec_every=2)
    summary = summarize({"shift": res})["shift"]
    assert summary["episodes"] == 2
    t30 = summary["calibration"]["T+30"]
    assert t30["cells"] > 0 and 0 <= t30["brier"] < 1 and t30["reliability"]
    assert any(a["cells"] for a in summary["arrival"].values())
    assert sum(v["routes"] for v in summary["routing"]["predicted_vs_cut"].values()) > 0
    assert summary["recommendations"]["asked"] > 0
    args = type("A", (), {"episodes": 2, "ticks": 40, "every": 10, "rollouts": 4})
    report = markdown({"shift": summary}, args)
    assert "## shift wind" in report and "Forecast calibration" in report
