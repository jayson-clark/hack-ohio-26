"""Online conformal risk control for the forecast's burn envelope (#12).

Each forecast gives P(burn by T+h). The envelope for horizon h is the set of
cells with P >= lambda, widened by `margin` cells when even the lowest useful
lambda isn't enough. Its promise: of the ground that newly burns in the next h
minutes, at most `alpha` (10%) falls outside the envelope, in the long run.

The raw forecast can't promise that by itself. It assumes the wind and tokens
hold, and players change both mid-forecast; the eval found it overconfident
after wind shifts. So each envelope is scored when its horizon passes:

    miss = (area newly burned outside the envelope) / (area newly burned)

and the single knob `theta` moves to keep the long-run miss near alpha, an
adaptive conformal update (Gibbs & Candes 2021; conformal risk control,
Angelopoulos et al. 2022):

    theta <- theta - lr * (miss - alpha)

Too many misses lower theta: a bigger envelope. The online version keeps its
long-run guarantee under distribution shift (a wind shift, a new scenario),
at the cost of a short catch-up after the shift. Each horizon has its own knob.

Misses are measured in area, not cells, so the promise means the same thing
on maps of different resolution. Forecasts mature in order but with a delay
(h minutes), and several are in flight at once; each update uses the envelope
that was shown when that forecast was issued.

theta maps to the envelope as: lambda = max(theta, lam_min), and below lam_min
(one rollout out of N), margin = ceil((lam_min - theta) / MARGIN_STEP) cells of
dilation around the lam_min set.
"""

import math
from collections import deque
from dataclasses import dataclass, field

import numpy as np

ALPHA = 0.1  # the promise: at most 10% of new burning outside the envelope
LR = 0.1  # how fast theta reacts to each scored forecast (eval.run: 0.05 too slow after shifts, 0.2 jumpy)
MARGIN_STEP = 0.02  # theta below lam_min buys one cell of margin per step
MAX_MARGIN = 10  # cells
WINDOW = 20  # forecasts in the "recent" miss rate shown to the operator


def dilate(mask: np.ndarray, cells: int) -> np.ndarray:
    """Grow a bool (H, W) mask by `cells` king moves."""
    out = mask.copy()
    for _ in range(cells):
        grown = out.copy()
        grown[1:] |= out[:-1]
        grown[:-1] |= out[1:]
        grown[:, 1:] |= grown[:, :-1].copy()
        grown[:, :-1] |= grown[:, 1:].copy()
        out = grown
    return out


@dataclass
class OnlineEnvelope:
    """The calibrated envelope for one horizon."""

    theta: float  # warm start, e.g. from eval.run's lambda_for_fnr_10pct
    lam_min: float  # the smallest probability a forecast can express, 1/N
    alpha: float = ALPHA
    lr: float = LR
    scored: int = 0
    total_miss: float = 0.0
    recent: deque = field(default_factory=lambda: deque(maxlen=WINDOW))

    @property
    def threshold(self) -> float:
        return max(self.theta, self.lam_min)

    @property
    def margin(self) -> int:
        if self.theta >= self.lam_min:
            return 0
        return min(MAX_MARGIN, math.ceil((self.lam_min - self.theta) / MARGIN_STEP))

    def envelope(self, p: np.ndarray, already: np.ndarray | None = None) -> np.ndarray:
        """bool (H, W): where the fire is expected by the horizon. `already`
        (burning or burned now) is always inside."""
        s = p >= self.threshold
        if self.margin:
            s = dilate(s, self.margin)
        if already is not None:
            s |= already
        return s

    def update(self, envelope: np.ndarray, newly_burned: np.ndarray) -> float | None:
        """Score one matured forecast. Returns its miss rate, or None when
        nothing new burned (no information, no update)."""
        area = int(newly_burned.sum())
        if area == 0:
            return None
        miss = float((newly_burned & ~envelope).sum()) / area
        self.theta = float(np.clip(self.theta - self.lr * (miss - self.alpha),
                                   self.lam_min - MAX_MARGIN * MARGIN_STEP, 1.0))
        self.scored += 1
        self.total_miss += miss
        self.recent.append(miss)
        return miss

    @property
    def miss_overall(self) -> float | None:
        return None if self.scored == 0 else self.total_miss / self.scored

    @property
    def miss_recent(self) -> float | None:
        return None if not self.recent else float(np.mean(self.recent))


@dataclass
class _Issued:
    mature_tick: int
    horizon: int  # index into the envelopes
    envelope: np.ndarray  # bool (H, W), as shown
    unburned: np.ndarray  # bool (H, W): fuel not yet alight at issue


class EnvelopeLedger:
    """Keeps each shown envelope until its horizon passes, then scores it.
    One OnlineEnvelope per horizon; call issue() when a forecast lands and
    mature() after every fire step."""

    def __init__(self, horizons_ticks: tuple[float, ...], warm: tuple[float, ...], n_rollouts: int,
                 lr: float = LR) -> None:
        self.horizons_ticks = horizons_ticks
        self.envs = [OnlineEnvelope(theta=w, lam_min=1.0 / n_rollouts, lr=lr) for w in warm]
        self._pending: list[_Issued] = []

    def issue(self, tick: int, probability: np.ndarray, state_lit: np.ndarray, state_fuel: np.ndarray) -> list[np.ndarray]:
        """Envelopes for a forecast issued at `tick` (probability (K, H, W)),
        remembered for scoring. Returns them, one per horizon."""
        out = []
        for i, (env, h) in enumerate(zip(self.envs, self.horizons_ticks)):
            s = env.envelope(probability[i], state_lit)
            self._pending.append(_Issued(tick + int(math.ceil(h)), i, s, state_fuel.copy()))
            out.append(s)
        return out

    def mature(self, tick: int, state_lit: np.ndarray) -> list[tuple[int, float]]:
        """Score every envelope whose horizon has passed. Returns (horizon
        index, miss) for each one scored."""
        done = [p for p in self._pending if p.mature_tick <= tick]
        self._pending = [p for p in self._pending if p.mature_tick > tick]
        out = []
        for p in sorted(done, key=lambda p: p.mature_tick):
            miss = self.envs[p.horizon].update(p.envelope, state_lit & p.unburned)
            if miss is not None:
                out.append((p.horizon, miss))
        return out

    def clear_pending(self) -> None:
        """Drop in-flight envelopes (the map was reset); keep what was learned."""
        self._pending.clear()
