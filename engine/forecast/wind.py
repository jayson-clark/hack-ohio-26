"""Future-wind scenarios for the forecast ensemble (#228).

The forecast used to assume the wind at issue holds for the whole horizon.
When the wind then changes, every rollout is wrong the same way and the
outline misses most of the new fire (AI_README.md, "What actually drives the
drop after a wind shift"). Here each rollout instead gets its own plausible
wind trajectory, minute by minute, built only from the wind at issue:

- slow wander: direction and log-speed drift as AR(1) (Ornstein-Uhlenbeck)
  processes around the issue wind, starting at zero, so the spread grows
  with lead time (sd ~ dir_sd_deg * sqrt(1 - rho^(2t))) and consecutive
  minutes are correlated (rho = exp(-1 / persistence_min));
- abrupt shifts: a Poisson number of changes (shift_rate_per_h), each
  turning the wind by a uniform amount in shift_dir_deg, either way, and
  scaling its speed by a lognormal factor (shift_speed_sd); the wander then
  continues around the new wind;
- gusts: in any minute, with chance gust_prob, speed x (1 + gust_frac).

There is no weather forecast in the scenarios to centre this on, so the
baseline is persistence of the current wind. The parameters are a scenario
prior (what kinds of change are plausible in a round), not fitted to
observed weather: the ensemble is a scenario model, not a calibrated
meteorological forecast. See AI_README.md for how they were chosen.
"""

import math
from dataclasses import dataclass

import numpy as np

from sim.fire import C1, C2, NEIGHBOURS, Wind

MAX_SPEED = 30.0  # m/s; clip so a run of jumps can't blow up


@dataclass(frozen=True)
class WindScenarios:
    """How the future wind may differ from the wind at issue. All rates are per sim minute unless named."""

    dir_sd_deg: float = 15.0  # long-run sd of the slow direction wander
    speed_sd: float = 0.15  # long-run sd of the slow log-speed wander (0.15 ~ +-15%)
    persistence_min: float = 60.0  # e-folding time of the wander
    shift_rate_per_h: float = 0.25  # abrupt changes per hour
    shift_dir_deg: tuple[float, float] = (30.0, 180.0)  # size of a turn, uniform, random sign
    shift_speed_sd: float = 0.4  # log-speed jump sd at a shift (0.4 ~ x0.67..x1.5)
    gust_prob: float = 0.05  # chance a given minute is gusty
    gust_frac: float = 0.3  # how much stronger a gust is


@dataclass(frozen=True)
class WindPaths:
    """Per rollout and tick: the wind the rollout sees on step t + 1 (t = 0 is the first step)."""

    speed_ms: np.ndarray  # float32 (T, N)
    from_deg: np.ndarray  # float32 (T, N), in [0, 360)

    def at(self, t: int) -> tuple[np.ndarray, np.ndarray]:
        i = min(t, len(self.speed_ms) - 1)
        return self.speed_ms[i], self.from_deg[i]


def sample_paths(wind: Wind, n: int, ticks: int, model: WindScenarios, rng: np.random.Generator,
                 minutes_per_tick: float = 1.0) -> WindPaths:
    """n wind trajectories of `ticks` steps, starting from `wind` (the wind at
    issue, the only input about the weather). Vectorized over rollouts."""
    rho = math.exp(-minutes_per_tick / model.persistence_min) if model.persistence_min > 0 else 0.0
    kick = math.sqrt(max(1.0 - rho * rho, 0.0))
    base_dir = np.full(n, float(wind.from_deg))
    base_log = np.full(n, math.log(max(wind.speed_ms, 0.1)))
    wd = np.zeros(n)  # direction wander, degrees
    ws = np.zeros(n)  # log-speed wander
    p_shift = 1.0 - math.exp(-model.shift_rate_per_h * minutes_per_tick / 60.0)
    lo, hi = model.shift_dir_deg
    speeds = np.empty((ticks, n), np.float32)
    dirs = np.empty((ticks, n), np.float32)
    for t in range(ticks):
        wd = rho * wd + kick * model.dir_sd_deg * rng.standard_normal(n)
        ws = rho * ws + kick * model.speed_sd * rng.standard_normal(n)
        jump = rng.random(n) < p_shift
        turn = rng.uniform(lo, hi, n) * np.where(rng.random(n) < 0.5, -1.0, 1.0)
        base_dir = np.where(jump, base_dir + turn, base_dir)
        base_log = np.where(jump, base_log + model.shift_speed_sd * rng.standard_normal(n), base_log)
        gust = np.where(rng.random(n) < model.gust_prob, 1.0 + model.gust_frac, 1.0)
        v = np.minimum(np.exp(base_log + ws) * gust, MAX_SPEED)
        speeds[t] = v
        dirs[t] = np.mod(base_dir + wd, 360.0)
    return WindPaths(speeds, dirs)


def factors(speed_ms: np.ndarray, from_deg: np.ndarray) -> np.ndarray:
    """sim.fire.wind_factors for many winds at once, float32 (8, N)."""
    f = np.radians(np.asarray(from_deg, np.float64))
    to_x, to_y = -np.sin(f), np.cos(f)
    v = np.maximum(np.asarray(speed_ms, np.float64), 0.0)
    out = np.empty((8, len(v)), np.float32)
    for d, (dy, dx) in enumerate(NEIGHBOURS):
        cos_t = (-dx * to_x - dy * to_y) / math.hypot(dx, dy)
        out[d] = np.exp(C1 * v) * np.exp(C2 * v * (cos_t - 1))
    return out
