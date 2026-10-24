"""Check the evacuation order clock (#121) against the real 2018 Camp Fire.

For each town, NIST TN 2135's earliest observation inside it is when the
fire really got there. With the clock's own time to empty the town (nobody
else ordered), that gives the latest order that would really have got the
last car out: real arrival minus required time.

The replay then does what the live engine does: ignite at the NIST origin,
run the fire under the day's wind, and every --every minutes make a long
forecast (32 rollouts to T+600, under the wind at that moment) and run the
clock. It reports the clock's order-by time from its first forecast, and the
first forecast at which it said to order each town (order soon, order now or
late), next to the real deadline.

    cd engine && uv run python -m eval.evac_clock
"""

import argparse
import math

import numpy as np

from eval.campfire import load_truth, wind_at
from forecast.rollout import rollout
from forecast.runner import EVAC_HORIZON_MIN, EVAC_ROLLOUTS
from protocol import EvacStatus
from routing.clearance import compute_clock
from routing.roads import load_network
from scenario import load_scenario
from sim.fire import SIM_MINUTES_PER_TICK, FireSim

DUE = (EvacStatus.ORDER_SOON, EvacStatus.ORDER_NOW, EvacStatus.LATE)


def real_arrivals(net, hours: float) -> dict[str, float]:
    """Minutes after ignition of the earliest NIST observation in each town's disk."""
    cells, times, *_ = load_truth(hours)
    out = {}
    for t in net.towns:
        inside = np.hypot(cells[:, 1] + 0.5 - t.x, cells[:, 0] + 0.5 - t.y) <= t.radius
        out[t.name] = float(times[inside].min()) if inside.any() else math.inf
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--wind", type=float, default=19.0, help="m/s, the morning run")
    p.add_argument("--wind-after", type=float, default=6.0)
    p.add_argument("--wind-from", type=float, default=65.0)
    p.add_argument("--every", type=int, default=15, help="sim minutes between forecasts")
    p.add_argument("--until", type=int, default=120, help="sim minutes to replay")
    args = p.parse_args()

    scen = load_scenario("paradise")
    net = load_network(scen.dir, scen.width, scen.height)
    real = real_arrivals(net, 12)
    *_, origin, _, _, _ = load_truth(12)
    sim = FireSim(scen, seed=0)
    sim.ignite(*origin, radius=2)
    mpt = SIM_MINUTES_PER_TICK

    first_said: dict[str, float] = {}
    first_clock = None
    for minute in range(0, args.until + 1, args.every):
        while sim.tick * mpt < minute:
            sim.set_wind(wind_at(sim.tick * mpt, args.wind, args.wind_after, args.wind_from))
            sim.step()
        sim.set_wind(wind_at(minute, args.wind, args.wind_after, args.wind_from))
        fb = rollout(sim.snapshot(), EVAC_ROLLOUTS, int(EVAC_HORIZON_MIN / mpt), seed=minute)
        clocks = compute_clock(net, fb, tick=sim.tick, forecast_tick=sim.tick, horizon_min=EVAC_HORIZON_MIN,
                               orders={}, evacuated=[0.0] * len(net.towns), minutes_per_tick=mpt)
        first_clock = first_clock or clocks
        for c in clocks:
            if c.status in DUE and c.town not in first_said:
                first_said[c.town] = minute
        print(f"T+{minute:3d}: " + ", ".join(f"{c.town} {c.status}" for c in clocks), flush=True)

    print("\nminutes after ignition    real fire  needs   real deadline  clock order-by (T+0)  clock first said order")
    for c in first_clock:
        need = c.mobilize_min + c.clearance_min
        deadline = real[c.town] - need
        ob = "-" if c.order_by_tick is None else f"{c.order_by_tick * mpt:.0f}" + ("+" if c.order_by_bound else "")
        said = first_said.get(c.town)
        print(f"{c.town:24s} {real[c.town]:9.0f} {need:6.0f} {deadline:15.0f} {ob:>21s} "
              f"{'-' if said is None else f'T+{said}':>23s}")


if __name__ == "__main__":
    main()
