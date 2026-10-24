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
"""

import argparse
import glob
import json
import time

import numpy as np

from emulator import features as F
from emulator.data import _scenario, load
from emulator.model import load_emulator
from sim.fire import Wind

BINS = [0, 0.1, 0.25, 0.5, 0.75, 0.9, 1.0001]


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--test", default="emulator/data/test")
    p.add_argument("--json", help="write the results here")
    args = p.parse_args()
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
    print(json.dumps(out, indent=2))
    if args.json:
        with open(args.json, "w") as f:
            json.dump(out, f, indent=2)


if __name__ == "__main__":
    main()
