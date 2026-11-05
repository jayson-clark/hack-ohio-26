"""Are 30-60 min wind shifts predictable from forecast-time information? (#231)

    cd engine && uv run --with numcodecs python -m weather.fetch       # once: the data
    cd engine && uv run python -m eval.wind_shift_skill --out ../docs/wind_shift_skill.md --json skill.json

Meteorology only, no fire. Stations, events and features are defined in
weather.dataset; the model is forecast.wind_risk. Compared, for each horizon
(30, 60 min) and event (shift > 45 deg, reversal > 135 deg, speed surge):

  persistence      P = 0: the wind holds (the engine's forecast today)
  constant         the training base rate per station (an unconditional
                   ensemble's view: the same risk every time)
  onboard          logistic on what a drone measures itself: current wind,
                   its change over 30/60 min, steadiness, gustiness, hour
  onboard+forecast the same plus a preloaded HRRR forecast (its predicted
                   change over the horizon, gusts, spatial spread, current
                   error and age)

Splits, fixed in advance: chronological (fit on 2018-2022 fire seasons, test
on 2023-2024), and across stations (fit on one region, test on the other).
All models are scored on the same test rows (where a preloaded forecast
exists). Scores: Brier, Brier skill vs constant (BSS), log loss, ROC AUC,
calibration by bin, and hit / false-alarm rates at P >= 0.2 and 0.5.
Intervals: 90% bootstrap over test days (samples within a day are correlated).

--stale repeats it with the forecast loaded 6 h earlier (7-13 h old), as on a
long flight without a fresh uplink.

Also wind-vector error at t + h for persistence, raw HRRR, and a linear blend
of the two fit on the training years (MOS-style).
"""

import argparse
import json
from datetime import datetime, timezone

import numpy as np

from forecast import wind_risk as R
from weather import dataset as D
from weather import hrrr
from weather.fetch import DATA, MONTHS, SITES, YEARS

TRAIN_YEARS = tuple(y for y in YEARS if y <= 2022)
TEST_YEARS = tuple(y for y in YEARS if y > 2022)
EVENTS = ("shift", "reversal", "surge")
BOOT = 500
L2 = 1.0
# Fewer events than this and a split is reported as too few to score, not
# scored: set after seeing event counts (Oroville is calm), before any skill.
MIN_TRAIN_EVENTS = 30
MIN_TEST_EVENTS = 20


def load_rows(stale: bool = False) -> dict[str, np.ndarray]:
    from weather.obs import fetch_station

    parts = []
    latency = D.RUN_LATENCY_H + (6.0 if stale else 0.0)
    for code, s in SITES.items():
        a = fetch_station(code, [(y, m) for y in YEARS for m in MONTHS], s["one_minute"], DATA / "obs")
        series = D.Series(a[:, 0], a[:, 1], a[:, 2], 600.0 if s["one_minute"] else 1200.0)
        runs = hrrr.load_runs(DATA / "hrrr" / code)
        for yr in YEARS:
            start = datetime(yr, MONTHS[0], 1, tzinfo=timezone.utc).timestamp()
            end = datetime(yr + 1, 1, 1, tzinfo=timezone.utc).timestamp() if MONTHS[-1] == 12 else \
                datetime(yr, MONTHS[-1] + 1, 1, tzinfo=timezone.utc).timestamp()
            rows = D.build(series, runs, start, end, s["lon"], latency_h=latency,
                           max_age_h=D.MAX_RUN_AGE_H + (6.0 if stale else 0.0))
            rows["site"] = np.array([code] * len(rows["t"]))
            rows["year"] = np.full(len(rows["t"]), yr)
            parts.append(rows)
    return {k: np.concatenate([p[k] for p in parts]) for k in parts[0]}


def auc(y: np.ndarray, p: np.ndarray) -> float:
    """ROC AUC by ranks (ties get their average rank), vectorized."""
    y = y.astype(bool)
    n1, n0 = int(y.sum()), int((~y).sum())
    if n1 == 0 or n0 == 0:
        return float("nan")
    srt = np.sort(p)
    ranks = (np.searchsorted(srt, p, "left") + np.searchsorted(srt, p, "right") + 1) / 2.0
    return float((ranks[y].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def scores(y: np.ndarray, p: np.ndarray, ref: np.ndarray) -> dict:
    p = np.clip(p, 1e-6, 1 - 1e-6)
    brier, bref = np.mean((p - y) ** 2), np.mean((ref - y) ** 2)
    out = {"brier": float(brier), "bss": float(1 - brier / bref) if bref > 0 else float("nan"),
           "logloss": float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))), "auc": auc(y, p)}
    for th in (0.2, 0.5):
        warn = p >= th
        out[f"pod_{th}"] = float(warn[y > 0].mean()) if (y > 0).any() else float("nan")  # hit rate
        out[f"far_{th}"] = float((y[warn] == 0).mean()) if warn.any() else float("nan")  # false-alarm ratio
        out[f"warn_rate_{th}"] = float(warn.mean())
    return out


def reliability(y: np.ndarray, p: np.ndarray, bins=(0, 0.05, 0.1, 0.2, 0.3, 0.5, 1.0001)) -> list:
    idx = np.digitize(p, bins) - 1
    return [{"bin": f"{bins[i]:.2f}-{min(bins[i + 1], 1):.2f}", "n": int((idx == i).sum()),
             "mean_p": float(p[idx == i].mean()), "observed": float(y[idx == i].mean())}
            for i in range(len(bins) - 1) if (idx == i).any()]


def boot(y, preds: dict, ref_key: str, days: np.ndarray, rng) -> dict:
    """90% intervals over resampled test days for BSS and AUC of each model,
    and for the AUC gain of onboard+forecast over onboard."""
    uniq = np.unique(days)
    by_day = {d: np.flatnonzero(days == d) for d in uniq}
    out = {k: {"bss": [], "auc": []} for k in preds}
    gain = []
    for _ in range(BOOT):
        idx = np.concatenate([by_day[d] for d in rng.choice(uniq, len(uniq))])
        yy = y[idx]
        if yy.sum() == 0:
            continue
        for k, p in preds.items():
            s = scores(yy, p[idx], preds[ref_key][idx])
            out[k]["bss"].append(s["bss"])
            out[k]["auc"].append(s["auc"])
        if "onboard" in preds and "onboard+forecast" in preds:
            gain.append(auc(yy, preds["onboard+forecast"][idx]) - auc(yy, preds["onboard"][idx]))
    q = lambda a: [float(np.nanpercentile(a, 5)), float(np.nanpercentile(a, 95))] if a else None  # noqa: E731
    res = {k: {m: q(v[m]) for m in v} for k, v in out.items()}
    res["auc_gain_forecast"] = q(gain)
    return res


def matrix(rows: dict, cols: list[str], mask: np.ndarray) -> np.ndarray:
    return np.column_stack([rows[c][mask] for c in cols])


def evaluate(rows: dict, train: np.ndarray, test: np.ndarray, h: int, event: str, rng) -> dict:
    y_all = rows[f"{event}_{h}"]
    fcols = [f"{c}_{h}" for c in D.FORECAST]
    base = rows[f"valid_{h}"] > 0
    for c in D.ONBOARD + fcols:
        base &= np.isfinite(rows[c])
    tr, te = base & train, base & test
    y_tr, y_te = y_all[tr], y_all[te]
    if y_tr.sum() < MIN_TRAIN_EVENTS or y_te.sum() < MIN_TEST_EVENTS:
        return {"n_train": int(tr.sum()), "events_train": int(y_tr.sum()), "n_test": int(te.sum()),
                "events_test": int(y_te.sum()), "too_few_events": True}
    models = {"persistence": R.persistence()}
    # Constant rate per station, from training rows.
    const = np.zeros(te.sum())
    for site in np.unique(rows["site"]):
        m_tr, m_te = tr & (rows["site"] == site), te & (rows["site"] == site)
        rate = y_all[m_tr].mean() if m_tr.any() else y_tr.mean()
        const[(rows["site"][te] == site)] = rate
    onboard = R.fit(matrix(rows, D.ONBOARD, tr), y_tr, D.ONBOARD, L2)
    withf = R.fit(matrix(rows, D.ONBOARD + fcols, tr), y_tr, D.ONBOARD + fcols, L2)
    preds = {"persistence": models["persistence"].predict(np.zeros((te.sum(), 0))), "constant": const,
             "onboard": onboard.predict(matrix(rows, D.ONBOARD, te)),
             "onboard+forecast": withf.predict(matrix(rows, D.ONBOARD + fcols, te))}
    days = (rows["t"][te] // 86400).astype(int) * 10 + np.searchsorted(np.unique(rows["site"]), rows["site"][te])
    out = {"n_train": int(tr.sum()), "events_train": int(y_tr.sum()), "n_test": int(te.sum()),
           "events_test": int(y_te.sum()), "base_rate_test": float(y_te.mean()),
           "models": {k: scores(y_te, p, const) for k, p in preds.items()},
           "reliability": {k: reliability(y_te, preds[k]) for k in ("constant", "onboard", "onboard+forecast")},
           "intervals": boot(y_te, {k: v for k, v in preds.items() if k != "persistence"}, "constant", days, rng),
           "coefficients": {"onboard": dict(zip(onboard.features, np.round(onboard.weights, 3).tolist())),
                            "onboard+forecast": dict(zip(withf.features, np.round(withf.weights, 3).tolist()))}}
    if event == "shift":  # how many of the big reversals and surges each model warned of, at P >= 0.2
        for sub in ("reversal", "surge"):
            ys = rows[f"{sub}_{h}"][te] > 0
            out[f"warned_{sub}_0.2"] = {k: float((p[ys] >= 0.2).mean()) if ys.any() else None
                                        for k, p in preds.items()}
            out[f"n_{sub}_test"] = int(ys.sum())
    return out


def vector_errors(rows: dict, train: np.ndarray, test: np.ndarray, h: int) -> dict:
    """Error of the wind at t + h: persistence, raw HRRR, and a linear blend."""
    cols = ["u", "v", f"f_u_h_{h}", f"f_v_h_{h}"]
    ok = rows[f"valid_{h}"] > 0
    for c in cols + [f"obs_u_{h}", f"obs_v_{h}"]:
        ok &= np.isfinite(rows[c])
    tr, te = ok & train, ok & test
    obs = np.column_stack([rows[f"obs_u_{h}"], rows[f"obs_v_{h}"]])
    X = np.column_stack([rows[c] for c in cols] + [np.ones(len(rows["t"]))])
    coef = np.linalg.lstsq(X[tr], obs[tr], rcond=None)[0]
    preds = {"persistence": X[te][:, :2], "hrrr": X[te][:, 2:4], "blend": X[te] @ coef}
    o = obs[te]
    so = np.hypot(o[:, 0], o[:, 1])
    out = {"n_test": int(te.sum())}
    for k, p in preds.items():
        sp = np.hypot(p[:, 0], p[:, 1])
        m = (so >= D.MIN_SPEED) & (sp >= D.MIN_SPEED)
        out[k] = {"vector_rmse": float(np.sqrt(np.mean(np.sum((p - o) ** 2, axis=1)))),
                  "speed_mae": float(np.mean(np.abs(sp - so))),
                  "direction_mae_deg": float(np.mean(D.angle_between(p[m, 0], p[m, 1], o[m, 0], o[m, 1])))}
    return out


def follow_up(rows: dict, train: np.ndarray, test: np.ndarray, h: int, event: str) -> dict | None:
    """Defined after the first results, so reported as a follow-up, not a
    pre-registered test. Only issue times where a shift was possible (wind
    >= MIN_SPEED now, so "calm now, no shift" can't earn credit), models and
    the constant rate refit on those: AUC, Brier skill, and concentration,
    the share of events in the riskiest 10% / 20% of times (no skill: 10% / 20%).
    Concentration is what a conditional ensemble needs: hedge when risk is high."""
    fcols = [f"{c}_{h}" for c in D.FORECAST]
    base = (rows[f"valid_{h}"] > 0) & (rows["speed"] >= D.MIN_SPEED)
    for c in D.ONBOARD + fcols:
        base &= np.isfinite(rows[c])
    tr, te = base & train, base & test
    y = rows[f"{event}_{h}"]
    if y[tr].sum() < MIN_TRAIN_EVENTS or y[te].sum() < MIN_TEST_EVENTS:
        return None
    yy = y[te]
    const = np.zeros(te.sum())
    for site in np.unique(rows["site"]):
        m = tr & (rows["site"] == site)
        const[rows["site"][te] == site] = y[m].mean() if m.any() else y[tr].mean()
    out = {"n_test": int(te.sum()), "events_test": int(yy.sum()), "base_rate": float(yy.mean()), "models": {}}
    for name, cols in (("constant", None), ("onboard", D.ONBOARD), ("onboard+forecast", D.ONBOARD + fcols)):
        p = const if cols is None else R.fit(matrix(rows, cols, tr), y[tr], cols, L2).predict(matrix(rows, cols, te))
        r = {"auc": auc(yy, p), "bss": float(1 - np.mean((p - yy) ** 2) / np.mean((const - yy) ** 2))}
        for q in (10, 20):
            top = p >= np.percentile(p, 100 - q)
            r[f"top{q}_share"] = float(yy[top].sum() / yy.sum())
            r[f"top{q}_rate"] = float(yy[top].mean())
        if cols is not None:  # within each station, so station identity can't earn credit
            sites = rows["site"][te]
            r["within_station_top20"] = {}
            for site in np.unique(sites):
                ys, ps = yy[sites == site], p[sites == site]
                if ys.sum() >= 10:
                    top = ps >= np.percentile(ps, 80)
                    r["within_station_top20"][str(site)] = {"events": int(ys.sum()), "share": float(ys[top].sum() / ys.sum()),
                                                            "auc": auc(ys, ps)}
        out["models"][name] = r
    return out


def run(stale: bool) -> dict:
    rows = load_rows(stale)
    rng = np.random.default_rng(0)
    splits = {"chronological (train 2018-22, test 2023-24)": (np.isin(rows["year"], TRAIN_YEARS),
                                                              np.isin(rows["year"], TEST_YEARS))}
    for a in SITES:
        others = [b for b in SITES if b != a]
        splits[f"across stations (train {a}, test {'+'.join(others)})"] = (rows["site"] == a, np.isin(rows["site"], others))
    out = {"stale_forecast": stale, "rows": int(len(rows["t"])), "splits": {}}
    for name, (tr, te) in splits.items():
        out["splits"][name] = {f"{e} {h} min": evaluate(rows, tr, te, h, e, rng) for h in D.HORIZONS_MIN for e in EVENTS}
        out["splits"][name]["wind vector"] = {f"{h} min": vector_errors(rows, tr, te, h) for h in D.HORIZONS_MIN}
        out["splits"][name]["follow-up"] = {f"{e} {h} min": follow_up(rows, tr, te, h, e)
                                           for h in D.HORIZONS_MIN for e in EVENTS}
    return out


def _f(x, pct=False, d=3):
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "–"
    return f"{100 * x:.1f}%" if pct else f"{x:.{d}f}"


def report(res: dict) -> str:
    L = [f"# Wind-shift predictability (#231){' — stale forecast (7-13 h old)' if res['stale_forecast'] else ''}", "",
         f"{res['rows']:,} issue times (every 30 min, Sep-Dec 2018-2024, Oroville OVE and Broomfield BJC).", ""]
    for split, by in res["splits"].items():
        L += [f"## {split}", "",
              "| event | n test (events) | base rate | model | Brier | BSS vs constant (90% CI) | AUC (90% CI) | "
              "hit / false-alarm @0.2 | warned @0.2 | hit / false-alarm @0.5 |",
              "|---|---|---|---|---|---|---|---|---|---|"]
        for ev, r in by.items():
            if ev in ("wind vector", "follow-up"):
                continue
            if r.get("too_few_events"):
                L.append(f"| {ev} | {r['n_test']} ({r['events_test']}) | | too few events to score "
                         f"({r['events_train']} train, {r['events_test']} test) | | | | | | |")
                continue
            for k, s in r["models"].items():
                ci = r["intervals"].get(k, {})
                bss_ci = f" [{_f(ci['bss'][0])}, {_f(ci['bss'][1])}]" if ci.get("bss") else ""
                auc_ci = f" [{_f(ci['auc'][0])}, {_f(ci['auc'][1])}]" if ci.get("auc") else ""
                L.append(f"| {ev} | {r['n_test']} ({r['events_test']}) | {_f(r['base_rate_test'], True)} | {k} | "
                         f"{_f(s['brier'], d=4)} | {_f(s['bss'])}{bss_ci} | {_f(s['auc'])}{auc_ci} | "
                         f"{_f(s['pod_0.2'], True)} / {_f(s['far_0.2'], True)} | {_f(s['warn_rate_0.2'], True)} | "
                         f"{_f(s['pod_0.5'], True)} / {_f(s['far_0.5'], True)} |")
            g = r["intervals"].get("auc_gain_forecast")
            if g:
                L.append(f"| {ev} | | | AUC gain from the forecast | | | 90% CI [{_f(g[0])}, {_f(g[1])}] | | | |")
        L += ["", "Of the shifts that were also reversals (> 135°) or surges, the share each model warned of at P ≥ 0.2:", ""]
        for ev, r in by.items():
            if not ev.startswith("shift") or ev in ("wind vector", "follow-up") or r.get("too_few_events"):
                continue
            for sub in ("reversal", "surge"):
                w = r.get(f"warned_{sub}_0.2")
                if w:
                    L.append(f"- {ev}, {sub}s ({r[f'n_{sub}_test']}): " + ", ".join(f"{k} {_f(v, True)}" for k, v in w.items()))
        L += ["", "Wind at t + h (test rows):", "", "| horizon | predictor | vector RMSE m/s | speed MAE m/s | direction MAE ° |",
              "|---|---|---|---|---|"]
        for hk, r in by["wind vector"].items():
            for k in ("persistence", "hrrr", "blend"):
                L.append(f"| {hk} | {k} | {_f(r[k]['vector_rmse'], d=2)} | {_f(r[k]['speed_mae'], d=2)} | "
                         f"{_f(r[k]['direction_mae_deg'], d=1)} |")
        L += ["", "**Follow-up (defined after the first results): only times with wind >= 2.5 m/s at issue**, models refit "
              "on those. Concentration = share of the test events in the riskiest 10% / 20% of times (no skill: 10% / 20%).",
              "", "| event | n test (events) | base rate | model | AUC | BSS vs constant | top 10% holds | top 20% holds | "
              "risk in top 10% |", "|---|---|---|---|---|---|---|---|---|"]
        for ev, r in by["follow-up"].items():
            if r is None:
                L.append(f"| {ev} | | | too few events | | | | | |")
                continue
            for k, m in r["models"].items():
                L.append(f"| {ev} | {r['n_test']} ({r['events_test']}) | {_f(r['base_rate'], True)} | {k} | {_f(m['auc'])} | "
                         f"{_f(m['bss'])} | {_f(m['top10_share'], True)} | {_f(m['top20_share'], True)} | "
                         f"{_f(m['top10_rate'], True)} |")
        L += ["", "Within each station (the constant rate's concentration above is only the windier station's share; "
              "this removes station identity): share of events in a station's riskiest 20%, and AUC.", ""]
        for ev, r in by["follow-up"].items():
            if r is None:
                continue
            for k in ("onboard", "onboard+forecast"):
                w = r["models"][k].get("within_station_top20", {})
                if w:
                    L.append(f"- {ev}, {k}: " + "; ".join(f"{st} {v['share']:.0%} of {v['events']} (AUC {v['auc']:.2f})"
                                                         for st, v in w.items()))
        L.append("")
    return "\n".join(L)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--stale", action="store_true", help="forecast loaded 6 h earlier (7-13 h old)")
    p.add_argument("--out")
    p.add_argument("--json")
    args = p.parse_args()
    res = run(args.stale)
    text = report(res)
    if args.json:
        with open(args.json, "w") as f:
            json.dump(res, f, indent=1)
    if args.out:
        with open(args.out, "w") as f:
            f.write(text)
    print(text)


if __name__ == "__main__":
    main()
