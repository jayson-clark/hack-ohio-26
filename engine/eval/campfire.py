"""Replay the 2018 Camp Fire and score the fire model against what really
happened (#15).

Truth (assets/scenarios/paradise/real/, from tools/campfire_to_assets.py):
- NIST TN 2135 observations: "fire was here at local time t". The earliest
  one per cell is an upper bound on when fire reached it.
- NIFC and NASA FEDS perimeters at 7.1 h and 11.5 h after ignition.

The replay ignites at the NIST origin near Pulga under a steady wind (the
morning's NE Jarbo Gap wind) and runs N rollouts. Scores:
- arrival error: per observed cell, the median simulated arrival minus the
  observed time, for observations in the first `--hours` (positive means the
  sim is late);
- reached: the share of observed cells the sim burns within 30 min of the
  observation;
- IoU of the sim's 50% burned area with each perimeter, on the map.

    cd engine && uv run python -m eval.campfire                       # current constants
    cd engine && uv run python -m eval.campfire --search              # grid search
"""

import argparse
import functools
import itertools
import json
import math
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

import sim.fire as fire
from scenario import load_scenario
from sim.fire import FireSim, Wind

REAL = Path(__file__).resolve().parents[2] / "assets" / "scenarios" / "paradise" / "real"
TOLERANCE_MIN = 30
HORIZON_CAP_MIN = 720  # a never-reached observation is late by this minus its time


def load_truth(hours: float):
    obs = json.loads((REAL / "campfire_observations.json").read_text())["observations"]
    p = np.load(REAL / "campfire_perimeters.npz")
    first: dict[tuple[int, int], float] = {}
    for o in obs:
        if o["t_min"] > hours * 60 or o["residual"]:
            continue
        cell = (int(o["y"]), int(o["x"]))
        first[cell] = min(first.get(cell, math.inf), o["t_min"])
    cells = np.array(list(first), int)
    times = np.array(list(first.values()), float)
    origin = next(o for o in obs if o["t_min"] == 0)
    keep = p["t_min"] <= hours * 60
    return cells, times, (origin["x"], origin["y"]), p["masks"][keep], p["t_min"][keep], p["source"][keep]


def wind_at(t_min: float, morning: float, afternoon: float, from_deg: float) -> Wind:
    """The day's wind, simplified: strong NE Jarbo Gap wind through the
    morning run, easing to `afternoon` between 4 h and 7 h after ignition
    (10:25-13:25), as the downslope event died down."""
    k = min(max((t_min - 240) / 180, 0.0), 1.0)
    return Wind(morning + (afternoon - morning) * k, from_deg)


def replay(scen, origin, wind_fn, ticks: int, n: int, seed: int = 0) -> np.ndarray:
    """First-burn tick per rollout, float32 (n, H, W), under a wind that
    changes over time (wind_fn(minutes since ignition) -> Wind)."""
    sim = FireSim(scen, seed=seed)
    sim.ignite(*origin, radius=2)
    snap = sim.snapshot()
    state = np.repeat(snap.state[None], n, axis=0)
    left = np.repeat(snap.burn_left[None], n, axis=0)
    first = np.where(state >= fire.BURNING, 0.0, np.inf).astype(np.float32)
    rng = np.random.default_rng(seed)
    sup = np.zeros(snap.state.shape, np.float32)
    for t in range(1, ticks + 1):
        r = fire.advance(state, left, snap.layers, wind_fn((t - 1) * fire.SIM_MINUTES_PER_TICK), sup, rng)
        if r is None:
            break
        ign, y0, x0, spots = r
        crop = first[:, y0 : y0 + ign.shape[1], x0 : x0 + ign.shape[2]]
        crop[ign] = t
        if spots is not None:
            first[spots] = np.minimum(first[spots], t)
    return first


def score(first: np.ndarray, cells, times, masks, mask_t) -> dict:
    arrival = np.median(first, axis=0)  # inf where most rollouts never reach it
    sim_t = arrival[cells[:, 0], cells[:, 1]] * fire.SIM_MINUTES_PER_TICK
    err = np.where(np.isfinite(sim_t), sim_t - times, np.nan)
    reached = np.isfinite(sim_t) & (sim_t <= times + TOLERANCE_MIN)
    # An observation says fire was there by then (often a house already
    # burning), so only lateness is a proven error; a cell never reached
    # counts as late by the rest of the replay.
    late = np.where(np.isfinite(sim_t), np.maximum(sim_t - times, 0.0), HORIZON_CAP_MIN - times)
    out = {
        "obs_cells": int(len(times)),
        "late_median_min": round(float(np.median(late)), 1),
        "late_p75_min": round(float(np.percentile(late, 75)), 1),
        "reached": round(float(reached.mean()), 3),
        "arrival_err_median_min": None if np.isnan(err).all() else round(float(np.nanmedian(err)), 1),
        "arrival_err_mae_min": None if np.isnan(err).all() else round(float(np.nanmedian(np.abs(err))), 1),
        "never_reached": int(np.isnan(err).sum()),
    }
    for m, t in zip(masks, mask_t):
        burned = (np.isfinite(first) & (first <= t / fire.SIM_MINUTES_PER_TICK)).mean(axis=0) >= 0.5
        inter, union = (burned & m).sum(), (burned | m).sum()
        out[f"iou_{t / 60:.1f}h"] = round(float(inter / max(union, 1)), 3)
        out[f"area_ratio_{t / 60:.1f}h"] = round(float(burned.sum() / max(m.sum(), 1)), 2)
    return out


def objective(r: dict) -> float:
    """Lower is better, with three terms weighted equally:
    - how late the sim is at the observed cells (75th percentile, in hours);
    - outline mismatch with the perimeters (1 - IoU, x2);
    - area error (log of the area ratio).
    Being early isn't penalized directly, since observations are upper bounds,
    but burning too much shows up in the IoU and area terms."""
    ious = [v for k, v in r.items() if k.startswith("iou_")]
    areas = [abs(math.log(max(v, 1e-3))) for k, v in r.items() if k.startswith("area_ratio")]
    return r["late_p75_min"] / 60 + 2 * (1 - float(np.mean(ious))) + float(np.mean(areas))


def _trial(params: dict, hours: float, rollouts: int, defaults: dict) -> dict:
    """One replay with these settings (upper-case keys are sim.fire constants)."""
    for k, v in params.items():
        if k.isupper():
            setattr(fire, k, v)  # FireSim bakes P_H and SLOPE_A into its layers when built
    p = {**defaults, **params}
    scen = load_scenario("paradise")
    cells, times, origin, masks, mask_t, _ = load_truth(hours)
    first = replay(scen, origin, lambda t: wind_at(t, p["wind"], p["wind_after"], p["wind_from"]),
                   int(hours * 60 / fire.SIM_MINUTES_PER_TICK), rollouts)
    res = {**params, **score(first, cells, times, masks, mask_t)}
    res["objective"] = round(objective(res), 3)
    return res


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--hours", type=float, default=12.0, help="observations and perimeters up to this many hours")
    p.add_argument("--wind", type=float, default=19.0, help="m/s, the morning run")
    p.add_argument("--wind-after", type=float, default=6.0, help="m/s, from ~7 h after ignition")
    p.add_argument("--workers", type=int, default=11)
    p.add_argument("--wind-from", type=float, default=65.0, help="degrees, NE to ENE")
    p.add_argument("--rollouts", type=int, default=8)
    p.add_argument("--search", action="store_true", help="grid search P_H, C1, C2, SLOPE_A")
    p.add_argument("--json", help="write results here")
    args = p.parse_args()
    scen = load_scenario("paradise")
    cells, times, origin, masks, mask_t, sources = load_truth(args.hours)
    ticks = int(args.hours * 60 / fire.SIM_MINUTES_PER_TICK)
    wind = Wind(args.wind, args.wind_from)
    base = {k: getattr(fire, k) for k in ("P_H", "C1", "C2", "SLOPE_A", "SPOT_RATE", "SPOT_MEAN")}
    print(f"{len(times)} observed cells, perimeters: {list(sources)}")
    grid = [dict(base)]
    if args.search:
        grid = [dict(C2=c2, SPOT_RATE=sr, SPOT_MEAN=sm, wind=ws, wind_after=wa, wind_from=wd)
                for c2, sr, sm, ws, wa, wd in itertools.product(
                    (0.22, 0.30, 0.40), (0.0, 0.002, 0.005, 0.01), (6.0, 12.0, 20.0),
                    (13.0, 16.0, 19.0), (6.0, 9.0), (55.0, 65.0))]
    rows = []
    job = functools.partial(_trial, hours=args.hours, rollouts=args.rollouts, defaults=dict(
        wind=args.wind, wind_after=args.wind_after, wind_from=args.wind_from))
    with ProcessPoolExecutor(args.workers) as pool:
        for res in pool.map(job, grid, chunksize=4):
            rows.append(res)
            print(json.dumps(res), flush=True)
    if args.search:
        best = sorted(rows, key=objective)[:8]
        print("best by objective (late or missed observations, plus area mismatch):")
        for r in best:
            print(json.dumps(r))
    if args.json:
        Path(args.json).write_text(json.dumps(rows, indent=1))


if __name__ == "__main__":
    main()
