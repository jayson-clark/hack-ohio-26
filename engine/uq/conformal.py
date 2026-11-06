"""Online conformal risk control for the forecast's burn envelope (#12, #227).

Each forecast gives P(burn by T+h). The envelope for horizon h is the set of
cells with P >= lambda, widened by `margin` cells when even the lowest useful
lambda isn't enough. Its target: of the ground that newly burns in the next h
minutes, on average at most `alpha` (10%) falls outside the envelope.

The raw forecast can't promise that by itself. It assumes the wind and tokens
hold, and players change both mid-forecast; the eval found it overconfident
after wind shifts. So each envelope is scored when its horizon passes, with a
CRC-style loss (the loss of conformal risk control, Angelopoulos et al. 2022):

    L_t = |newly burned outside the envelope| / |newly burned|

and a single knob `theta` per horizon is moved online to keep the average
L_t near alpha. This is not the split-CRC algorithm of that paper (which
needs exchangeable calibration data) but an online, ACI-style controller
(Gibbs & Candes 2021) on the same loss. Two controllers are available:

- `OnlineEnvelope` ("aci"), the original and the engine's default: one
  fixed step size,
      theta <- clip(theta - lr * (L_t - alpha))
- `DtACIEnvelope` ("dtaci"): several such controllers with
  different step sizes, combined by exponentially weighted averaging with
  fixed share, after Gibbs & Candes's DtACI (2024). Each expert's weight is
  scored on the integrated risk of what it would have shown; see the class.
  In eval.conformal_compare it gave tighter envelopes but missed more than
  "aci", and recovered no faster after wind shifts, so it is not the default.

theta maps to the envelope as: lambda = max(theta, lam_min), and below lam_min
(one rollout out of N), margin = ceil((lam_min - theta) / MARGIN_STEP) cells of
dilation around the lam_min set, up to MAX_MARGIN. That makes the envelopes
nested: lowering theta never removes a cell. So each cell has a score, the
largest theta whose envelope still holds it (`envelope_scores`), and

    C(theta) = {cells with score >= theta}  (plus what is already alight)

A matured forecast's loss at *any* theta is then a count over the scores of
the cells that newly burned (`RiskCurve`). That is what lets DtACI score
every expert on the same forecast, and it flags forecasts that even the
widest envelope (theta at its floor) can't bring to alpha ("infeasible").

Misses are measured in area, not cells, so the target means the same thing
on maps of different resolution. Forecasts mature with a delay (h minutes)
and several are in flight at once. Every update uses only what was known at
issue (the score map, and each controller's knobs as they were then) and
what has burned by the forecast's own horizon, however late it is scored.
"""

import math
from collections import deque
from dataclasses import dataclass, field

import numpy as np

ALPHA = 0.1  # the target: on average at most 10% of new burning outside the envelope
LR = 0.1  # the fixed-rate controller's step (eval.run: 0.05 too slow after shifts, 0.2 jumpy)
MARGIN_STEP = 0.02  # theta below lam_min buys one cell of margin per step
MAX_MARGIN = 10  # cells
WINDOW = 20  # forecasts in the "recent" miss rate shown to the operator

# DtACI-inspired controller. The step sizes span 32x around LR, so one expert
# is the old controller. DTACI_INTERVAL is I, the number of scored forecasts
# over which the weights should be able to switch to a different expert;
# about a WINDOW. Fixed share is sigma = 1 / (2I) as in DtACI; eta is the
# standard fixed-share Hedge step for losses with range B over I rounds,
# sqrt(8 ln(2kI) / I) / B (Herbster & Warmuth 1998; Cesa-Bianchi & Lugosi
# 2006). Set before running the comparison in eval.conformal_compare; that
# eval also sweeps I and multiples of eta (the observed loss gaps between
# experts are ~100x below the worst case, so eta x1 barely moves the weights).
DTACI_RATES = (0.0125, 0.025, 0.05, 0.1, 0.2, 0.4)
DTACI_INTERVAL = 20


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


def theta_floor(lam_min: float, max_margin: int = MAX_MARGIN) -> float:
    """The lowest useful theta: cutoff lam_min plus max_margin cells, the widest envelope."""
    return lam_min - max_margin * MARGIN_STEP


def is_widest(theta: float, lam_min: float, max_margin: int = MAX_MARGIN) -> bool:
    """True when theta shows the widest envelope (cutoff lam_min, full margin):
    margins are whole cells, so that is any theta within a step of the floor."""
    return theta < theta_floor(lam_min, max_margin) + MARGIN_STEP


def envelope_scores(p: np.ndarray, lam_min: float, max_margin: int = MAX_MARGIN) -> np.ndarray:
    """float64 (H, W): per cell, the largest theta whose envelope holds it;
    -inf beyond the widest envelope. A cell with p >= lam_min is inside
    exactly when theta <= p. One d king moves from that set is inside when
    margin(theta) >= d, i.e. theta < lam_min - (d - 1) * MARGIN_STEP; the
    nextafter turns that strict < into the >= of `C = scores >= theta`."""
    core = p >= lam_min
    s = np.where(core, p.astype(np.float64), -np.inf)
    reach = core
    for d in range(1, max_margin + 1):
        grown = dilate(reach, 1)
        s[grown & ~reach] = np.nextafter(lam_min - (d - 1) * MARGIN_STEP, -np.inf)
        reach = grown
    return s


@dataclass
class ScoreMap:
    """envelope_scores, stored compactly: a forecast's probabilities take at
    most N + 1 values, plus one per margin ring, so each cell keeps a small
    code into a sorted table of values."""

    codes: np.ndarray  # uint8/uint16 (H, W)
    values: np.ndarray  # float64, sorted ascending; may start with -inf

    @classmethod
    def of(cls, p: np.ndarray, lam_min: float, max_margin: int = MAX_MARGIN) -> "ScoreMap":
        values, inverse = np.unique(envelope_scores(p, lam_min, max_margin), return_inverse=True)
        dtype = np.uint8 if len(values) <= 256 else np.uint16 if len(values) <= 65536 else np.uint32
        return cls(inverse.reshape(p.shape).astype(dtype), values)

    def envelope(self, theta: float) -> np.ndarray:
        """bool (H, W): C(theta)."""
        return self.codes >= np.searchsorted(self.values, theta, side="left")

    def curve(self, cells: np.ndarray) -> "RiskCurve":
        """The loss curve over the cells in bool mask `cells` (e.g. the newly burned)."""
        counts = np.bincount(self.codes[cells].ravel(), minlength=len(self.values))
        keep = counts > 0
        return RiskCurve(self.values[keep], counts[keep])


@dataclass
class RiskCurve:
    """L(theta) for one matured forecast: the share of its newly burned area
    outside C(theta), from the scores of the cells that newly burned (as
    distinct values and their counts). Non-decreasing in theta."""

    values: np.ndarray  # sorted ascending
    counts: np.ndarray

    @property
    def n(self) -> int:
        return int(self.counts.sum())

    def loss(self, theta) -> np.ndarray | float:
        """Share of the cells with score < theta (missed at theta). Vectorized over theta."""
        cum = np.concatenate([[0], np.cumsum(self.counts)])
        out = cum[np.searchsorted(self.values, np.asarray(theta, np.float64), side="left")] / self.n
        return float(out) if np.ndim(out) == 0 else out

    def integral(self, theta, lo: float) -> np.ndarray | float:
        """The integral of L(u) for u from lo to theta (theta >= lo): for each
        cell, the length of [lo, theta] above its score. Vectorized over theta."""
        t = np.asarray(theta, np.float64)
        gap = np.maximum(0.0, t[..., None] - np.maximum(self.values, lo))
        out = (gap * self.counts).sum(axis=-1) / self.n
        return float(out) if np.ndim(out) == 0 else out

    def capped(self, lam_min: float, max_margin: int) -> "RiskCurve":
        """The same forecast with at most max_margin cells of margin (scores
        of farther rings become -inf). For asking what a different cap would do."""
        cut = np.nextafter(lam_min - (max_margin - 1) * MARGIN_STEP, -np.inf)
        v = np.where(self.values >= cut, self.values, -np.inf)
        u, inv = np.unique(v, return_inverse=True)
        return RiskCurve(u, np.bincount(inv, weights=self.counts).astype(np.int64))


@dataclass
class _Controller:
    """What both controllers share: the theta -> envelope mapping, and the
    running record of how the shown envelopes did."""

    lam_min: float  # the smallest probability a forecast can express, 1/N
    alpha: float = ALPHA
    max_margin: int = MAX_MARGIN
    scored: int = 0
    total_miss: float = 0.0
    recent: deque = field(default_factory=lambda: deque(maxlen=WINDOW))
    empty: int = 0  # matured forecasts where nothing new burned: 0/0, no update
    saturated: int = 0  # scored envelopes shown at the widest setting
    infeasible: int = 0  # scored forecasts where even the widest envelope missed more than alpha

    # Subclasses provide `theta`, the knob the next envelope is shown with.

    @property
    def floor(self) -> float:
        return theta_floor(self.lam_min, self.max_margin)

    @property
    def threshold(self) -> float:
        return max(self.theta, self.lam_min)

    @property
    def margin(self) -> int:
        if self.theta >= self.lam_min:
            return 0
        return min(self.max_margin, math.ceil((self.lam_min - self.theta) / MARGIN_STEP))

    def envelope(self, p: np.ndarray, already: np.ndarray | None = None) -> np.ndarray:
        """bool (H, W): where the fire is expected by the horizon. `already`
        (burning or burned now) is always inside."""
        s = ScoreMap.of(p, self.lam_min, self.max_margin).envelope(self.theta)
        if already is not None:
            s |= already
        return s

    def state(self):
        """What to remember at issue, to score this forecast later."""
        raise NotImplementedError

    def learn(self, curve: RiskCurve, issued) -> float:
        """Score one matured forecast, given its loss curve and state() as it
        was at issue. Returns the shown envelope's miss."""
        raise NotImplementedError

    def update(self, envelope: np.ndarray, newly_burned: np.ndarray) -> float | None:
        """Score one forecast from masks alone: the envelope that was shown and
        what newly burned. Only the shown miss is known this way, so only the
        fixed-rate controller supports it. None when nothing new burned."""
        raise NotImplementedError

    def _record(self, miss: float, shown: float, curve: RiskCurve) -> None:
        self.scored += 1
        self.total_miss += miss
        self.recent.append(miss)
        self.saturated += is_widest(shown, self.lam_min, self.max_margin)
        self.infeasible += curve.loss(self.floor) > self.alpha

    @property
    def miss_overall(self) -> float | None:
        return None if self.scored == 0 else self.total_miss / self.scored

    @property
    def miss_recent(self) -> float | None:
        return None if not self.recent else float(np.mean(self.recent))


@dataclass
class OnlineEnvelope(_Controller):
    """The original fixed-rate controller ("aci"), kept as the baseline:
    theta <- clip(theta - lr * (miss of the shown envelope - alpha), floor, 1).
    The step uses the envelope shown at issue and applies to theta now."""

    theta: float = 0.2  # warm start, e.g. from eval.run's lambda_for_fnr_10pct
    lr: float = LR

    def state(self) -> float:
        return self.theta

    def _step(self, miss: float) -> None:
        self.theta = float(np.clip(self.theta - self.lr * (miss - self.alpha), self.floor, 1.0))

    def learn(self, curve: RiskCurve, issued: float) -> float:
        miss = curve.loss(issued)
        self._step(miss)
        self._record(miss, issued, curve)
        return miss

    def update(self, envelope: np.ndarray, newly_burned: np.ndarray) -> float | None:
        area = int(newly_burned.sum())
        if area == 0:
            self.empty += 1
            return None
        miss = float((newly_burned & ~envelope).sum()) / area
        self._step(miss)
        self.scored += 1
        self.total_miss += miss
        self.recent.append(miss)
        return miss


@dataclass
class DtACIEnvelope(_Controller):
    """The DtACI-inspired controller ("dtaci"): k experts, each the fixed-rate
    controller with its own step gamma_i, and the shown knob is their
    weighted average, theta = sum_i w_i theta_i (envelopes are nested, so this
    is always a valid knob). When a forecast issued at s matures:

    1. Weights. Expert i is charged what its own knob theta_i(s) would have
       cost on that forecast, under the integrated risk

           f(theta) = integral from floor to theta of (L(u) - alpha) du,

       convex in theta because L is non-decreasing, with gradient L - alpha:
       the controller's own update is gradient descent on f, as ACI is on
       the pinball loss (for a 0/1 loss, f is the pinball loss up to a
       constant). Then, as in DtACI,
           w_i <- w_i exp(-eta f(theta_i(s))),  normalized,
           w_i <- (1 - sigma) w_i + sigma / k   (fixed share: no expert's
                                                  weight dies, so it can recover)
    2. Experts. theta_i <- clip(theta_i - gamma_i (L(theta_i(s)) - alpha), floor, 1),
       each on its own counterfactual miss.

    Feedback arrives h minutes late, so both steps use each expert's knob as
    it was at issue (its delayed loss) and apply to the weights and knobs as
    they are now. Nothing uses an outcome before its horizon has passed.

    Differences from DtACI as published: the loss is a fractional area loss,
    not 0/1 miscoverage, so f replaces the pinball loss; the output is the
    deterministic weighted average (the paper's practical variant); feedback
    is delayed; and knobs are clipped to the envelopes that exist. Its
    guarantees are not claimed here (see AI_README.md)."""

    theta0: float = 0.2
    rates: tuple[float, ...] = DTACI_RATES
    interval: int = DTACI_INTERVAL
    eta_scale: float = 1.0  # multiplies the worst-case eta (eval.conformal_compare selects it)
    experts: np.ndarray = field(init=False)
    weights: np.ndarray = field(init=False)
    eta: float = field(init=False)
    sigma: float = field(init=False)

    def __post_init__(self) -> None:
        k = len(self.rates)
        self.experts = np.full(k, float(self.theta0))
        self.weights = np.full(k, 1.0 / k)
        self.sigma = 1.0 / (2 * self.interval)
        # f differs between two knobs by at most max(alpha, 1 - alpha) times their distance.
        span = max(self.alpha, 1 - self.alpha) * (1.0 - self.floor)
        self.eta = self.eta_scale * math.sqrt(8 * math.log(2 * k * self.interval) / self.interval) / span

    @property
    def theta(self) -> float:
        return float(np.clip(self.weights @ self.experts, self.floor, 1.0))  # clip: float roundoff only

    def state(self) -> tuple[np.ndarray, float]:
        return self.experts.copy(), self.theta

    def learn(self, curve: RiskCurve, issued: tuple[np.ndarray, float]) -> float:
        experts_then, shown = issued
        miss = curve.loss(shown)
        f = curve.integral(experts_then, self.floor) - self.alpha * (experts_then - self.floor)
        w = self.weights * np.exp(-self.eta * (f - f.min()))
        w /= w.sum()
        self.weights = (1 - self.sigma) * w + self.sigma / len(w)
        own = curve.loss(experts_then)
        self.experts = np.clip(self.experts - np.asarray(self.rates) * (own - self.alpha), self.floor, 1.0)
        self._record(miss, shown, curve)
        return miss


METHODS = {"aci": OnlineEnvelope, "dtaci": DtACIEnvelope}
METHOD = "aci"  # what the engine uses: "dtaci" missed more in eval.conformal_compare (#227)


def make_controller(method: str, warm: float, lam_min: float, lr: float = LR, **kw) -> _Controller:
    if method == "aci":
        return OnlineEnvelope(lam_min=lam_min, theta=warm, lr=lr, **kw)
    if method == "dtaci":
        return DtACIEnvelope(lam_min=lam_min, theta0=warm, **kw)
    raise ValueError(f"unknown envelope method {method!r}")


@dataclass
class _Issued:
    issue_tick: int
    mature_tick: int
    horizon: int  # index into the envelopes
    scores: ScoreMap  # this forecast's scores, so any knob's envelope can be scored
    state: object  # the controller's state() at issue
    unburned: np.ndarray  # bool (H, W): fuel not yet alight at issue


@dataclass
class Scored:
    """One matured forecast, for evals: what was shown and how it did."""

    horizon: int
    issue_tick: int
    mature_tick: int
    miss: float
    theta: float  # the knob it was shown with
    curve: RiskCurve


class EnvelopeLedger:
    """Keeps each shown envelope until its horizon passes, then scores it.
    One controller per horizon; call issue() when a forecast lands and
    mature() after every fire step. Horizons are calibrated independently."""

    def __init__(self, horizons_ticks: tuple[float, ...], warm: tuple[float, ...], n_rollouts: int,
                 lr: float = LR, method: str = METHOD, record: bool = False, **kw) -> None:
        self.horizons_ticks = horizons_ticks
        self.method = method
        self.envs = [make_controller(method, w, 1.0 / n_rollouts, lr=lr, **kw) for w in warm]
        self._pending: list[_Issued] = []
        self.log: list[Scored] | None = [] if record else None

    def issue(self, tick: int, probability: np.ndarray, state_lit: np.ndarray, state_fuel: np.ndarray) -> list[np.ndarray]:
        """Envelopes for a forecast issued at `tick` (probability (K, H, W)),
        remembered for scoring. Returns them, one per horizon."""
        out = []
        for i, (env, h) in enumerate(zip(self.envs, self.horizons_ticks)):
            sm = ScoreMap.of(probability[i], env.lam_min, env.max_margin)
            state = env.state()
            self._pending.append(_Issued(tick, tick + int(math.ceil(h)), i, sm, state, state_fuel.copy()))
            out.append(sm.envelope(env.theta) | state_lit)
        return out

    def mature(self, tick: int, state_lit: np.ndarray, burn_tick: np.ndarray | None = None) -> list[tuple[int, float]]:
        """Score every envelope whose horizon has passed, oldest first.
        Returns (horizon index, miss) for each one scored. With `burn_tick`
        (the tick each cell first caught, inf if not yet), a forecast scored
        late is judged on what burned by its own horizon, not since."""
        done = [p for p in self._pending if p.mature_tick <= tick]
        self._pending = [p for p in self._pending if p.mature_tick > tick]
        out = []
        for p in sorted(done, key=lambda p: (p.mature_tick, p.issue_tick)):
            env = self.envs[p.horizon]
            lit = state_lit if burn_tick is None else burn_tick <= p.mature_tick
            newly = lit & p.unburned
            if not newly.any():
                env.empty += 1  # nothing new burned: no information about missed area
                continue
            curve = p.scores.curve(newly)
            shown = p.state[1] if isinstance(p.state, tuple) else p.state
            miss = env.learn(curve, p.state)
            out.append((p.horizon, miss))
            if self.log is not None:
                self.log.append(Scored(p.horizon, p.issue_tick, p.mature_tick, miss, float(shown), curve))
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
