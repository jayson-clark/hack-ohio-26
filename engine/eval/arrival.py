"""Do the calibrated time-to-impact ranges hold? (#13)

Headless Paradise episodes under the eval wind schedules (steady, shift,
gusty). Every EVERY minutes a forecast of HORIZON_MIN gives each threatened
town a raw 5-95% arrival range; the online calibrator (uq.conformal
ArrivalCalibrator, learning from sampled cells, carried across a schedule's
episodes) widens or narrows it. When the fire really reaches the town, or the
forecast runs out, both ranges are scored. Target: about 90% of towns' real
arrivals inside the calibrated range.

    cd engine && uv run python -m eval.arrival            # ~10 min
    cd engine && uv run python -m eval.arrival --episodes 2 --schedules shift
"""

import argparse
import json

import numpy as np

from eval.run import IGNITIONS, schedule
from forecast.recommend import TownInfo
from forecast.rollout import WindSpread, rollout
from routing.roads import load_network
from scenario import load_scenario
from sim.fire import BURNING, SIM_MINUTES_PER_TICK, FireSim
from uq.conformal import ArrivalCalibrator, arrival_quantiles, bucket_of

HORIZON_MIN = 240  # the engine's long forecast runs 600; shorter keeps this quick
EVERY = 20
TICKS = 360
N = 32


def town_masks(towns, h, w):
    cy, cx = np.mgrid[:h, :w].astype(np.float32) + 0.5
    return np.stack([np.hypot(cx - t.x, cy - t.y) <= t.radius for t in towns])


def episode(scen, towns, masks, sched: str, seed: int, cal: ArrivalCalibrator, rows: list,
            spread: WindSpread | None = None) -> None:
    wind_at = schedule(sched, seed)
    sim = FireSim(scen, seed=seed)
    sim.set_wind(wind_at(0))
    sim.ignite(*IGNITIONS[seed % len(IGNITIONS)], radius=2)
    burn_tick = np.full(sim.state.shape, np.inf, np.float32)
    burn_tick[sim.state >= BURNING] = 0
    preds = []  # (issue tick, town index, raw lo, raw hi, cal lo, cal hi, bucket)
    horizon = int(HORIZON_MIN / SIM_MINUTES_PER_TICK)
    for tick in range(TICKS + horizon + 1):
        if tick <= TICKS and tick % EVERY == 0 and (sim.state == BURNING).any():
            snap = sim.snapshot()
            fb = rollout(snap, N, horizon, seed=seed * 1000 + tick, wind_spread=spread)
            cal.issue(tick, fb, fb[0] != 0, SIM_MINUTES_PER_TICK, horizon)
            for i, m in enumerate(masks):
                if (burn_tick[m] <= tick).any():
                    continue  # already reached
                a = fb.reshape(N, -1)[:, m.ravel()].min(axis=1) * SIM_MINUTES_PER_TICK
                lo, med, hi = arrival_quantiles(a)
                if not np.isfinite(hi):
                    continue  # too few simulations reach it to bound the range
                clo, chi = cal.interval(float(lo), float(med), float(hi))
                preds.append((tick, i, float(lo), float(hi), clo, chi, bucket_of(float(med))))
        sim.set_wind(wind_at(tick))
        sim.step()
        lit = sim.state >= BURNING
        burn_tick[lit & np.isinf(burn_tick)] = sim.tick
        cal.mature(sim.tick, burn_tick, SIM_MINUTES_PER_TICK)
        if not (sim.state == BURNING).any() and tick > TICKS:
            break
    final = sim.tick
    for issue, i, lo, hi, clo, chi, b in preds:
        reach = burn_tick[masks[i]].min()
        if np.isfinite(reach):
            y = (reach - issue) * SIM_MINUTES_PER_TICK
        elif final - issue >= horizon:
            y = np.inf  # never reached within the forecast: later than any finite range
        else:
            continue  # unresolved
        rows.append({"schedule": sched, "town": towns[i].name, "bucket": b, "y": float(y),
                     "raw": bool(lo <= y <= hi), "cal": bool(clo <= y <= chi),
                     "raw_width": hi - lo, "cal_width": chi - clo})
    cal.clear_pending()


def summarize(rows: list, cals: dict) -> dict:
    out = {}
    for sched in sorted({r["schedule"] for r in rows}):
        sub = [r for r in rows if r["schedule"] == sched]
        c = cals[sched]
        out[sched] = {
            "town_ranges": len(sub),
            "raw_coverage": round(float(np.mean([r["raw"] for r in sub])), 3),
            "cal_coverage": round(float(np.mean([r["cal"] for r in sub])), 3),
            "raw_median_width_min": round(float(np.median([r["raw_width"] for r in sub])), 1),
            "cal_median_width_min": round(float(np.median([r["cal_width"] for r in sub])), 1),
            "by_bucket": {
                b: {"n": sum(r["bucket"] == b for r in sub),
                    "raw": round(float(np.mean([r["raw"] for r in sub if r["bucket"] == b] or [np.nan])), 3),
                    "cal": round(float(np.mean([r["cal"] for r in sub if r["bucket"] == b] or [np.nan])), 3),
                    "correction_min": round(c.buckets[b].q, 1),
                    "cells_scored": c.buckets[b].scored,
                    "cell_miss_rate": round(c.buckets[b].misses / max(c.buckets[b].scored, 1), 3)}
                for b in range(len(c.buckets))
            },
            "cells_censored": c.censored,
        }
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--schedules", default="steady,shift,gusty")
    p.add_argument("--episodes", type=int, default=4)
    p.add_argument("--json", help="write the summary here")
    p.add_argument("--wind-spread", help="speed_frac,dir_deg: per-rollout wind variation in the forecasts (off by default)")
    args = p.parse_args()
    scen = load_scenario("paradise")
    net = load_network(scen.dir, scen.width, scen.height)
    towns = [TownInfo(t.name, t.x, t.y, t.radius, t.population) for t in net.towns]
    masks = town_masks(towns, scen.height, scen.width)
    spread = None
    if args.wind_spread:
        sf, dd = (float(v) for v in args.wind_spread.split(","))
        spread = WindSpread(speed_frac=sf, dir_deg=dd)
    rows, cals = [], {}
    for sched in args.schedules.split(","):
        cals[sched] = ArrivalCalibrator(scen.cell_size_m)
        for seed in range(args.episodes):
            episode(scen, towns, masks, sched, seed, cals[sched], rows, spread)
            print(f"{sched} episode {seed} done, {len(rows)} town ranges so far", flush=True)
    out = summarize(rows, cals)
    print(json.dumps(out, indent=1))
    if args.json:
        with open(args.json, "w") as f:
            json.dump(out, f, indent=1)


if __name__ == "__main__":
    main()
