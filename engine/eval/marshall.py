"""Replay the 2021 Marshall Fire and score the fire model against its
perimeters (#107), the second real fire after the Camp Fire (eval.campfire).

Truth (assets/scenarios/marshall/real/, from tools/marshall_to_assets.py):
- NASA FEDS VIIRS perimeter at 2.5 h after ignition (the ~13:30 pass);
- the WFIGS final perimeter, at 14.5 h, by when the fire had stopped growing.
There are no timed per-house observations, so only the origin is an
observation and the scores are the perimeters' IoU and area ratio.

The wind is either the measured record (--measured: NCAR Mesa Lab's 5-min
wind in the foothills upwind, gusts to 40 m/s, from tools/marshall_to_assets.py)
or, by default, a simplified day: a strong, steady westerly downslope wind from
ignition through the afternoon, easing after dusk.
Grass and suburb, very different fuel from the Camp Fire's forest, so the two
fires together test C2 and spotting better than either alone.

    cd engine && uv run python -m eval.marshall                       # current constants
    cd engine && uv run python -m eval.marshall --search              # grid search
    cd engine && uv run python -m eval.marshall --measured --search   # the same, under the measured wind
"""

import argparse
import functools
import itertools
import json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

import sim.fire as fire
from eval.campfire import load_truth, objective, replay, score
from scenario import load_scenario
from sim.fire import Wind

WIND = Path(__file__).resolve().parents[2] / "assets" / "scenarios" / "marshall" / "real" / "marshall_wind.json"


def wind_at(t_min: float, day: float, night: float, from_deg: float) -> Wind:
    """Steady at `day` through the afternoon run, easing to `night` between
    6 h and 8 h after ignition (17:00-19:00), as the downslope event ended."""
    k = min(max((t_min - 360) / 120, 0.0), 1.0)
    return Wind(day + (night - day) * k, from_deg)


def measured_wind(scale: float = 1.0):
    """Mesa Lab's measured wind as wind_fn(minutes since ignition), held
    between 5-min readings. `scale` maps the station's 10 m mean onto the
    sim's wind, which stands for the wind at the fire."""
    w = json.loads(WIND.read_text())
    t = np.asarray(w["t_min"])
    speed, from_deg = w["speed_ms"], w["from_deg"]

    def at(t_min: float) -> Wind:
        i = max(int(np.searchsorted(t, t_min, side="right")) - 1, 0)
        return Wind(speed[i] * scale, from_deg[i])

    return at


def _trial(params: dict, hours: float, rollouts: int, defaults: dict) -> dict:
    """One replay with these settings (upper-case keys are sim.fire constants)."""
    for k, v in params.items():
        if k.isupper():
            setattr(fire, k, v)  # FireSim bakes P_H and SLOPE_A into its layers when built
    p = {**defaults, **params}
    scen = load_scenario("marshall")
    cells, times, origin, masks, mask_t, _ = load_truth(hours, "marshall", "marshall")
    wind_fn = (measured_wind(p["wind_scale"]) if p["measured"]
               else lambda t: wind_at(t, p["wind"], p["wind_after"], p["wind_from"]))
    first = replay(scen, origin, wind_fn, int(hours * 60 / fire.SIM_MINUTES_PER_TICK), rollouts)
    res = {**params, **score(first, cells, times, masks, mask_t)}
    res["objective"] = round(objective(res), 3)
    return res


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--hours", type=float, default=14.5, help="perimeters up to this many hours")
    p.add_argument("--wind", type=float, default=20.0, help="m/s, the afternoon run")
    p.add_argument("--wind-after", type=float, default=5.0, help="m/s, from ~8 h after ignition")
    p.add_argument("--wind-from", type=float, default=265.0, help="degrees, W to WSW")
    p.add_argument("--measured", action="store_true", help="play the measured wind (Mesa Lab) instead of the profile")
    p.add_argument("--wind-scale", type=float, default=1.0, help="with --measured: multiply the measured speed")
    p.add_argument("--workers", type=int, default=11)
    p.add_argument("--rollouts", type=int, default=8)
    p.add_argument("--search", action="store_true", help="grid search C2, spotting and the wind")
    p.add_argument("--json", help="write results here")
    args = p.parse_args()
    _, _, _, _, _, sources = load_truth(args.hours, "marshall", "marshall")
    base = {k: getattr(fire, k) for k in ("P_H", "C1", "C2", "SLOPE_A", "SPOT_RATE", "SPOT_MEAN")}
    print(f"perimeters: {list(sources)}")
    grid = [dict(base)]
    if args.search and args.measured:
        # The direction and timing are measured; only how the station's speed
        # maps onto the fire's is left free.
        grid = [dict(C2=c2, SPOT_RATE=sr, SPOT_MEAN=sm, wind_scale=k)
                for c2, sr, sm, k in itertools.product(
                    (0.22, 0.30, 0.40), (0.0, 0.002, 0.005, 0.01), (6.0, 12.0, 20.0), (0.8, 1.0, 1.25))]
    elif args.search:
        # The same C2 and spotting values eval.campfire searches, so the two fires compare.
        grid = [dict(C2=c2, SPOT_RATE=sr, SPOT_MEAN=sm, wind=ws, wind_from=wd)
                for c2, sr, sm, ws, wd in itertools.product(
                    (0.22, 0.30, 0.40), (0.0, 0.002, 0.005, 0.01), (6.0, 12.0, 20.0),
                    (15.0, 20.0, 25.0), (255.0, 270.0))]
    rows = []
    job = functools.partial(_trial, hours=args.hours, rollouts=args.rollouts, defaults=dict(
        wind=args.wind, wind_after=args.wind_after, wind_from=args.wind_from,
        measured=args.measured, wind_scale=args.wind_scale))
    with ProcessPoolExecutor(args.workers) as pool:
        for res in pool.map(job, grid, chunksize=4):
            rows.append(res)
            print(json.dumps(res), flush=True)
    if args.search:
        print("best by objective (outline and area mismatch with the perimeters):")
        for r in sorted(rows, key=objective)[:8]:
            print(json.dumps(r))
    if args.json:
        Path(args.json).write_text(json.dumps(rows, indent=1))


if __name__ == "__main__":
    main()
