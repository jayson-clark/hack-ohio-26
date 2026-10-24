"""Batched stochastic rollouts of the fire model.

N copies of a FireSnapshot are stacked into (N, H, W) arrays and advanced
together by sim.fire.advance, the same kernel the live sim uses. What comes
out is, per rollout, the first tick each cell caught fire, which is enough to
answer "P(burn by t)" for any t, and lets routing ask about the moment a bus
would arrive rather than one fixed horizon.
"""

from dataclasses import dataclass

import numpy as np

from sim.fire import BURNED, BURNING, FireSnapshot, Wind, advance, wind_factors


@dataclass(frozen=True)
class WindSpread:
    """How much the wind varies across an ensemble's rollouts.

    Each rollout draws its own wind: speed scaled by a normal factor
    (1 ± speed_frac, clipped at 0) and direction shifted by a normal number
    of degrees (± dir_deg). Off unless asked for: ignition noise alone makes
    a forecast too sure of itself when the wind changes mid-run.
    """

    speed_frac: float = 0.2
    dir_deg: float = 15.0


def ensemble_wind(wind: Wind, n: int, spread: WindSpread, rng: np.random.Generator) -> np.ndarray:
    """Per-rollout wind factors, float32 (8, n), for advance(wind_rows=...)."""
    speeds = np.maximum(wind.speed_ms * (1.0 + spread.speed_frac * rng.standard_normal(n)), 0.0)
    dirs = wind.from_deg + spread.dir_deg * rng.standard_normal(n)
    return np.stack([wind_factors(Wind(float(v), float(d))) for v, d in zip(speeds, dirs)], axis=1)


def _wind_rng(seed: int | None) -> np.random.Generator:
    # Separate from the ignition stream, so turning spread on doesn't change
    # which cells catch for a given seed beyond what the wind itself changes.
    return np.random.default_rng(None if seed is None else (seed, 1))


def rollout(
    snapshot: FireSnapshot,
    n: int,
    ticks: int,
    *,
    wind: Wind | None = None,
    extra_suppression: np.ndarray | None = None,
    seed: int | None = None,
    wind_spread: WindSpread | None = None,
) -> np.ndarray:
    """Ticks from now until each cell first burns, float32 (n, H, W).

    0 for cells already burning or burned, np.inf for cells that don't catch
    within `ticks`. `wind` overrides the snapshot's (for what-ifs), and
    `extra_suppression` is max-combined with the snapshot's, to test a
    hypothetical placement. If the snapshot carries a suppression schedule,
    suppression follows it tick by tick: a crew placed a moment ago digs in
    over the forecast, and wet ground dries out (#56). Without one it stays
    frozen at the snapshot's grid.
    """
    extra = None if extra_suppression is None else extra_suppression.astype(np.float32)

    def sup_at(dt: int) -> np.ndarray:
        base = _base_at(snapshot, dt)
        return base if extra is None else np.maximum(base, extra)

    wind = wind or snapshot.wind
    rows = None if wind_spread is None else ensemble_wind(wind, n, wind_spread, _wind_rng(seed))
    sup = sup_at if _varies(snapshot) else sup_at(0)
    return _run(snapshot, n, ticks, sup, wind, rows, np.random.default_rng(seed), group=1)


def rollout_paired(
    snapshot: FireSnapshot,
    n: int,
    ticks: int,
    variants,
    *,
    wind: Wind | None = None,
    seed: int | None = None,
    wind_spread: WindSpread | None = None,
) -> np.ndarray:
    """First-burn ticks for a baseline and K what-ifs on identical luck,
    float32 (K+1, n, H, W). Index 0 is the baseline (the snapshot as is);
    index k is the snapshot plus variants[k-1], max-combined into its
    suppression. A variant is a fixed grid (float (H, W)), a
    sim.effects.TimedLayer (a crew that starts digging in at its arrival tick
    and ramps up, as a placed one really would, #56, #104), or a whole
    sim.effects.SuppressionSchedule (several orders at once: a plan, #123).

    Rollout i of every variant sees the same random draws (and the same wind,
    with wind_spread), so `first[k, i]` vs `first[0, i]` differs only because
    of the intervention. Comparing them pairwise has far less noise than two
    independent forecasts.
    """
    if isinstance(variants, np.ndarray):
        variants = list(np.asarray(variants, np.float32).reshape(-1, *snapshot.state.shape))
    k = len(variants)
    timed = [v for v in variants if hasattr(v, "level") or hasattr(v, "at")]

    def sup_at(dt: int) -> np.ndarray:
        base = _base_at(snapshot, dt)
        sup = np.empty((k + 1, *base.shape), np.float32)
        sup[0] = base
        for i, v in enumerate(variants, start=1):
            if hasattr(v, "level"):
                lvl = v.level(dt)
                sup[i] = np.maximum(base, lvl * v.footprint) if lvl > 0 else base
            elif hasattr(v, "at"):
                np.maximum(base, v.at(dt), out=sup[i])
            else:
                np.maximum(base, v, out=sup[i])
        return sup

    wind = wind or snapshot.wind
    rows = None
    if wind_spread is not None:
        rows = np.tile(ensemble_wind(wind, n, wind_spread, _wind_rng(seed)), (1, k + 1))
    # One grid per variant; advance() repeats each over its block of rollouts
    # (variant-major rows: [v0 r0..r(n-1), v1 r0..r(n-1), ...]), and tiling one
    # block of draws (`group`) lines up rollout i across variants.
    sup = sup_at if (_varies(snapshot) or any(v.varies for v in timed)) else sup_at(0)
    first = _run(snapshot, (k + 1) * n, ticks, sup, wind, rows, np.random.default_rng(seed), group=k + 1)
    return first.reshape(k + 1, n, *snapshot.state.shape)


def _base_at(snapshot: FireSnapshot, dt: int) -> np.ndarray:
    """The snapshot's own suppression `dt` ticks from now."""
    sched = getattr(snapshot, "schedule", None)
    return snapshot.suppression if sched is None else sched.at(dt)


def _varies(snapshot: FireSnapshot) -> bool:
    sched = getattr(snapshot, "schedule", None)
    return sched is not None and sched.varies


def _run(snapshot, n, ticks, suppression, wind, wind_rows, rng, group) -> np.ndarray:
    """`suppression` is a grid (or one per group), or a function of dt (ticks
    from now) returning one. Rollout step t applies suppression at dt = t - 1,
    the same tick the live sim would."""
    state = np.repeat(snapshot.state[None], n, axis=0)
    burn_left = np.repeat(snapshot.burn_left[None], n, axis=0)
    first = np.full(state.shape, np.inf, np.float32)
    first[(state == BURNING) | (state == BURNED)] = 0.0
    for t in range(1, ticks + 1):
        sup = suppression(t - 1) if callable(suppression) else suppression
        result = advance(state, burn_left, snapshot.layers, wind, sup, rng, group=group, wind_rows=wind_rows)
        if result is None:
            break  # every rollout has burned out
        ignited, y0, x0, spots = result
        crop = first[:, y0 : y0 + ignited.shape[1], x0 : x0 + ignited.shape[2]]
        crop[ignited] = t
        if spots is not None:  # embers can land anywhere on the map
            first[spots] = np.minimum(first[spots], t)
    return first


def burn_probability(first_burn: np.ndarray, horizon_ticks: float) -> np.ndarray:
    """Fraction of rollouts in which each cell has burned by the horizon, float32 (H, W)."""
    return (first_burn <= horizon_ticks).mean(axis=0, dtype=np.float32)
