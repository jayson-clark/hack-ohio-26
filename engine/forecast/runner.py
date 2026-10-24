"""Runs forecasts in a worker process so they never stall the tick loop.

A forecast is N rollouts to the furthest horizon (about 0.1 s for a young
fire, over a second for one that covers the map), far too slow for a 100 ms
tick. The server keeps at most one in flight and starts the next only when
the last has landed, so forecasts never queue up behind a fast-moving fire.
"""

import asyncio
import multiprocessing
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass

import numpy as np

from forecast.rollout import WindSpread, burn_probability, rollout
from sim.fire import SIM_MINUTES_PER_TICK, FireSnapshot

HORIZONS_MIN = (30, 60)  # sim-minutes; the ghost shows one layer per horizon
N_ROLLOUTS = 32
# Per-rollout wind variation for the live forecast. Off for now; set to
# WindSpread() to make the ghost hedge against wind shifts (forecast/rollout.py).
WIND_SPREAD: WindSpread | None = None


@dataclass(frozen=True)
class Forecast:
    tick: int  # sim tick of the snapshot the forecast started from
    horizons_ticks: tuple[float, ...]
    # Per rollout, ticks after `tick` until each cell first burns (0 = already
    # burning or burned, inf = not within the last horizon). float32 (N, H, W).
    # P(burn by t) for any t is (first_burn <= t).mean(axis=0).
    first_burn: np.ndarray
    # burn_probability at each horizon, float32 (len(horizons), H, W) in [0, 1].
    probability: np.ndarray
    # The wind variation the rollouts used, or None for the snapshot's wind only.
    wind_spread: WindSpread | None = None


def horizon_ticks(minutes: float) -> float:
    return minutes / SIM_MINUTES_PER_TICK


def run_forecast(
    snapshot: FireSnapshot, n: int = N_ROLLOUTS, seed: int | None = None, wind_spread: WindSpread | None = WIND_SPREAD
) -> Forecast:
    """The worker-side job. Also fine to call in-process (tests, what-ifs)."""
    horizons = tuple(horizon_ticks(m) for m in HORIZONS_MIN)
    first = rollout(snapshot, n, int(np.ceil(max(horizons))), seed=seed, wind_spread=wind_spread)
    prob = np.stack([burn_probability(first, h) for h in horizons])
    return Forecast(
        tick=snapshot.tick, horizons_ticks=horizons, first_burn=first, probability=prob, wind_spread=wind_spread
    )


class Forecaster:
    def __init__(self) -> None:
        # spawn (the macOS default anyway) so the worker doesn't inherit the
        # event loop or open sockets.
        ctx = multiprocessing.get_context("spawn")
        self._pool = ProcessPoolExecutor(max_workers=1, mp_context=ctx)

    def submit(self, snapshot: FireSnapshot) -> asyncio.Future[Forecast]:
        loop = asyncio.get_running_loop()
        return loop.run_in_executor(self._pool, run_forecast, snapshot)

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
