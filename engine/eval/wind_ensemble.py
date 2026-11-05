"""Constant-wind forecast against the wind-scenario ensemble (#228).

    cd engine && uv run python -m eval.wind_ensemble --phase tune  --cache /tmp/wind_tune.pkl
    cd engine && uv run python -m eval.wind_ensemble --phase final --cache /tmp/wind_final.pkl --out ../docs/wind_ensemble.md

Same fires as eval.conformal_compare (Paradise, 32 rollouts, a forecast every
5 min for 300 min, six wind schedules including a gradual veer). At every
issue, each forecaster forecasts from the *same* snapshot: the fire and the
wind at that moment, nothing later. The truth (the live fire) is the same for
all of them, and so are the rollout seeds. The recorded loss curves are then
replayed through the conformal controllers ("static" warm start, "aci" the
engine's, optionally "dtaci"), exactly as in eval.conformal_compare.

Protocol, fixed before running:
- phase "tune": seeds 0-3. Constant wind and four ensemble settings that
  differ only in how often abrupt shifts happen (0, 0.25, 0.5, 1 per hour;
  the slow wander and gusts are the same prior in all of them).
- Selection rule: the setting that needs the least envelope area to reach a
  pooled 10% miss at a fixed cutoff ("equal-risk area", below), averaged
  over T+30 and T+60, relative to constant wind. Ties go to lower pre-shift miss.
- phase "final": seeds 4-11, constant wind against the selected setting only
  (forecast.wind.WindScenarios defaults). Nothing is tuned on these seeds.

Metrics (per forecaster, horizon; all schedules pooled unless named):
  equal-risk   the cutoff theta at which the pooled mean miss is 10%, with no
               controller, and the mean envelope area there: which forecast
               ranks cells better, at the same average risk
  pre-shift    mean miss of forecasts issued in the h minutes before an abrupt
               shift (reversal, surge, flipflop), the ones that failed before
  aci rows     eval.conformal_compare's metrics under the engine's controller
  runtime      wall time per forecast, single process

--emulators (phase final, needs the ml extra and both weights files) adds the
original and the wind-aware U-Net emulators as forecasters on the same fires
(#229), recorded in this process since MLX runs on the GPU. The wind-aware one
is given the selected wind setting as its uncertainty input. Each forecaster
gets its own conformal controller state from the same warm start; nothing
calibrated on Monte Carlo is reused. Probabilities are rounded to 1/256.
"""

import argparse
import json
import pickle
import time
from concurrent.futures import ProcessPoolExecutor

import numpy as np

from eval import conformal_compare as cc
from forecast.runner import HORIZONS_MIN, N_ROLLOUTS, horizon_ticks
from forecast.wind import WindScenarios
from uq.conformal import ALPHA, theta_floor

SCHEDULES = ("steady", "veer", "reversal", "surge", "flipflop", "gusty")
ABRUPT = ("reversal", "surge", "flipflop")  # schedules whose shifts are scored as "pre-shift"
TUNE = {
    "constant": {},
    "wander only": {"wind_model": WindScenarios(shift_rate_per_h=0.0)},
    "shifts 0.25/h": {"wind_model": WindScenarios(shift_rate_per_h=0.25)},
    "shifts 0.5/h": {"wind_model": WindScenarios(shift_rate_per_h=0.5)},
    "shifts 1/h": {"wind_model": WindScenarios(shift_rate_per_h=1.0)},
}
FINAL = {"constant": {}, "ensemble": {"wind_model": WindScenarios()}}
# --explore: the 1/h shift rate, looked at only after the held-out result for
# the selected 0.25/h setting was known. Exploratory, not a validated choice:
# it was not selected by the tuning rule, and these are the same seeds 4-11.
EXPLORE_RATE = 1.0
EXPLORE = {"ensemble 1/h (exploratory)": {"wind_model": WindScenarios(shift_rate_per_h=EXPLORE_RATE)}}
PHASES = {"tune": (TUNE, range(0, 4)), "final": (FINAL, range(4, 12))}
THETAS = np.linspace(-0.2, 1.0, 1201)


def emulator_forecasters(explore: bool = False) -> dict:
    """The emulators as eval forecasters (snapshot -> rounded probability).
    The wind-aware one is told the wind setting it stands in for."""
    from emulator.model import WEIGHTS, WIND_WEIGHTS, Emulator

    spec = [("U-Net original", WEIGHTS, None), ("U-Net wind-aware", WIND_WEIGHTS, WindScenarios())]
    if explore:
        spec.append(("U-Net wind-aware 1/h (exploratory)", WIND_WEIGHTS, WindScenarios(shift_rate_per_h=EXPLORE_RATE)))
    out = {}
    for name, path, wm in spec:
        emu = Emulator(path, wind_model=wm)
        out[name] = lambda snap, emu=emu: np.round(emu.forecast(snap) * 256) / 256
    return out


def _job(args):
    sched, seed, ticks, every, n, forecasters = args
    t0 = time.perf_counter()
    eps = cc.record(sched, seed, ticks, every, n, forecasters=forecasters)
    print(f"  recorded {sched} seed {seed} ({time.perf_counter() - t0:.0f} s)", flush=True)
    return eps


def _pre_shift(ep: cc.Episode, issue: int, h: int) -> bool:
    if ep.sched not in ABRUPT:
        return False
    hz = int(np.ceil(horizon_ticks(HORIZONS_MIN[h])))
    return any(s - hz < issue < s for s in ep.shifts)


def equal_risk(eps: list[cc.Episode], h: int, n: int = N_ROLLOUTS, max_margin: int = cc.MAX_MARGIN) -> dict:
    """With no controller: the largest cutoff whose pooled mean miss is <= alpha,
    and the area, pre-shift miss and per-schedule miss there."""
    lam = 1.0 / n
    floor = theta_floor(lam, max_margin)
    recs = [(ep, r) for ep in eps for r in ep.records if r.horizon == h and r.new is not None]
    new = [r.new.capped(lam, max_margin) for _, r in recs]
    area = [r.area.capped(lam, max_margin) for _, r in recs]
    th = THETAS[THETAS >= floor]
    miss = np.array([c.loss(th) for c in new])  # (forecasts, thetas)
    ok = np.flatnonzero(miss.mean(axis=0) <= ALPHA)
    if not len(ok):
        return {"theta": None}
    j = ok.max()
    t = float(th[j])
    km2 = np.array([a.n * (1 - a.loss(t)) * ep.cell_km2 for (ep, _), a in zip(recs, area)])
    pre = np.array([_pre_shift(ep, r.issue_tick, h) for ep, r in recs])
    sched = np.array([ep.sched for ep, _ in recs])
    return {"theta": t, "miss": float(miss[:, j].mean()), "area_km2": float(km2.mean()),
            "pre_shift_miss": float(miss[pre, j].mean()) if pre.any() else None,
            "pre_shift_area_km2": float(km2[pre].mean()) if pre.any() else None,
            "by_schedule": {s: float(miss[sched == s, j].mean()) for s in dict.fromkeys(sched)}}


def controller_rows(eps: list[cc.Episode], method: str, h: int, n: int = N_ROLLOUTS) -> dict:
    runs = [cc.replay(e, method, n=n) for e in eps]
    out = {"all": cc.metrics(eps, runs, h)}
    pre = [s for e, r in zip(eps, runs) for s in r[h] if _pre_shift(e, s.issue_tick, h)]
    out["all"]["pre_shift_miss"] = float(np.mean([s.miss for s in pre])) if pre else None
    out["all"]["pre_shift_area_km2"] = float(np.mean([s.area_km2 for s in pre])) if pre else None
    for sched in dict.fromkeys(e.sched for e in eps):
        idx = [i for i, e in enumerate(eps) if e.sched == sched]
        es = [eps[i] for i in idx]
        m = cc.metrics(es, [runs[i] for i in idx], h)
        pre = [s for i in idx for s in runs[i][h] if _pre_shift(eps[i], s.issue_tick, h)]
        if pre:
            m["pre_shift_miss"] = float(np.mean([s.miss for s in pre]))
            m["pre_shift_area_km2"] = float(np.mean([s.area_km2 for s in pre]))
        out[sched] = m
    return out


def summarize(eps: list[cc.Episode], names: list[str], methods: list[str], n: int) -> dict:
    out = {"forecasters": {}}
    for name in names:
        es = [e for e in eps if e.forecaster == name]
        t = np.array([x for e in es for x in e.forecast_s])
        row = {"episodes": len(es), "forecasts": len(t), "forecast_ms_mean": float(1000 * t.mean()),
               "forecast_ms_p90": float(1000 * np.percentile(t, 90)), "horizons": {}}
        for h, m in enumerate(HORIZONS_MIN):
            row["horizons"][f"T+{m}"] = {"equal_risk": equal_risk(es, h, n),
                                         **{meth: controller_rows(es, meth, h, n) for meth in methods}}
        out["forecasters"][name] = row
    base = out["forecasters"]["constant"]["horizons"]
    score = {}
    for name in names:
        r = out["forecasters"][name]["horizons"]
        ratios = [r[k]["equal_risk"]["area_km2"] / base[k]["equal_risk"]["area_km2"] for k in r
                  if r[k]["equal_risk"].get("area_km2") and base[k]["equal_risk"].get("area_km2")]
        pre = [r[k]["equal_risk"]["pre_shift_miss"] or 0.0 for k in r]
        score[name] = (float(np.mean(ratios)) if ratios else None, float(np.mean(pre)))
    out["selection_score"] = score  # (equal-risk area vs constant, mean pre-shift miss)
    cand = {k: v for k, v in score.items() if k != "constant" and v[0] is not None}
    out["selected"] = min(cand, key=lambda k: cand[k]) if cand else None
    return out


def _f(x, pct=False, d=2):
    if x is None:
        return "–"
    return f"{100 * x:.1f}%" if pct else f"{x:.{d}f}"


def report(s: dict, phase: str, seeds: str, methods: list[str]) -> str:
    L = [f"# Wind-scenario ensemble vs constant wind (#228), phase {phase}", "",
         f"Seeds {seeds}, schedules {', '.join(SCHEDULES)}; {N_ROLLOUTS} rollouts, a forecast every 5 min for "
         f"300 min, target miss {ALPHA:.0%}. Pre-shift = issued in the h minutes before an abrupt shift "
         f"({', '.join(ABRUPT)}).", ""]
    fs = s["forecasters"]
    L += ["## Equal risk, no controller: area needed for a pooled 10% miss", "",
          "| forecaster | horizon | cutoff θ | pooled miss | area km² | pre-shift miss | pre-shift area km² | "
          + " | ".join(f"{x} miss" for x in SCHEDULES) + " |",
          "|---|---|---|---|---|---|---|" + "---|" * len(SCHEDULES)]
    for name, r in fs.items():
        for hk, hr in r["horizons"].items():
            e = hr["equal_risk"]
            L.append(f"| {name} | {hk} | {_f(e.get('theta'), d=3)} | {_f(e.get('miss'), True)} | "
                     f"{_f(e.get('area_km2'))} | {_f(e.get('pre_shift_miss'), True)} | {_f(e.get('pre_shift_area_km2'))} | "
                     + " | ".join(_f(e.get('by_schedule', {}).get(x), True) for x in SCHEDULES) + " |")
    for meth in methods:
        L += ["", f"## Under the {meth} controller", "",
              "| forecaster | horizon | schedule | miss | worst 30 min | area km² | vs oracle | pre-shift miss | "
              "pre-shift area km² | recovery (shown) | post-shift miss | at widest | infeasible |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for hk in ("T+30", "T+60"):
            for sched in ("all",) + SCHEDULES:
                for name, r in fs.items():
                    m = r["horizons"][hk][meth].get(sched)
                    if not m:
                        continue
                    L.append(f"| {name} | {hk} | {sched} | {_f(m.get('miss'), True)} | {_f(m.get('worst30'), True)} | "
                             f"{_f(m.get('area_km2'))} | {_f(m.get('vs_oracle'))}× | {_f(m.get('pre_shift_miss'), True)} | "
                             f"{_f(m.get('pre_shift_area_km2'))} | {_f(m.get('recovery_shown_min'), d=0)} | "
                             f"{_f(m.get('post_miss'), True)} | {_f(m.get('sat'), True)} | {_f(m.get('infeasible'), True)} |")
    L += ["", "## Runtime (wall time per forecast in one worker; Monte Carlo on the CPU with the other workers "
          "busy, emulators in the main process on the GPU, so compare across machines with care)", "",
          "| forecaster | forecasts | mean ms | p90 ms |", "|---|---|---|---|"]
    for name, r in fs.items():
        L.append(f"| {name} | {r['forecasts']} | {r['forecast_ms_mean']:.0f} | {r['forecast_ms_p90']:.0f} |")
    L += ["", "## Selection score (equal-risk area vs constant, averaged over horizons; mean pre-shift miss)", ""]
    for name, (a, p) in s["selection_score"].items():
        L.append(f"- {name}: area {_f(a)}×, pre-shift miss {_f(p, True)}")
    L.append(f"\nSelected: **{s['selected']}**" if phase == "tune" else "")
    return "\n".join(L) + "\n"


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--phase", choices=PHASES, default="final")
    p.add_argument("--ticks", type=int, default=300)
    p.add_argument("--every", type=int, default=5)
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--dtaci", action="store_true", help="also replay the DtACI-inspired controller")
    p.add_argument("--emulators", action="store_true", help="also the original and wind-aware U-Nets (#229)")
    p.add_argument("--emulators-only", action="store_true",
                   help="record no Monte Carlo forecasters (they run elsewhere); report only what the cache has")
    p.add_argument("--explore", action="store_true",
                   help="phase final: also the 1/h shift rate, exploratory (chosen after seeing held-out results)")
    p.add_argument("--cache", help="pickle of recorded episodes for this phase: reused if present")
    p.add_argument("--out")
    p.add_argument("--json")
    args = p.parse_args()
    forecasters, seeds = PHASES[args.phase]
    if args.explore:
        forecasters = forecasters | EXPLORE
    eps: list[cc.Episode] = []
    if args.cache:
        try:
            with open(args.cache, "rb") as f:
                eps = pickle.load(f)
            print(f"loaded {len(eps)} episodes from {args.cache}")
        except FileNotFoundError:
            pass

    def save():
        if args.cache:
            with open(args.cache, "wb") as f:
                pickle.dump(eps, f)

    # Record only the forecasters the cache lacks; every one sees the same seeded fires.
    have = {e.forecaster for e in eps}
    missing = {k: v for k, v in forecasters.items() if k not in have}
    if args.emulators_only:
        forecasters = {k: v for k, v in forecasters.items() if k in have}
        missing = {}
    if missing:
        jobs = [(s, seed, args.ticks, args.every, N_ROLLOUTS, missing) for s in SCHEDULES for seed in seeds]
        print(f"recording {len(jobs)} fires x {len(missing)} forecasters on {args.workers} workers", flush=True)
        with ProcessPoolExecutor(args.workers) as pool:
            eps += [e for group in pool.map(_job, jobs) for e in group]
        save()
    names = list(forecasters)
    if args.emulators:
        emus = emulator_forecasters(args.explore)
        names += list(emus)
        todo = {k: v for k, v in emus.items() if k not in have}
        if todo:
            print(f"recording {len(SCHEDULES) * len(seeds)} fires x {len(todo)} emulators in this process", flush=True)
            for sched in SCHEDULES:
                for seed in seeds:
                    t0 = time.perf_counter()
                    eps += cc.record(sched, seed, args.ticks, args.every, N_ROLLOUTS, forecasters=todo)
                    print(f"  recorded {sched} seed {seed} ({time.perf_counter() - t0:.0f} s)", flush=True)
            save()
    methods = ["static", "aci"] + (["dtaci"] if args.dtaci else [])
    summary = summarize(eps, names, methods, N_ROLLOUTS)
    text = report(summary, args.phase, f"{seeds.start}-{seeds.stop - 1}", methods)
    if args.json:
        with open(args.json, "w") as f:
            json.dump(summary, f, indent=2)
    if args.out:
        with open(args.out, "w") as f:
            f.write(text)
    print(text)


if __name__ == "__main__":
    main()
