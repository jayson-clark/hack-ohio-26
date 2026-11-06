"""Forecast-conditioned wind uncertainty, tested on fires driven by real
observed winds (#231, stage 2).

    cd engine && uv run python -m eval.wind_replay --fit-models          # once: the frozen risk models (2018-22 data)
    cd engine && uv run python -m eval.wind_replay --workers 24 --cache wind_replay.pkl \
        --out ../docs/wind_replay.md --json wind_replay.json             # the test (big CPU job)

Needs engine/weather/data/ (python -m weather.fetch, or a copy of it).

Fires. Each episode is a fire on the map of the region a station is in
(Oroville OVE -> Paradise, Broomfield BJC -> Marshall), driven minute by
minute by that station's *observed* wind (trailing mean over the station's
window), from a start time in the 2023-24 test seasons that no model saw.
Starts: seeded random times with wind >= START_WIND, at least 12 h apart,
with observations and a preloaded forecast available. The ignition is a
seeded random burnable cell within IGNITION_RADIUS of the real fire's origin.

Forecasters, all from the same snapshot and seed at every issue time:
  constant          the engine's forecast: the wind at issue holds
  ensemble 0.25/h   the fixed wind-scenario ensemble (#228)
  ensemble 1/h      the same at 1 shift/h (exploratory in #228)
  conditional onboard            shift rate per forecast from the on-board
                                 risk model (the drone's own wind history)
  conditional onboard+forecast   the same plus the preloaded HRRR run
  conditional budget-matched     secondary, added after a smoke test showed
                                 the calibrated rates average ~0.03/h (so the
                                 primary barely hedges): rate = 1/h * P / P_train,
                                 P_train the mean predicted P on the 2018-22
                                 training rows. Same average hedging as the 1/h
                                 ensemble, moved to risky times. Defined from
                                 training data only. (The smoke test's two fires,
                                 the first at each station, stay in the test set.)
  oracle (diagnostic)            every rollout follows the wind that really
                                 came next: an upper bound, never deployable
The conditional rate is rate = -ln(1 - P(shift within 60 min)) per hour
(forecast.wind_risk.rate_per_hour), fixed in advance; the risk models are
frozen, fit on 2018-22 meteorology only (--fit-models). Nothing is tuned on
these fires. Each forecaster has its own conformal controller state.

Pre-shift forecasts: those whose own window [t, t + h] holds an observed
wind change (a shift > 45 deg or a surge, weather.dataset definitions).

Decision rule, fixed before running: the conditional (onboard+forecast)
method improves the trade-off if, at equal risk (no controller, pooled 10%
miss), (1) its pre-shift miss is lower than constant wind's, with a 90%
bootstrap interval over episodes excluding zero, and (2) it needs less
outline area than the 1/h ensemble. Everything else is reported, secondary.
"""

import argparse
import json
import pickle
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from eval import conformal_compare as cc
from eval import wind_ensemble as we
from forecast import wind_risk as R
from forecast.runner import N_ROLLOUTS, run_forecast
from forecast.wind import WindPaths, WindScenarios
from sim.fire import Wind
from weather import dataset as D
from weather import hrrr
from weather.fetch import DATA, MONTHS, SITES
from weather.obs import fetch_station, from_uv

TEST_YEARS = (2023, 2024)
TRAIN_YEARS = (2018, 2019, 2020, 2021, 2022)
STATIONS = {  # station -> (scenario, real fire origin in map coords)
    "OVE": ("paradise", (412.07, 113.02)),  # Camp Fire
    "BJC": ("marshall", (48.53, 86.18)),  # Marshall Fire
}
EPISODES = 30  # per station
TICKS, EVERY = 300, 5  # sim minutes of forecasts; minutes between them
START_WIND = 3.0  # m/s at the start, so the fire spreads
MIN_GAP_H = 12.0
IGNITION_RADIUS = 40  # cells
MODELS = Path(__file__).resolve().parent.parent / "forecast" / "wind_risk_models"
FEATURES = {"onboard": D.ONBOARD, "onboard+forecast": D.ONBOARD + [f"{c}_60" for c in D.FORECAST]}
BOOT = 1000
BUDGET_RATE = 1.0  # shifts/h on average for the budget-matched variant: the 1/h ensemble's


# --- Data -------------------------------------------------------------------------------

def series(code: str) -> D.Series:
    s = SITES[code]
    years = TRAIN_YEARS + TEST_YEARS
    a = fetch_station(code, [(y, m) for y in years for m in MONTHS], s["one_minute"], DATA / "obs")
    return D.Series(a[:, 0], a[:, 1], a[:, 2], 600.0 if s["one_minute"] else 1200.0)


def fit_models() -> dict:
    """The frozen risk models: logistic P(shift within 60 min), fit on every
    valid 2018-22 row of both stations. Saved to forecast/wind_risk_models/."""
    from eval.wind_shift_skill import load_rows

    rows = load_rows(False)
    MODELS.mkdir(exist_ok=True)
    out = {}
    for name, cols in FEATURES.items():
        ok = (rows["valid_60"] > 0) & np.isin(rows["year"], TRAIN_YEARS)
        for c in cols:
            ok &= np.isfinite(rows[c])
        x = np.column_stack([rows[c][ok] for c in cols])
        m = R.fit(x, rows["shift_60"][ok], cols, l2=1.0)
        m.train_mean_p = float(m.predict(x).mean())
        m.save(MODELS / f"shift60_{name.replace('+', '_')}.json")
        out[name] = {"n": int(ok.sum()), "events": int(rows["shift_60"][ok].sum())}
    return out


def load_model(name: str) -> R.ShiftRisk:
    return R.ShiftRisk.load(MODELS / f"shift60_{name.replace('+', '_')}.json")


def episode_starts(code: str, s: D.Series, runs: dict) -> list[float]:
    """Seeded random starts in the test seasons (see the module docstring)."""
    inits = np.array(sorted(runs))
    cands = []
    for yr in TEST_YEARS:
        t0 = datetime(yr, MONTHS[0], 1, tzinfo=timezone.utc).timestamp()
        t1 = datetime(yr + 1, 1, 1, tzinfo=timezone.utc).timestamp()
        cands.append(np.arange(t0 + 3600, t1 - (TICKS + 90) * 60, 1800.0))
    t = np.concatenate(cands)
    u, v, _ = D.wind_at(s, t)
    ok = np.hypot(u, v) >= START_WIND
    # Observations in every half hour from 1 h before to the end, and a preload at the start.
    for k in range(-2, (TICKS + 60) // 30 + 1):
        _, _, n = D.wind_at(s, t + k * 1800, 1800.0)
        ok &= n > 0
    ok &= np.array([D.preloaded_run(inits, x) is not None for x in t])
    t = t[ok]
    rng = np.random.default_rng(sum(map(ord, code)))
    chosen: list[float] = []
    for x in rng.permutation(t):
        if all(abs(x - c) >= MIN_GAP_H * 3600 for c in chosen):
            chosen.append(float(x))
        if len(chosen) == EPISODES:
            break
    return sorted(chosen)


def observed_wind(s: D.Series, start: float, minutes: int) -> tuple[np.ndarray, np.ndarray]:
    """Per minute from start: the station's trailing-mean wind (speed, from),
    gaps held at the last value."""
    u, v, n = D.wind_at(s, start + 60.0 * np.arange(minutes + 1))
    sp, fr = from_uv(u, v)
    for i in range(len(sp)):
        if not np.isfinite(sp[i]) or n[i] == 0:
            sp[i], fr[i] = (sp[i - 1], fr[i - 1]) if i else (0.0, 0.0)
    return sp, fr


def ignition(scenario: str, origin: tuple[float, float], seed: int) -> tuple[float, float]:
    from scenario import load_scenario
    from sim.fire import FUEL, FireSim

    sim = FireSim(load_scenario(scenario), seed=0)
    ys, xs = np.nonzero(sim.state == FUEL)
    near = np.hypot(xs + 0.5 - origin[0], ys + 0.5 - origin[1]) <= IGNITION_RADIUS
    i = np.random.default_rng(seed).choice(np.flatnonzero(near))
    return float(xs[i]) + 0.5, float(ys[i]) + 0.5


# --- One episode ------------------------------------------------------------------------

def _episode(args):
    code, k, start = args
    t_run = time.perf_counter()
    scenario, origin = STATIONS[code]
    s = series(code)
    runs = hrrr.load_runs(DATA / "hrrr" / code)
    sp, fr = observed_wind(s, start, TICKS + 61)
    wind_fn = lambda tick: Wind(float(sp[min(tick, len(sp) - 1)]), float(fr[min(tick, len(fr) - 1)]))  # noqa: E731
    seed = 10_000 + k + (0 if code == "OVE" else 5_000)
    lon = SITES[code]["lon"]
    models = {name: load_model(name) for name in FEATURES}
    rates: dict[str, list] = {k: [] for k in list(FEATURES) + ["onboard+forecast budget"]}
    fallback = [0]

    def conditional(name, budget=False):
        key = name + (" budget" if budget else "")

        def forecast(snap):
            t = np.array([start + 60.0 * snap.tick])
            feats = D.onboard_features(s, t, lon)
            row = {c: feats[c] for c in D.ONBOARD}
            m = models[name]
            if name == "onboard+forecast":
                ff = D.forecast_features(runs, t, 60, feats["u"], feats["v"])
                row.update({f"{c}_60": ff[c] for c in D.FORECAST})
                if not all(np.isfinite(row[c]).all() for c in m.features):
                    m = models["onboard"]  # no usable preload: the on-board model alone
                    fallback[0] += 1
            x = np.column_stack([np.nan_to_num(row[c], nan=0.0) for c in m.features])
            p = float(m.predict(x)[0])
            rate = (min(BUDGET_RATE * p / m.train_mean_p, R.MAX_RATE_PER_H) if budget
                    else float(R.rate_per_hour(p)))
            rates[key].append(rate)
            return run_forecast(snap, n=N_ROLLOUTS, seed=seed * 1000 + snap.tick,
                                wind_model=WindScenarios(shift_rate_per_h=rate)).probability
        return forecast

    def oracle(snap):  # diagnostic only: the wind that really came next
        i = snap.tick
        paths = WindPaths(sp[i + 1 : i + 62, None].astype(np.float32), fr[i + 1 : i + 62, None].astype(np.float32))
        return run_forecast(snap, n=N_ROLLOUTS, seed=seed * 1000 + snap.tick, wind_paths=paths).probability

    forecasters = {
        "constant": {"wind_model": None},
        "ensemble 0.25/h": {"wind_model": WindScenarios(shift_rate_per_h=0.25)},
        "ensemble 1/h": {"wind_model": WindScenarios(shift_rate_per_h=1.0)},
        "conditional onboard": conditional("onboard"),
        "conditional onboard+forecast": conditional("onboard+forecast"),
        "conditional budget-matched": conditional("onboard+forecast", budget=True),
        "oracle (diagnostic)": oracle,
    }
    eps = cc.record(code, seed, TICKS, EVERY, N_ROLLOUTS, scenario, forecasters=forecasters, wind_fn=wind_fn,
                    ignition=ignition(scenario, origin, seed))
    # Pre-shift issue ticks per horizon index, from the observed wind.
    pre = {}
    issues = np.arange(0, TICKS + 1, EVERY)
    t = start + 60.0 * issues
    u0, v0, _ = D.wind_at(s, t)
    for hi, h in enumerate(D.HORIZONS_MIN):
        u1, v1, _ = D.wind_at(s, t + h * 60)
        tg = D.shift_targets(u0, v0, u1, v1)
        pre[hi] = set(issues[tg["shift"] | tg["surge"]].tolist())
    for e in eps:
        e.pre_shift = pre
        e.info = {"start": start, "rates": rates, "fallback": fallback[0], "seconds": time.perf_counter() - t_run}
    print(f"  {code} episode {k} ({datetime.fromtimestamp(start, timezone.utc):%Y-%m-%d %H:%M}Z): "
          f"{sum(len(v) for v in pre.values())} pre-shift forecasts, {time.perf_counter() - t_run:.0f} s", flush=True)
    return eps


# --- Summary ----------------------------------------------------------------------------

def boot_decision(eps: list, names: list[str], rng) -> dict:
    """Bootstrap over episodes (paired across forecasters): equal-risk
    pre-shift miss difference (conditional - constant) and the area ratio
    conditional / ensemble 1/h, per horizon."""
    by = {}
    for e in eps:
        by.setdefault((e.sched, e.seed), {})[e.forecaster] = e
    keys = sorted(by)
    out = {}
    for h, m in enumerate((30, 60)):
        diffs, ratios, bd, br = [], [], [], []
        for _ in range(BOOT):
            pick = [keys[i] for i in rng.integers(len(keys), size=len(keys))]
            fs = ("constant", "ensemble 1/h", "conditional onboard+forecast", "conditional budget-matched")
            r = {f: we.equal_risk([by[k][f] for k in pick], h) for f in fs if f in by[pick[0]]}
            if any(v.get("pre_shift_miss") is None or v.get("area_km2") is None for v in r.values()):
                continue
            diffs.append(r["conditional onboard+forecast"]["pre_shift_miss"] - r["constant"]["pre_shift_miss"])
            ratios.append(r["conditional onboard+forecast"]["area_km2"] / r["ensemble 1/h"]["area_km2"])
            if "conditional budget-matched" in r:
                bd.append(r["conditional budget-matched"]["pre_shift_miss"] - r["ensemble 1/h"]["pre_shift_miss"])
                br.append(r["conditional budget-matched"]["area_km2"] / r["ensemble 1/h"]["area_km2"])
        q = lambda a: [float(np.percentile(a, 5)), float(np.percentile(a, 95))] if a else None  # noqa: E731
        out[f"T+{m}"] = {"pre_shift_diff_vs_constant": q(diffs), "area_ratio_vs_1h": q(ratios), "draws": len(diffs),
                         "budget_pre_shift_diff_vs_1h": q(bd), "budget_area_ratio_vs_1h": q(br)}
    return out


def _f(x, pct=False, d=2):
    if x is None:
        return "–"
    return f"{100 * x:.1f}%" if pct else f"{x:.{d}f}"


def report(s: dict, rates: dict, boot: dict, meta: dict) -> str:
    L = ["# Forecast-conditioned wind uncertainty on real-wind fires (#231, stage 2)", "",
         f"{meta['episodes']} fires ({EPISODES} per station) driven by observed 2023-24 winds; "
         f"{N_ROLLOUTS} rollouts, a forecast every {EVERY} min for {TICKS} min; target miss 10%. Pre-shift = "
         "the forecast's window held an observed shift (> 45°) or surge. The oracle is a diagnostic upper bound "
         "fed the future wind: never deployable.", "",
         "## Equal risk, no controller (the decision rule's view)", "",
         "| forecaster | horizon | cutoff θ | pooled miss | area km² | pre-shift miss | pre-shift area km² |",
         "|---|---|---|---|---|---|---|"]
    fs = s["forecasters"]
    for name, r in fs.items():
        for hk, hr in r["horizons"].items():
            e = hr["equal_risk"]
            L.append(f"| {name} | {hk} | {_f(e.get('theta'), d=3)} | {_f(e.get('miss'), True)} | {_f(e.get('area_km2'))} | "
                     f"{_f(e.get('pre_shift_miss'), True)} | {_f(e.get('pre_shift_area_km2'))} |")
    L += ["", "**Decision rule** (fixed in advance): conditional onboard+forecast must lower the pre-shift miss vs "
          "constant wind (90% CI over episodes excluding 0) and need less area than the 1/h ensemble (ratio < 1).", "",
          "| horizon | pre-shift miss, conditional − constant (90% CI) | area, conditional / 1/h (90% CI) | draws |",
          "|---|---|---|---|"]
    for hk, b in boot.items():
        d, r = b["pre_shift_diff_vs_constant"], b["area_ratio_vs_1h"]
        L.append(f"| {hk} | {('[' + _f(d[0], True) + ', ' + _f(d[1], True) + ']') if d else '–'} | "
                 f"{('[' + _f(r[0]) + ', ' + _f(r[1]) + ']') if r else '–'} | {b['draws']} |")
    L += ["", "Secondary (added after the smoke test; see the docstring): budget-matched conditional vs the 1/h "
          "ensemble it is budget-matched to, at equal risk.", "",
          "| horizon | pre-shift miss, budget-matched − 1/h (90% CI) | area, budget-matched / 1/h (90% CI) |", "|---|---|---|"]
    for hk, b in boot.items():
        d, r = b.get("budget_pre_shift_diff_vs_1h"), b.get("budget_area_ratio_vs_1h")
        L.append(f"| {hk} | {('[' + _f(d[0], True) + ', ' + _f(d[1], True) + ']') if d else '–'} | "
                 f"{('[' + _f(r[0]) + ', ' + _f(r[1]) + ']') if r else '–'} |")
    L += ["", "## Under the engine's controller (fixed-rate ACI, own state per forecaster)", "",
          "| forecaster | horizon | station | miss | worst 30 min | area km² | vs oracle | pre-shift miss | at widest |",
          "|---|---|---|---|---|---|---|---|---|"]
    for hk in ("T+30", "T+60"):
        for st in ("all", "OVE", "BJC"):
            for name, r in fs.items():
                m = r["horizons"][hk]["aci"].get(st)
                if m:
                    L.append(f"| {name} | {hk} | {st} | {_f(m.get('miss'), True)} | {_f(m.get('worst30'), True)} | "
                             f"{_f(m.get('area_km2'))} | {_f(m.get('vs_oracle'))}× | {_f(m.get('pre_shift_miss'), True)} | "
                             f"{_f(m.get('sat'), True)} |")
    L += ["", "## Conditional shift rates and cost", "",
          "| forecaster | mean rate /h | share of forecasts > 0.5/h | share > 1/h | mean forecast ms | p90 ms |",
          "|---|---|---|---|---|---|"]
    for name, r in fs.items():
        rr = rates.get(name)
        extra = (f"{np.mean(rr):.2f} | {np.mean(np.array(rr) > 0.5):.1%} | {np.mean(np.array(rr) > 1.0):.1%}"
                 if rr else "– | – | –")
        L.append(f"| {name} | {extra} | {r['forecast_ms_mean']:.0f} | {r['forecast_ms_p90']:.0f} |")
    L.append(f"\nPreloads missing (onboard+forecast fell back to onboard): {meta['fallback']} forecasts.")
    return "\n".join(L) + "\n"


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--fit-models", action="store_true", help="fit and save the frozen risk models, then exit")
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--cache")
    p.add_argument("--out")
    p.add_argument("--json")
    p.add_argument("--episodes", type=int, default=EPISODES, help="per station (smaller for a smoke test)")
    args = p.parse_args()
    if args.fit_models:
        print(json.dumps(fit_models(), indent=1))
        return
    eps = None
    if args.cache:
        try:
            with open(args.cache, "rb") as f:
                eps = pickle.load(f)
            print(f"loaded {len(eps)} episodes from {args.cache}")
        except FileNotFoundError:
            pass
    if eps is None:
        jobs = []
        for code in STATIONS:
            s = series(code)
            starts = episode_starts(code, s, hrrr.load_runs(DATA / "hrrr" / code))[: args.episodes]
            print(f"{code}: {len(starts)} episodes", flush=True)
            jobs += [(code, k, t) for k, t in enumerate(starts)]
        print(f"recording {len(jobs)} fires x 7 forecasters on {args.workers} workers", flush=True)
        with ProcessPoolExecutor(args.workers) as pool:
            eps = [e for group in pool.map(_episode, jobs) for e in group]
        if args.cache:
            with open(args.cache, "wb") as f:
                pickle.dump(eps, f)
    names = list(dict.fromkeys(e.forecaster for e in eps))
    summary = we.summarize(eps, names, ["static", "aci"], N_ROLLOUTS)
    rates = {}
    for name, key in (("conditional onboard", "onboard"), ("conditional onboard+forecast", "onboard+forecast"),
                      ("conditional budget-matched", "onboard+forecast budget")):
        rates[name] = [r for e in eps if e.forecaster == name for r in e.info["rates"][key]]
    boot = boot_decision(eps, names, np.random.default_rng(0))
    meta = {"episodes": len({(e.sched, e.seed) for e in eps}),
            "fallback": sum(e.info["fallback"] for e in eps if e.forecaster == "conditional onboard+forecast")}
    text = report(summary, rates, boot, meta)
    if args.json:
        with open(args.json, "w") as f:
            json.dump({"summary": summary, "bootstrap": boot, "meta": meta}, f, indent=1, default=float)
    if args.out:
        with open(args.out, "w") as f:
            f.write(text)
    print(text)


if __name__ == "__main__":
    main()
