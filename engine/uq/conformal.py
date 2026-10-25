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


# --- Time-to-impact intervals (#13) -------------------------------------------------

# Lead-time buckets by predicted median arrival (minutes). Scores are pooled
# within a bucket: arrivals an hour out are less certain than ones in minutes.
ETA_BUCKETS = (30.0, 120.0)
ETA_LR = 2.0  # minutes a single miss (or hit) moves a bucket's correction
ETA_CELLS = 300  # calibration units sampled per forecast to score
ETA_UNIT_RADIUS = 8.0  # cells: town-sized disks, scored like towns (first fire anywhere inside)


def bucket_of(median_min: float) -> int:
    return int(np.searchsorted(ETA_BUCKETS, median_min, side="right"))


@dataclass
class OnlineQuantile:
    """Adaptive conformal quantile of a stream of scores: q moves up by
    lr * (1 - alpha) on a miss (score > q) and down by lr * alpha on a hit,
    so in the long run about alpha of scores exceed it (Gibbs & Candes 2021)."""

    q: float = 0.0
    alpha: float = ALPHA
    lr: float = ETA_LR
    scored: int = 0
    misses: int = 0

    def update(self, score: float) -> None:
        miss = score > self.q
        self.q += self.lr * ((1.0 if miss else 0.0) - self.alpha)
        self.scored += 1
        self.misses += int(miss)


def arrival_quantiles(first_burn: np.ndarray, lo: float = 0.05, hi: float = 0.95) -> np.ndarray:
    """Per-cell (or per-town) arrival quantiles over rollouts: (3, ...) for
    lo, median and hi, in the same units as `first_burn`; inf where that many
    rollouts never reach it."""
    return np.quantile(first_burn, [lo, 0.5, hi], axis=0, method="higher")


@dataclass
class _EtaIssued:
    issue_tick: int
    horizon: int  # ticks the forecast covers
    units: list[np.ndarray]  # flat cell indices of each town-sized disk
    lo: np.ndarray  # predicted interval, ticks after issue
    hi: np.ndarray
    bucket: np.ndarray


class ArrivalCalibrator:
    """Conformalized quantile intervals for when fire arrives (CQR, online).

    Each forecast's rollouts give a raw [5%, 95%] arrival range for any area,
    as the first time fire touches it. The calibration units are town-sized
    disks (ETA_UNIT_RADIUS) dropped on unburned ground, so they behave like
    towns: single cells didn't (in eval.arrival, cell-calibrated ranges held
    on cells but covered towns only ~50% after a wind shift). Once a disk
    burns, or the forecast's horizon passes without it, it is scored as
        s = max(lo - y, y - hi)   (positive: outside the range)
    and its lead-time bucket's correction Q moves (OnlineQuantile). A town's
    calibrated range is [lo - Q, hi + Q] for its bucket. Disks stand in for
    towns because towns catch fire too rarely to calibrate on alone (an
    exchangeability assumption that eval.arrival checks on the towns).

    Censoring: a cell still unburned at the horizon gives only y > horizon,
    so its score is the smallest it could be, max(0, horizon - hi). That can
    only make Q too small, so it's reported, not hidden."""

    def __init__(self, cell_m: float, rng_seed: int = 0, unit_radius: float = ETA_UNIT_RADIUS) -> None:
        self.unit_radius = unit_radius
        self._offsets: np.ndarray | None = None
        self.buckets = [OnlineQuantile() for _ in range(len(ETA_BUCKETS) + 1)]
        self.cell_m = cell_m
        self._pending: list[_EtaIssued] = []
        self._rng = np.random.default_rng(rng_seed)
        self.censored = 0

    def correction(self, median_min: float) -> float:
        return self.buckets[bucket_of(median_min)].q

    def interval(self, lo_min: float, median_min: float, hi_min: float) -> tuple[float, float]:
        q = self.correction(median_min)
        return max(0.0, lo_min - q), max(lo_min - q, hi_min + q, 0.0)

    def issue(self, tick: int, first_burn: np.ndarray, unburned: np.ndarray, minutes_per_tick: float,
              horizon_ticks: int) -> None:
        """Remember a sample of cells from a forecast that started at `tick`
        and ran `horizon_ticks` (so a cell not burned by then is censored)."""
        horizon = int(horizon_ticks)
        n, h, w = first_burn.shape
        fb = first_burn.reshape(n, -1)
        # Centres: unburned cells that at least one rollout reaches.
        ok = np.flatnonzero(unburned.ravel() & np.isfinite(fb).any(axis=0))
        if len(ok) == 0:
            return
        centres = self._rng.choice(ok, size=min(ETA_CELLS, len(ok)), replace=False)
        units, los, his, buckets = [], [], [], []
        for c in centres:
            cells = self._disk(int(c), h, w)
            cells = cells[unburned.ravel()[cells]]
            a = fb[:, cells].min(axis=1)  # each rollout's first fire anywhere in the disk
            lo, med, hi = arrival_quantiles(a)
            if not np.isfinite(hi):
                continue  # too few rollouts reach it to bound the range
            units.append(cells)
            los.append(lo)
            his.append(hi)
            buckets.append(bucket_of(float(med) * minutes_per_tick))
        if units:
            self._pending.append(_EtaIssued(tick, max(horizon, 1), units, np.array(los), np.array(his), np.array(buckets)))

    def _disk(self, centre: int, h: int, w: int) -> np.ndarray:
        if self._offsets is None:
            r = int(np.ceil(self.unit_radius))
            dy, dx = np.mgrid[-r : r + 1, -r : r + 1]
            keep = np.hypot(dx, dy) <= self.unit_radius
            self._offsets = np.stack([dy[keep], dx[keep]])
        y, x = divmod(centre, w)
        ys, xs = y + self._offsets[0], x + self._offsets[1]
        inside = (ys >= 0) & (ys < h) & (xs >= 0) & (xs < w)
        return ys[inside] * w + xs[inside]

    def mature(self, tick: int, burn_tick: np.ndarray, minutes_per_tick: float) -> int:
        """Score every remembered cell that has burned or whose forecast has
        run out. `burn_tick` is the live first-burn tick per cell (inf if
        not yet). Returns how many were scored."""
        flat = burn_tick.ravel()
        scored = 0
        keep = []
        for p in self._pending:
            y = np.array([flat[u].min() for u in p.units]) - p.issue_tick
            expired = tick - p.issue_tick >= p.horizon
            done = np.isfinite(y) | expired
            for i in np.flatnonzero(done):
                if np.isfinite(y[i]):
                    s = max(p.lo[i] - y[i], y[i] - p.hi[i])
                else:
                    s = max(0.0, p.horizon - p.hi[i])
                    self.censored += 1
                self.buckets[p.bucket[i]].update(float(s) * minutes_per_tick)
                scored += 1
            rest = ~done
            if rest.any():
                keep.append(_EtaIssued(p.issue_tick, p.horizon, [u for u, r in zip(p.units, rest) if r],
                                       p.lo[rest], p.hi[rest], p.bucket[rest]))
        self._pending = keep
        return scored

    def clear_pending(self) -> None:
        self._pending.clear()
