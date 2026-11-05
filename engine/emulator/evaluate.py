"""How good and how fast is the fire emulator? (#113)

    cd engine && uv run --extra ml python -m emulator.evaluate

On held-out samples (emulator.data --with-32), each labelled with a
64-rollout forecast, it compares the emulator with a 32-rollout forecast
(what the engine shows today) on the cells either has to predict:

- Brier score against the 64-rollout label (lower is better). The 32-run
  forecast's own sampling noise sets the bar.
- Calibration: of cells predicted at p, how much of the label's
  probability they actually got.
- Overlap (IoU) of the 50% and 90% areas with the label's.
- Speed: one forecast, and a batch of 100 (crew-spot screening), vs
  run_forecast's 32 rollouts.

--compare (#229) instead scores four predictors on an emulator.data
--wind-aware --with-32 test set, against both targets (the 64-rollout
label under future-wind scenarios, and the constant-wind label of the same
fire and constants): the original emulator, the wind-aware one (given the
label's wind uncertainty as input), and the engine's 32-rollout forecast with
constant wind and with wind scenarios. Split by whether the sample's label
had any wind uncertainty.

    cd engine && uv run --extra ml python -m emulator.evaluate --compare --test emulator/data/test_wind
"""

import argparse
import glob
import json
import time

import numpy as np

from emulator import features as F
from emulator.data import _scenario, load
from emulator.model import WEIGHTS, WIND_WEIGHTS, Emulator, load_emulator
from sim.fire import Wind

BINS = [0, 0.1, 0.25, 0.5, 0.75, 0.9, 1.0001]


def _bins(p, y):
    idx = np.digitize(p, BINS) - 1
    n = np.bincount(idx, minlength=len(BINS) - 1)
    sp = np.bincount(idx, weights=p, minlength=len(BINS) - 1)
    sy = np.bincount(idx, weights=y, minlength=len(BINS) - 1)
    return n, sp, sy


def compare(rows: list[dict], weights=(WEIGHTS, WIND_WEIGHTS)) -> dict:
    """Brier, calibration (expected calibration error over BINS) and IoU of
    the 50% area for each predictor against each target, on open cells."""
    emus = {"original emulator": Emulator(weights[0]), "wind-aware emulator": Emulator(weights[1])}
    names = list(emus) + ["MC 32, constant wind", "MC 32, wind scenarios"]
    targets = ("label", "label_const")
    groups = ("all", "with wind uncertainty", "constant-wind label")
    acc = {(g, t, k): {"se": 0.0, "n": 0.0, "i": 0.0, "u": 0.0, "bins": None} for g in groups for t in targets for k in names}
    times = {k: [] for k in emus}
    for r in rows:
        _, layers = _scenario(r["scenario"])
        wind = Wind(*map(float, r["wind"]))
        _, open_ = F.masks(r["state"])
        preds = {}
        for k, emu in emus.items():
            x = F.inputs(r["state"], r["burn_left"], layers.spread, wind, r["sup"] / 255.0,
                         r["wind_model"] if emu.wind_aware else None)
            t = time.perf_counter()
            preds[k] = F.finish(emu.predict(x[None])[0], r["state"])
            times[k].append(time.perf_counter() - t)
        preds["MC 32, constant wind"] = r["p32"] / 255.0
        preds["MC 32, wind scenarios"] = r["p32_wind"] / 255.0
        g2 = "with wind uncertainty" if np.any(r["wind_model"] > 0) else "constant-wind label"
        for t in targets:
            y = r[t] / 255.0
            for k, pk in preds.items():
                a, b = pk[open_], y[open_]
                for g in ("all", g2):
                    c = acc[(g, t, k)]
                    c["se"] += float(((a - b) ** 2).sum())
                    c["n"] += len(a)
                    c["i"] += float(((a >= 0.5) & (b >= 0.5)).sum())
                    c["u"] += float(((a >= 0.5) | (b >= 0.5)).sum())
                    n, sp, sy = _bins(a, b)
                    c["bins"] = (n, sp, sy) if c["bins"] is None else tuple(x + z for x, z in zip(c["bins"], (n, sp, sy)))
    out = {"test_samples": len(rows), "results": []}
    for (g, t, k), c in acc.items():
        if not c["n"]:
            continue
        n, sp, sy = c["bins"]
        ece = float(np.abs(sp - sy).sum() / n.sum())
        out["results"].append({"group": g, "target": "wind-scenario label" if t == "label" else "constant-wind label",
                               "predictor": k, "brier": round(c["se"] / c["n"], 5), "ece": round(ece, 4),
                               "iou_50": round(c["i"] / max(c["u"], 1), 3),
                               })
    out["emulator_ms"] = {k: round(1000 * float(np.median(v[1:] or v)), 1) for k, v in times.items()}
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--test", default="emulator/data/test")
    p.add_argument("--json", help="write the results here")
    p.add_argument("--device", default="auto", choices=("auto", "gpu", "cpu"))
    p.add_argument("--compare", action="store_true", help="four predictors vs both targets on a --wind-aware test set")
    args = p.parse_args()
    try:  # MLX on a Mac; elsewhere the emulator runs on PyTorch (emulator.model.Emulator)
        from emulator import device as D

        dev = D.select(args.device)
    except ImportError:
        from emulator import torch_model as T

        dev = T.describe(T.device(args.device))
    if args.compare:
        out = compare(load(sorted(glob.glob(f"{args.test}/*.npz"))))
        out["device"] = dev
        print(json.dumps(out, indent=2))
        if args.json:
            with open(args.json, "w") as f:
                json.dump(out, f, indent=2)
        return
    emu = load_emulator()
    if emu is None:
        raise SystemExit("no emulator: install the ml extra and train weights first")
    rows = load(sorted(glob.glob(f"{args.test}/*.npz")))
    se = {"emulator": 0.0, "32_rollouts": 0.0}
    cells = 0.0
    inter = {k: np.zeros(2) for k in se}
    union = {k: np.zeros(2) for k in se}
    cal_p, cal_y, cal_n = np.zeros(len(BINS) - 1), np.zeros(len(BINS) - 1), np.zeros(len(BINS) - 1)
    for r in rows:
        _, layers = _scenario(r["scenario"])
        x = F.inputs(r["state"], r["burn_left"], layers.spread, Wind(*map(float, r["wind"])), r["sup"] / 255.0)
        pe = F.finish(emu.predict(x[None])[0], r["state"])
        y = r["label"] / 255.0
        _, open_ = F.masks(r["state"])
        preds = {"emulator": pe, "32_rollouts": r["p32"] / 255.0}
        for k, pk in preds.items():
            se[k] += float(((pk - y) ** 2)[open_].sum())
            for j, lvl in enumerate((0.5, 0.9)):
                a, b = (pk >= lvl) & open_, (y >= lvl) & open_
                inter[k][j] += (a & b).sum()
                union[k][j] += (a | b).sum()
        cells += float(open_.sum())
        idx = np.digitize(pe[open_], BINS) - 1
        np.add.at(cal_p, idx, pe[open_])
        np.add.at(cal_y, idx, y[open_])
        np.add.at(cal_n, idx, 1)
    out = {
        "test_samples": len(rows),
        "brier": {k: round(v / cells, 5) for k, v in se.items()},
        "iou_50": {k: round(float(inter[k][0] / max(union[k][0], 1)), 3) for k in se},
        "iou_90": {k: round(float(inter[k][1] / max(union[k][1], 1)), 3) for k in se},
        "calibration": [
            {"bin": f"{BINS[i]:.2f}-{min(BINS[i + 1], 1):.2f}", "mean_pred": round(float(cal_p[i] / cal_n[i]), 3),
             "mean_label": round(float(cal_y[i] / cal_n[i]), 3), "cells": int(cal_n[i])}
            for i in range(len(cal_n)) if cal_n[i]
        ],
    }
    # Speed on the full Paradise map.
    r = next(r for r in rows if r["scenario"] == "paradise")
    _, layers = _scenario("paradise")
    x = F.inputs(r["state"], r["burn_left"], layers.spread, Wind(*map(float, r["wind"])), r["sup"] / 255.0)
    emu.predict(x[None])
    t = time.perf_counter()
    for _ in range(10):
        emu.predict(x[None])
    one = (time.perf_counter() - t) / 10
    batch = np.repeat(x[None], 100, axis=0)
    emu.predict(batch[:8])
    t = time.perf_counter()
    for i in range(0, 100, 25):
        emu.predict(batch[i : i + 25])
    hundred = time.perf_counter() - t
    out["speed_s"] = {"one_forecast": round(one, 4), "100_variants": round(hundred, 3)}
    out["device"] = dev
    print(json.dumps(out, indent=2))
    if args.json:
        with open(args.json, "w") as f:
            json.dump(out, f, indent=2)


if __name__ == "__main__":
    main()
