"""Batched stochastic rollouts of the fire model.

N copies of a FireSnapshot are stacked into (N, H, W) arrays and advanced
together by sim.fire.advance, the same kernel the live sim uses. What comes
out is, per rollout, the first tick each cell caught fire, which is enough to
answer "P(burn by t)" for any t, and lets routing ask about the moment a bus
would arrive rather than one fixed horizon.
"""

import numpy as np

from sim.fire import BURNED, BURNING, FireSnapshot, Wind, advance


def rollout(
    snapshot: FireSnapshot,
    n: int,
    ticks: int,
    *,
    wind: Wind | None = None,
    extra_suppression: np.ndarray | None = None,
    seed: int | None = None,
) -> np.ndarray:
    """Ticks from now until each cell first burns, float32 (n, H, W).

    0 for cells already burning or burned, np.inf for cells that don't catch
    within `ticks`. `wind` overrides the snapshot's (for what-ifs), and
    `extra_suppression` is max-combined with the snapshot's, to test a
    hypothetical crew placement. Suppression stays frozen for the whole
    rollout; a crew that is still ramping up is forecast at its current level.
    """
    rng = np.random.default_rng(seed)
    state = np.repeat(snapshot.state[None], n, axis=0)
    burn_left = np.repeat(snapshot.burn_left[None], n, axis=0)
    suppression = snapshot.suppression
    if extra_suppression is not None:
        suppression = np.maximum(suppression, extra_suppression.astype(np.float32))
    wind = wind or snapshot.wind

    first = np.full(state.shape, np.inf, np.float32)
    first[(state == BURNING) | (state == BURNED)] = 0.0
    for t in range(1, ticks + 1):
        result = advance(state, burn_left, snapshot.layers, wind, suppression, rng)
        if result is None:
            break  # every rollout has burned out
        ignited, y0, x0 = result
        crop = first[:, y0 : y0 + ignited.shape[1], x0 : x0 + ignited.shape[2]]
        crop[ignited] = t
    return first


def burn_probability(first_burn: np.ndarray, horizon_ticks: float) -> np.ndarray:
    """Fraction of rollouts in which each cell has burned by the horizon, float32 (H, W)."""
    return (first_burn <= horizon_ticks).mean(axis=0, dtype=np.float32)
