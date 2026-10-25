"""Plan what-ifs (#123): the operator's set of orders, against doing nothing.

One rollout_paired batch runs the fire as it is (baseline) and the fire with
every order in the plan acting from when its unit could get there, on the
same random draws and under the same assumed wind. So the difference is the
plan's effect, not luck. Runs in the Recommender worker, like the
commander's what-ifs.
"""

from dataclasses import dataclass

import numpy as np

from forecast.recommend import TownInfo, _town_masks
from forecast.rollout import burn_probability, rollout_paired
from sim.effects import SuppressionSchedule
from sim.fire import SIM_MINUTES_PER_TICK, FireSnapshot, Wind
from uq.mc import mean_ci

# Paired, so 16 already separates a plan from doing nothing; a 2 h plan on a
# large fire takes a couple of seconds.
PLAN_ROLLOUTS = 16


@dataclass
class TownOutcome:
    town: str
    base_hits: int
    plan_hits: int
    saves: int
    worsens: int
    base_median_min: float | None
    plan_median_min: float | None


@dataclass
class PlanOutcome:
    n: int
    acres_base: float
    acres_plan: float
    acres_saved: tuple[float, float, float]  # paired (mean, lo, hi)
    people_base: float
    people_plan: float
    towns: list[TownOutcome]
    grids: np.ndarray  # uint8 (2, H, W): P(burned by the horizon), baseline then plan


def _median_min(arrivals: np.ndarray) -> float | None:
    """Median minutes until fire over the simulations, if at least half reach the town."""
    reached = np.isfinite(arrivals)
    if reached.sum() * 2 < len(arrivals):
        return None
    return round(float(np.median(arrivals[reached])) * SIM_MINUTES_PER_TICK, 1)


def evaluate_plan(snapshot: FireSnapshot, plan: SuppressionSchedule, towns: list[TownInfo], wind: Wind,
                  ticks: int, acres_per_cell: float, n: int = PLAN_ROLLOUTS, seed: int = 0) -> PlanOutcome:
    h, w = snapshot.state.shape
    first = rollout_paired(snapshot, n, ticks, [plan], wind=wind, seed=seed)  # (2, n, H, W)
    burned = np.isfinite(first).reshape(2, n, h * w)
    cells = burned.sum(axis=2).astype(np.float32)  # (2, n)
    out = []
    people = np.zeros((2, n), np.float32)
    if towns:
        masks = _town_masks(towns, h, w).reshape(len(towns), -1)
        frac = burned.astype(np.float32) @ masks.T / np.maximum(masks.sum(axis=1), 1.0)  # (2, n, T)
        people = frac @ np.array([t.population for t in towns], np.float32)
        reached = frac > 0
        fb = first.reshape(2, n, h * w)
        for i, t in enumerate(towns):
            m = masks[i] > 0
            arrivals = fb[:, :, m].min(axis=2) if m.any() else np.full((2, n), np.inf)
            out.append(TownOutcome(
                town=t.name,
                base_hits=int(reached[0, :, i].sum()),
                plan_hits=int(reached[1, :, i].sum()),
                saves=int((reached[0, :, i] & ~reached[1, :, i]).sum()),
                worsens=int((~reached[0, :, i] & reached[1, :, i]).sum()),
                base_median_min=_median_min(arrivals[0]),
                plan_median_min=_median_min(arrivals[1]),
            ))
    mean, lo, hi = mean_ci((cells[0] - cells[1]) * acres_per_cell)
    grids = np.stack([burn_probability(first[0], ticks), burn_probability(first[1], ticks)])
    return PlanOutcome(
        n=n,
        acres_base=float(cells[0].mean() * acres_per_cell),
        acres_plan=float(cells[1].mean() * acres_per_cell),
        acres_saved=(mean, lo, hi),
        people_base=float(people[0].mean()),
        people_plan=float(people[1].mean()),
        towns=out,
        grids=np.round(grids * 255).astype(np.uint8),
    )


