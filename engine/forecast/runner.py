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
# The evacuation clock's long forecast (#121). A big town takes hours to empty
# (Paradise: about 7 h), so the clock needs to see that far. 32 rollouts to
# T+600 take 3-8 s in one process, so they're split across EVAC_WORKERS.
EVAC_HORIZON_MIN = 600
EVAC_ROLLOUTS = 32
EVAC_WORKERS = 2
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


@dataclass(frozen=True)
class LongForecast:
    """First-burn times like Forecast.first_burn, out to horizon_min, for the evacuation clock."""

    tick: int
    horizon_min: float
    first_burn: np.ndarray  # float32 (N, H, W)


def run_long_part(snapshot: FireSnapshot, n: int, seed: int | None = None) -> np.ndarray:
    """One worker's share of the long forecast's rollouts."""
    return rollout(snapshot, n, int(np.ceil(horizon_ticks(EVAC_HORIZON_MIN))), seed=seed)


class LongForecaster:
    """Runs the long forecast's rollouts split across its own worker processes."""

    def __init__(self, workers: int = EVAC_WORKERS) -> None:
        self.workers = workers
        self._pool = ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context("spawn"))

    async def run(self, snapshot: FireSnapshot) -> LongForecast:
        loop = asyncio.get_running_loop()
        sizes = [len(c) for c in np.array_split(np.arange(EVAC_ROLLOUTS), self.workers)]
        parts = await asyncio.gather(*(loop.run_in_executor(self._pool, run_long_part, snapshot, k) for k in sizes))
        return LongForecast(tick=snapshot.tick, horizon_min=EVAC_HORIZON_MIN, first_burn=np.concatenate(parts))

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)


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
