"""What the fire emulator sees and predicts (#113). NumPy only, so data
generation and the engine can build inputs without MLX.

Input channels, float32 (C, H, W):
  0  burning                     1 where a cell is on fire now
  1  burned                      1 where it has burned out
  2  burn_left / BURN_TICKS      how long burning cells keep going
  3-10 spread[d] * wind[d]       per-direction chance a burning neighbour
                                 lights the cell (fuel, slope, wind), the same
                                 numbers advance() uses, scaled by 1/SPREAD_SCALE
  11-14 suppression at +0, +15, +30, +60 ticks (crews dig in, drops dry, #56)

Output: P(burn by T+30) and P(burn by T+60), (2, H, W).

Cells already burning or burned are 1, and cells further than h cells
(Chebyshev) from any burning cell can't be reached in h ticks, since fire moves
at most one cell per tick, so they're 0. The net only predicts the cells in
between; `finish` applies these rules to its output.
"""

import numpy as np

from sim.fire import BURN_TICKS, BURNED, BURNING, NEIGHBOURS, FireSnapshot, wind_factors

HORIZONS = (30, 60)  # ticks (= sim minutes); the forecast's own horizons
SUP_TICKS = (0, 15, 30, 60)
SPREAD_SCALE = 0.5  # head-fire spread chances top out around here
N_CHANNELS = 3 + 8 + len(SUP_TICKS)
MULTIPLE = 8  # the U-Net halves the grid three times


def suppression_stack(snapshot: FireSnapshot) -> np.ndarray:
    """Suppression at each SUP_TICKS offset, float32 (4, H, W)."""
    sched = getattr(snapshot, "schedule", None)
    if sched is None:
        return np.repeat(snapshot.suppression[None].astype(np.float32), len(SUP_TICKS), axis=0)
    return np.stack([sched.at(t) for t in SUP_TICKS]).astype(np.float32)


def inputs(state: np.ndarray, burn_left: np.ndarray, spread: np.ndarray, wind, sup: np.ndarray) -> np.ndarray:
    """Input channels from raw pieces: state uint8 (H, W), burn_left (H, W),
    the layers' spread (8, H, W), a Wind, and suppression (4, H, W)."""
    h, w = state.shape
    x = np.empty((N_CHANNELS, h, w), np.float32)
    x[0] = state == BURNING
    x[1] = state == BURNED
    x[2] = np.where(state == BURNING, burn_left, 0) / BURN_TICKS
    x[3:11] = np.minimum(spread * wind_factors(wind)[:, None, None], 1.0) / SPREAD_SCALE
    x[11:] = sup
    return x


def from_snapshot(snapshot: FireSnapshot) -> np.ndarray:
    return inputs(snapshot.state, snapshot.burn_left, snapshot.layers.spread, snapshot.wind, suppression_stack(snapshot))


def reach(burning: np.ndarray, steps: int) -> np.ndarray:
    """Cells within `steps` king moves of a burning cell, bool (H, W)."""
    out = burning.astype(bool).copy()
    for _ in range(steps):
        grown = out.copy()
        grown[1:] |= out[:-1]
        grown[:-1] |= out[1:]
        grown[:, 1:] |= grown[:, :-1].copy()
        grown[:, :-1] |= grown[:, 1:].copy()
        out = grown
        if out.all():
            break
    return out


def masks(state: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(done, open), each bool (len(HORIZONS), H, W): cells that are certainly
    1 (already burning or burned), and cells the net has to predict."""
    lit = state >= BURNING
    burning = state == BURNING
    done = np.repeat(lit[None], len(HORIZONS), axis=0)
    reachable = np.stack([reach(burning, h) for h in HORIZONS])
    return done, reachable & ~done


def finish(p: np.ndarray, state: np.ndarray) -> np.ndarray:
    """Apply the certain cells to a raw (2, H, W) prediction."""
    done, open_ = masks(state)
    return np.where(done, 1.0, np.where(open_, p, 0.0)).astype(np.float32)


# Flips are free extra data, but the 8 directional channels must swap to match.
def _perm(flip_y: bool, flip_x: bool) -> list[int]:
    moved = [(-dy if flip_y else dy, -dx if flip_x else dx) for dy, dx in NEIGHBOURS]
    return [NEIGHBOURS.index(m) for m in moved]


def flip_grid(a: np.ndarray, flip_y: bool, flip_x: bool) -> np.ndarray:
    """Flip the last two axes of any (..., H, W) array."""
    return a[..., ::-1 if flip_y else 1, ::-1 if flip_x else 1].copy()


def flip(x: np.ndarray, flip_y: bool, flip_x: bool) -> np.ndarray:
    """Flip input channels (C, H, W), swapping the directional ones to match."""
    x = flip_grid(x, flip_y, flip_x)
    x[3:11] = x[3:11][_perm(flip_y, flip_x)]
    return x
