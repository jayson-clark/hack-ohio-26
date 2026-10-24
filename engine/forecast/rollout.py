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
    hypothetical crew placement. Suppression stays frozen for the whole
    rollout; a crew that is still ramping up is forecast at its current level.
    """
    suppression = snapshot.suppression
    if extra_suppression is not None:
        suppression = np.maximum(suppression, extra_suppression.astype(np.float32))
    wind = wind or snapshot.wind
    rows = None if wind_spread is None else ensemble_wind(wind, n, wind_spread, _wind_rng(seed))
    return _run(snapshot, n, ticks, suppression, wind, rows, np.random.default_rng(seed), group=1)


def rollout_paired(
    snapshot: FireSnapshot,
    n: int,
    ticks: int,
    variants: np.ndarray,
    *,
    wind: Wind | None = None,
    seed: int | None = None,
    wind_spread: WindSpread | None = None,
) -> np.ndarray:
    """First-burn ticks for a baseline and K what-ifs on identical luck,
    float32 (K+1, n, H, W). Index 0 is the baseline (the snapshot as is);
    index k is the snapshot with variants[k-1] (float (K, H, W), e.g. a crew's
    suppression footprint) max-combined into its suppression.

    Rollout i of every variant sees the same random draws (and the same wind,
    with wind_spread), so `first[k, i]` vs `first[0, i]` differs only because
    of the intervention. Comparing them pairwise has far less noise than two
    independent forecasts.
    """
    variants = np.asarray(variants, np.float32).reshape(-1, *snapshot.state.shape)
    k = variants.shape[0]
    sup = np.empty((k + 1, *snapshot.state.shape), np.float32)
    sup[0] = snapshot.suppression
    sup[1:] = np.maximum(snapshot.suppression[None], variants)
    # Variant-major rows: [v0 r0..r(n-1), v1 r0..r(n-1), ...], so tiling one
    # block of draws (advance's `group`) lines up rollout i across variants.
    suppression = np.repeat(sup, n, axis=0)
    wind = wind or snapshot.wind
    rows = None
    if wind_spread is not None:
        rows = np.tile(ensemble_wind(wind, n, wind_spread, _wind_rng(seed)), (1, k + 1))
    first = _run(snapshot, (k + 1) * n, ticks, suppression, wind, rows, np.random.default_rng(seed), group=k + 1)
    return first.reshape(k + 1, n, *snapshot.state.shape)


def _run(snapshot, n, ticks, suppression, wind, wind_rows, rng, group) -> np.ndarray:
    state = np.repeat(snapshot.state[None], n, axis=0)
    burn_left = np.repeat(snapshot.burn_left[None], n, axis=0)
    first = np.full(state.shape, np.inf, np.float32)
    first[(state == BURNING) | (state == BURNED)] = 0.0
    for t in range(1, ticks + 1):
        result = advance(
            state, burn_left, snapshot.layers, wind, suppression, rng, group=group, wind_rows=wind_rows
        )
        if result is None:
            break  # every rollout has burned out
        ignited, y0, x0 = result
        crop = first[:, y0 : y0 + ignited.shape[1], x0 : x0 + ignited.shape[2]]
        crop[ignited] = t
    return first


def burn_probability(first_burn: np.ndarray, horizon_ticks: float) -> np.ndarray:
    """Fraction of rollouts in which each cell has burned by the horizon, float32 (H, W)."""
    return (first_burn <= horizon_ticks).mean(axis=0, dtype=np.float32)
