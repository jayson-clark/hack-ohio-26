"""Does dropping crews on a fresh ignition still contain it? (#104)

Three crews ordered onto each eval ignition the moment it starts, at several
wind speeds, compared with no crews, over paired seeds:

- instant: the crews act from the first tick (the old exploit),
- dispatched: they drive from the nearest real stations first (sim/dispatch.py).

Reports acres burned at the end and the share of fires out by then.
`--no-hold` turns off the head-fire rule (sim.fire.HOLD_P) for a before/after.

    cd engine && uv run python -m eval.early_attack            # ~1 min
    cd engine && uv run python -m eval.early_attack --no-hold
"""

import argparse
import json
import math

import numpy as np

import sim.fire as fire
from eval.run import IGNITIONS
from protocol import Token, TokenSource, TokenType
from routing.roads import load_network
from routing.units import Station, UnitRouter
from scenario import load_scenario
from sim.dispatch import Dispatcher
from sim.effects import TokenEffects
from sim.fire import FireSim, Wind

SQ_M_PER_ACRE = 4046.86


def crews_at(x: float, y: float, k: int = 3, r: float = 4.0) -> list[Token]:
    return [
        Token(id=f"c{i}", token_type=TokenType.CREW, x=x + r * math.cos(2 * math.pi * i / k),
              y=y + r * math.sin(2 * math.pi * i / k), angle=0.0, source=TokenSource.VIRTUAL)
        for i in range(k)
    ]


def episode(scen, router, stations, ign, wind, policy, seed, ticks) -> tuple[float, bool]:
    sim = FireSim(scen, seed=seed)
    sim.set_wind(wind)
    sim.ignite(*ign, radius=2)
    effects = TokenEffects(scen.width, scen.height)
    effects.set_wind(wind.from_deg)
    tokens = [] if policy == "none" else crews_at(*ign)
    disp = Dispatcher(stations if policy == "dispatched" else [], router)
    for t in range(ticks):
        acting = disp.update(tokens, t, wind.speed_ms, None)
        sim.set_suppression(effects.update(acting, t))
        sim.step()
    burning, burned = sim.counts()
    acres = (burning + burned) * scen.cell_size_m**2 / SQ_M_PER_ACRE
    return acres, burning == 0


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--scenario", default="paradise")
    p.add_argument("--winds", default="3,8,13")
    p.add_argument("--seeds", type=int, default=3)
    p.add_argument("--ticks", type=int, default=180, help="sim minutes per fire")
    p.add_argument("--no-hold", action="store_true", help="crews hold head fire as well as flanks (before)")
    p.add_argument("--json", help="write the table as JSON here")
    args = p.parse_args()
    if args.no_hold:
        fire.HOLD_P = math.inf
    scen = load_scenario(args.scenario)
    net = load_network(scen.dir, scen.width, scen.height)
    stations = [Station(**s) for s in json.loads((scen.dir / "stations.json").read_text())["stations"]]
    router = UnitRouter(net, scen.cell_size_m)
    rows = []
    print(f"{'wind':>6} {'policy':>11} {'acres':>8} {'out by end':>11}")
    for ws in (float(w) for w in args.winds.split(",")):
        wind = Wind(ws, 45.0)
        for policy in ("none", "instant", "dispatched"):
            res = [episode(scen, router, stations, ign, wind, policy, s, args.ticks)
                   for ign in IGNITIONS for s in range(args.seeds)]
            acres = float(np.mean([a for a, _ in res]))
            out = float(np.mean([o for _, o in res]))
            rows.append({"wind_ms": ws, "policy": policy, "acres": round(acres), "out": round(out, 2), "n": len(res)})
            print(f"{ws:>4.0f}ms {policy:>11} {acres:>8.0f} {out:>10.0%}")
    if args.json:
        with open(args.json, "w") as f:
            json.dump({"hold_p": None if args.no_hold else fire.HOLD_P, "ticks": args.ticks, "rows": rows}, f, indent=2)


if __name__ == "__main__":
    main()
