"""Training data for the fire emulator (#113): random fires on our own
scenarios, each labelled with a Monte Carlo forecast.

Each sample is a random situation:
- **map:** one of SCENARIOS (the real fires we ship);
- **fire:** one or two ignitions on fuel, burning for 5-200 ticks;
- **wind:** 0-15 m/s from any direction, sometimes shifting mid-run;
- **tokens:** up to 3 crews near the front (some still on their way, some dug
  in), maybe a firebreak and a wet patch.

It's labelled with run_forecast at LABEL_ROLLOUTS (more than the live 32,
so the labels are less noisy than what the engine shows). The label also
carries model uncertainty, since the fire model is only a fit to two real
fires: each sample's forecast uses its own wind steering (C2_RANGE) and spread
rate (P_H_SCALE), and each rollout its own wind (LABEL_WIND). The inputs stay
nominal, so the emulator learns a forecast that hedges over those errors
rather than copying one exact setting. The fire up to the snapshot runs at
the nominal constants.

    cd engine && uv run python -m emulator.data --samples 6000 --out emulator/data/train
    cd engine && uv run python -m emulator.data --samples 400 --out emulator/data/test --seed 1 --with-32

Shards are .npz files of compact arrays (uint8 grids). Inputs are rebuilt
from them at load time (features.inputs), so the format doesn't change when
the features do.
"""

import argparse
import math
import os
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from pathlib import Path

import numpy as np

from emulator.features import HORIZONS, SUP_TICKS
from forecast.rollout import WindSpread
from forecast.runner import run_forecast
from protocol import Token, TokenSource, TokenType
from scenario import load_scenario
from sim.effects import WATER_RADIUS, SuppressionSchedule, TimedLayer, TokenEffects, crew_layer, soft_disk
import sim.fire as fire_model
from sim.fire import BURNING, FUEL, FireSim, Wind

# Real scenarios only. Marshall's map is smaller and mostly grass and suburb.
SCENARIOS = {"paradise": 0.65, "marshall": 0.35}
LABEL_ROLLOUTS = 64
SHARD = 100  # samples per file
# Model uncertainty in the labels. The Camp Fire and Marshall replays fit C2
# between 0.22 and 0.4 (PLAN.md, "Choosing C2"); P_H is a guess of +/-15%.
C2_RANGE = (0.22, 0.4)
P_H_SCALE = (0.85, 1.15)
LABEL_WIND = WindSpread()  # each rollout's wind: +/-20% speed, +/-15 deg

_cache: dict = {}


def _scenario(name):
    if name not in _cache:
        scen = load_scenario(name)
        _cache[name] = (scen, FireSim(scen).layers)
    return _cache[name]


def _front(state: np.ndarray, rng) -> tuple[float, float] | None:
    ys, xs = np.nonzero(state == BURNING)
    if len(xs) == 0:
        return None
    i = rng.integers(len(xs))
    return float(xs[i]) + 0.5, float(ys[i]) + 0.5


def _schedule(state, w, h, rng, wind_from: float) -> SuppressionSchedule:
    """Random tokens around the fire: crews, a firebreak, a wet patch."""
    effects = TokenEffects(w, h)
    static = np.zeros((h, w), np.float32)
    layers: list[TimedLayer] = []
    for _ in range(rng.integers(0, 4)):
        spot = _front(state, rng)
        if spot is None:
            break
        ang, dist = rng.uniform(0, 2 * math.pi), rng.uniform(3, 25)
        x, y = spot[0] + dist * math.cos(ang), spot[1] + dist * math.sin(ang)
        if rng.random() < 0.5:  # still on its way
            layers.append(crew_layer(w, h, x, y, t_on=int(rng.integers(1, 40)), wind_from=wind_from))
        else:  # already digging in
            layers.append(crew_layer(w, h, x, y, ramped=float(rng.uniform(0, 1)), wind_from=wind_from))
    if rng.random() < 0.25 and (spot := _front(state, rng)) is not None:
        tok = Token(id="fb", token_type=TokenType.FIREBREAK, x=spot[0] + rng.uniform(-12, 12),
                    y=spot[1] + rng.uniform(-12, 12), angle=float(rng.uniform(0, math.pi)), source=TokenSource.VIRTUAL)
        np.maximum(static, effects._firebreak(tok), out=static)
    if rng.random() < 0.15 and (spot := _front(state, rng)) is not None:
        cy, cx = np.mgrid[:h, :w].astype(np.float32) + 0.5
        disk = soft_disk(np.hypot(cx - spot[0], cy - spot[1]), WATER_RADIUS).astype(np.float32)
        age = int(rng.integers(1, 30))
        layers.append(TimedLayer(disk, 0.8 * (1 - age / 30), -0.8 / 30, 0.8))
    return SuppressionSchedule(static, layers)


def sample(seed: int, with_32: bool = False) -> dict | None:
    rng = np.random.default_rng(seed)
    name = rng.choice(list(SCENARIOS), p=list(SCENARIOS.values()))
    scen, layers = _scenario(name)
    sim = FireSim(scen, seed=int(rng.integers(1 << 31)))
    sim.layers = layers
    sim.reset()
    wind = Wind(float(rng.uniform(0, 15)), float(rng.uniform(0, 360)))
    sim.set_wind(wind)
    fuel_cells = np.argwhere(sim.state == FUEL)
    for _ in range(rng.integers(1, 3)):
        y, x = fuel_cells[rng.integers(len(fuel_cells))]
        sim.ignite(x + 0.5, y + 0.5, radius=2)
    t0 = int(rng.integers(5, 200))
    shift = int(rng.integers(1, t0)) if rng.random() < 0.3 and t0 > 1 else None
    for t in range(t0):
        if t == shift:
            wind = Wind(float(rng.uniform(0, 15)), float(rng.uniform(0, 360)))
            sim.set_wind(wind)
        sim.step()
    if not (sim.state == BURNING).any():
        return None
    h, w = sim.state.shape
    sched = _schedule(sim.state, w, h, rng, wind.from_deg)
    snap = replace(sim.snapshot(), suppression=sched.at(0), schedule=sched)
    c2, ph = float(rng.uniform(*C2_RANGE)), float(rng.uniform(*P_H_SCALE))
    label = _label(snap, c2, ph, int(rng.integers(1 << 31)))
    out = {
        "scenario": name,
        "state": snap.state.astype(np.uint8),
        "burn_left": np.clip(snap.burn_left, 0, 255).astype(np.uint8),
        "wind": np.array([wind.speed_ms, wind.from_deg], np.float32),
        "sup": np.round(np.stack([sched.at(t) for t in SUP_TICKS]) * 255).astype(np.uint8),
        "label": np.round(label * 255).astype(np.uint8),
        "model": np.array([c2, ph], np.float32),  # the label's C2 and P_H scale
    }
    if with_32:  # what the live engine shows, to compare the emulator with
        out["p32"] = np.round(run_forecast(snap, seed=int(rng.integers(1 << 31))).probability * 255).astype(np.uint8)
    return out


def _label(snap, c2: float, ph: float, seed: int) -> np.ndarray:
    """The forecast under one draw of the model's constants (P_H scales the
    precomputed spread layers; C2 is read when wind factors are computed)."""
    noisy = replace(snap, layers=replace(snap.layers, spread=snap.layers.spread * np.float32(ph)))
    nominal = fire_model.C2
    fire_model.C2 = c2
    try:
        return run_forecast(noisy, n=LABEL_ROLLOUTS, seed=seed, wind_spread=LABEL_WIND).probability
    finally:
        fire_model.C2 = nominal


def _shard(args) -> str | None:
    out_dir, index, seeds, with_32 = args
    rows = [s for s in (sample(int(seed), with_32) for seed in seeds) if s is not None]
    if not rows:
        return None
    path = Path(out_dir) / f"shard-{index:04d}.npz"
    data = {"scenario": np.array([r["scenario"] for r in rows])}
    for key in rows[0]:
        if key == "scenario":
            continue
        # Different maps have different sizes, so grids are stored per sample.
        for i, r in enumerate(rows):
            data[f"{key}_{i}"] = r[key]
    np.savez_compressed(path, n=len(rows), **data)
    return str(path)


def load(paths) -> list[dict]:
    """Samples from shard files, as dicts of arrays."""
    out = []
    for p in paths:
        z = np.load(p)
        for i in range(int(z["n"])):
            row = {"scenario": str(z["scenario"][i])}
            for key in ("state", "burn_left", "wind", "sup", "label", "p32", "model"):
                if f"{key}_{i}" in z:
                    row[key] = z[f"{key}_{i}"]
            out.append(row)
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--samples", type=int, default=6000)
    p.add_argument("--out", default="emulator/data/train")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    p.add_argument("--with-32", action="store_true", help="also store a 32-rollout forecast (test sets)")
    args = p.parse_args()
    Path(args.out).mkdir(parents=True, exist_ok=True)
    seeds = np.random.default_rng(args.seed).integers(1 << 62, size=args.samples)
    jobs = [(args.out, i, seeds[j : j + SHARD], args.with_32) for i, j in enumerate(range(0, args.samples, SHARD))]
    done = 0
    with ProcessPoolExecutor(args.workers) as pool:
        for path in pool.map(_shard, jobs):
            done += 1
            print(f"{done}/{len(jobs)} {path}", flush=True)


if __name__ == "__main__":
    main()
