"""Print how far the fire spreads under a few winds, for tuning sim/fire.py.

Run from engine/: `uv run python -m sim.tune [--ticks 100] [--seeds 4]`.
Override constants to try them without editing fire.py, e.g.
`uv run python -m sim.tune P_H=0.1 C1=0.12`.
"""

import argparse
from dataclasses import replace

import numpy as np

import sim.fire as fire
from scenario import load_scenario


def spread(scenario, wind, seed, ticks, at=(128, 96)):
    s = fire.FireSim(scenario, seed=seed)
    s.set_wind(wind)
    s.ignite(*at)
    for _ in range(ticks):
        s.step()
    ys, xs = np.nonzero(s.state >= fire.BURNING)
    alive = s.counts()[0] > 0
    return at[0] - xs.min(), xs.max() - at[0], (ys.max() - ys.min()) / 2, alive


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("overrides", nargs="*", help="NAME=value for constants in sim/fire.py")
    ap.add_argument("--ticks", type=int, default=100)
    ap.add_argument("--seeds", type=int, default=4)
    ap.add_argument("--scenario", default="paradise")
    args = ap.parse_args()
    for o in args.overrides:
        name, value = o.split("=")
        setattr(fire, name, float(value) if "." in value else int(value))

    sc = load_scenario(args.scenario)
    flat = replace(sc, heightmap=np.zeros_like(sc.heightmap))
    print(f"cells spread from a centre ignition after {args.ticks} ticks, west wind, mean of {args.seeds} seeds")
    for terrain, label in [(flat, "flat"), (sc, args.scenario)]:
        for v in (0, 4, 8, 15):
            r = [spread(terrain, fire.Wind(v, 270), seed, args.ticks) for seed in range(args.seeds)]
            up, down, flank = (np.mean([x[i] for x in r]) for i in range(3))
            alive = sum(x[3] for x in r)
            print(
                f"  {label:>9} {v:2d} m/s  upwind {up:5.1f}  downwind {down:5.1f}"
                f"  flank {flank:5.1f}  still burning {alive}/{args.seeds}"
            )


if __name__ == "__main__":
    main()
