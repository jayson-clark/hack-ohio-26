"""Crew placement recommendations (PLAN.md, Crew recommendations).

1. Candidates: unburned cells on the predicted front (0.2 <= P(burn by T+30)
   <= 0.8), weighted by how many people live nearby, thinned so no two are
   closer than a crew's reach.
2. Paired what-ifs: one rollout_paired batch runs "no new crew" plus "a crew
   dug in here" for every candidate on the same random draws, so each
   difference is the crew's effect rather than luck.
3. Score: population-weighted share of each town the fire reaches, plus a
   little for acres. Benefit = baseline loss - loss with the crew, averaged
   over rollouts.
4. Winner's curse: the best of K noisy estimates is biased upward, so the
   top picks are re-run on fresh seeds and those numbers are what's shown.

Runs in its own worker process (Recommender), like the forecaster.
"""

import asyncio
import math
import multiprocessing
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field, replace

import numpy as np

from forecast.rollout import rollout_paired
from sim.effects import CREW_RADIUS, TimedLayer, crew_layer
from sim.fire import FUEL, SIM_MINUTES_PER_TICK, FireSnapshot
from uq.mc import benefit_confidence, mean_ci, overlap, wilson

N_CANDIDATES = 8
N_ROLLOUTS = 8
# The fresh-seed check that decides what's shown. More rollouts than the
# search pass, because the shown benefit has to clear zero at its lower bound.
HOLDOUT_ROLLOUTS = 16
# When the top two can't be told apart, they're re-run head to head on fresh seeds with this many.
REFINE_ROLLOUTS = 16
TOP = 3
HORIZON_TICKS = 60  # the commander's what-ifs (evaluate_spots) speak in "the next hour"
# Recommendations look further: a crew sent now takes 15-40 min to arrive, so
# a one-hour window left it arriving with the fire in strong wind. They're
# scored over two hours, and candidates come from both the 30-minute front and
# where the long forecast expects fire in 60-120 min.
REC_HORIZON_TICKS = 120
ARRIVAL_PCTL = 10  # "fire reaches the crew's area" = the early end across rollouts
FRONT_BAND = (0.2, 0.8)  # P(burn by T+30) range that counts as "the front"
AHEAD_BAND = FRONT_BAND  # the same band on P(burn by T+90), from the long forecast
NEAR_TOWN_CELLS = 25.0  # candidates are weighted by population within ~this distance
# Person-equivalents per burned cell, so acres break ties without
# outweighing people (Paradise is about 7 people per cell).
ACRE_WEIGHT = 0.2
# Smallest drop in a town's burned share worth mentioning (2% of the town).
MIN_SHARE = 0.02


@dataclass(frozen=True)
class TownInfo:
    name: str
    x: float
    y: float
    radius: float  # cells
    population: int


@dataclass
class TownEffect:
    town: str
    hits: int  # rollouts where the crew changes whether fire reaches the town
    n: int
    lo: float = 0.0  # 90% Wilson interval on hits / n
    hi: float = 1.0


@dataclass
class TownShare:
    town: str
    share: float  # mean drop in the fraction of the town that burns by T+60, 0..1


@dataclass
class Rec:
    x: float
    y: float
    benefit: float  # mean person-equivalents spared per rollout
    cells_saved: float  # mean burned cells avoided per rollout
    cells_lo: float = 0.0  # 90% interval on cells_saved (paired t)
    cells_hi: float = 0.0
    benefit_lo: float = 0.0  # 90% interval on `benefit` (paired t over rollouts)
    benefit_hi: float = 0.0
    confidence: str = "low"  # how firmly to state it: high / moderate / low
    saves: list[TownEffect] = field(default_factory=list)  # baseline reaches the town, crew stops it
    worsens: list[TownEffect] = field(default_factory=list)  # the reverse (fire deflected onto it)
    protects: list[TownShare] = field(default_factory=list)  # towns where less burns, biggest first
    # Minutes for the unit to get there (#104); None when units appear instantly.
    eta_min: float | None = None
    # Minutes until fire likely reaches the crew's area (the ARRIVAL_PCTL early
    # end across rollouts), and the latest the crew can be sent and still dig in
    # first (arrival minus eta). None when fire isn't expected there in the horizon.
    fire_arrival_min: float | None = None
    act_by_min: float | None = None
    # Set when every crew is already placed (#77): move this crew here instead.
    move_id: str | None = None
    from_x: float | None = None
    from_y: float | None = None
    # Set for "relieve this crew" (#178): a fresh crew takes over this order.
    relieve_id: str | None = None


@dataclass(frozen=True)
class PlacedCrew:
    """A crew on the table, the snapshot as it would be without it, and the
    crew itself as a suppression layer (continuing its ramp-up where it is)."""

    id: str
    x: float
    y: float
    without: FireSnapshot  # same fire, suppression (and its schedule) without this crew
    keep: TimedLayer | np.ndarray  # this crew staying where it is
    eta: np.ndarray | None = None  # minutes for this crew to reach each cell from where it is (#104)


@dataclass(frozen=True)
class TiredCrew:
    """A working crew that tires inside the look-ahead (#178), and how soon
    the fastest free crew could take over from it."""

    id: str
    x: float
    y: float
    without: FireSnapshot  # same fire, suppression (and its schedule) without this crew
    keep: TimedLayer  # this crew carrying on, tiring (its fade_at is in the look-ahead)
    relief_at: int  # ticks until a fresh crew could take over
    relief_eta_min: float  # the same, in minutes, for the card


def candidates(snapshot: FireSnapshot, p30: np.ndarray, towns: list[TownInfo], k: int = N_CANDIDATES,
               spacing: float = 2 * CREW_RADIUS) -> list[tuple[float, float]]:
    """Up to k (x, y) spots on the predicted front, best first, at least
    `spacing` apart (a crew's reach, 2 x CREW_RADIUS, by default)."""
    h, w = p30.shape
    lo, hi = FRONT_BAND
    band = (p30 >= lo) & (p30 <= hi) & (snapshot.state == FUEL)
    if not band.any() or not towns:
        return []
    cy, cx = np.mgrid[:h, :w].astype(np.float32) + 0.5
    near = np.zeros((h, w), np.float32)
    for t in towns:
        near += t.population * np.exp(-np.hypot(cx - t.x, cy - t.y) / NEAR_TOWN_CELLS)
    score = np.where(band, near * (1.0 - np.abs(p30 - 0.5)), -1.0)
    picks = []
    for _ in range(k):
        i = int(np.argmax(score))
        if score.flat[i] <= 0:
            break
        y, x = divmod(i, w)
        picks.append((x + 0.5, y + 0.5))
        score[np.hypot(cx - (x + 0.5), cy - (y + 0.5)) < spacing] = -1.0
    return picks


# Screening with the learned fire emulator (#113): a bigger, denser pool of
# spots on the front, ranked by the emulator's predicted benefit, and only
# the best N_CANDIDATES go on to the paired Monte Carlo that every shown
# number comes from. Without the emulator, candidates() picks as before.
SCREEN_POOL = 48
SCREEN_SPACING = CREW_RADIUS


def screen(snapshot, p30, towns, masks, emulator, eta=None, k: int = N_CANDIDATES, ahead=None) -> list[tuple[float, float]]:
    """The k most promising spots by the emulator's predicted T+60 loss
    reduction, at least a crew's reach apart. Falls back to candidates()."""
    pool = _reachable(_pool(snapshot, p30, ahead, towns, SCREEN_POOL, SCREEN_SPACING), eta)
    if len(pool) <= k:
        return pool
    from emulator.features import SUP_TICKS, from_snapshot

    h, w = snapshot.state.shape
    base = emulator.inputs(snapshot) if hasattr(emulator, "inputs") else from_snapshot(snapshot)
    batch = np.repeat(base[None], len(pool) + 1, axis=0)
    for i, (x, y) in enumerate(pool, start=1):
        layer = crew_layer(w, h, x, y, t_on=_arrival(eta, x, y)[0], wind_from=snapshot.wind.from_deg)
        for j, t in enumerate(SUP_TICKS):
            if (g := layer.grid(t)) is not None:
                np.maximum(batch[i, 11 + j], g, out=batch[i, 11 + j])
    p60 = np.concatenate([emulator.predict(batch[i : i + 16]) for i in range(0, len(batch), 16)])[:, 1]
    area = masks.reshape(len(towns), -1).sum(axis=1)
    pop = np.array([t.population for t in towns], np.float32)
    weight = (masks * (pop / np.maximum(area, 1.0))[:, None, None]).sum(axis=0) + ACRE_WEIGHT
    # Burning and burned cells are certain either way, so they cancel out.
    gain = ((p60[0] - p60[1:]) * weight).sum(axis=(1, 2))
    picks: list[tuple[float, float]] = []
    for i in np.argsort(-gain):
        x, y = pool[i]
        if all(math.hypot(x - a, y - b) >= 2 * CREW_RADIUS for a, b in picks):
            picks.append((x, y))
        if len(picks) == k:
            break
    return picks


def _town_masks(towns: list[TownInfo], h: int, w: int) -> np.ndarray:
    cy, cx = np.mgrid[:h, :w].astype(np.float32) + 0.5
    return np.stack([np.hypot(cx - t.x, cy - t.y) <= t.radius for t in towns]).astype(np.float32)


def evaluate_spots(snapshot, spots, towns, n=N_ROLLOUTS, seed=0, starts: list[int] | None = None) -> list[Rec]:
    """Paired effect of a crew at each (x, y), without picking or re-running.
    `starts` are the ticks until each crew could be there (#104); default now."""
    h, w = snapshot.state.shape
    return _evaluate(snapshot, spots, towns, _town_masks(towns, h, w), n, seed, starts=starts)


def _evaluate(snapshot, spots, towns, masks, n, seed, keep=None, starts: list[int] | None = None,
              horizon: int = HORIZON_TICKS) -> list[Rec]:
    """Paired run of the baseline plus a fresh crew at each spot, digging in
    from its start tick (0 = now; later if it has to travel there, #104) and
    ramping up as a placed crew does (#56).

    With `keep` (a TimedLayer or grid), the comparison baseline is instead
    "snapshot plus keep": that's how a move is scored, as the snapshot without
    the crew, then either the crew where it is (keep) or at the new spot."""
    h, w = snapshot.state.shape
    starts = starts or [0] * len(spots)
    # Each crew cuts its line along the wind it arrives in (#99).
    variants = [crew_layer(w, h, x, y, t_on=t0, wind_from=snapshot.wind.from_deg) for (x, y), t0 in zip(spots, starts)]
    if keep is not None:
        variants = [keep] + variants
    first = rollout_paired(snapshot, n, horizon, variants, seed=seed)
    if keep is not None:
        first = first[1:]  # index 0 is now "crew where it is"
    return _score(first, spots, towns, masks, n)


def _score(first: np.ndarray, spots, towns, masks, n) -> list[Rec]:
    """Recs from paired first-burn ticks (V, n, H, W): index 0 is the
    comparison baseline, index v the variant for spots[v - 1]."""
    h, w = first.shape[2:]
    burned = np.isfinite(first).reshape(len(spots) + 1, n, h * w).astype(np.float32)
    area = masks.reshape(len(towns), -1).sum(axis=1)
    frac = burned @ masks.reshape(len(towns), -1).T / np.maximum(area, 1.0)  # (V, n, T)
    pop = np.array([t.population for t in towns], np.float32)
    cells = burned.sum(axis=2)  # (V, n)
    loss = frac @ pop + ACRE_WEIGHT * cells  # (V, n)
    reached = frac > 0
    recs = []
    def effects(counts):
        return [TownEffect(t.name, int(c), n, *wilson(int(c), n)) for t, c in zip(towns, counts) if c > 0]

    cy, cx = np.mgrid[:h, :w].astype(np.float32) + 0.5
    for v, (x, y) in enumerate(spots, start=1):
        # When fire reaches the crew's core area in the baseline (per rollout).
        core = np.hypot(cx - x, cy - y) <= 0.6 * CREW_RADIUS
        reach = first[0][:, core].min(axis=1) * SIM_MINUTES_PER_TICK  # (n,), inf if never
        arrival = float(np.percentile(reach, ARRIVAL_PCTL)) if np.isfinite(reach).mean() > ARRIVAL_PCTL / 100 else None
        saves = (reached[0] & ~reached[v]).sum(axis=0)
        share = (frac[0] - frac[v]).mean(axis=0)  # (T,)
        worse = (~reached[0] & reached[v]).sum(axis=0)
        # Paired: each rollout's difference is the crew's effect on identical luck.
        mean, lo, hi = mean_ci(loss[0] - loss[v])
        recs.append(Rec(
            x=round(x, 2), y=round(y, 2),
            benefit=mean, benefit_lo=lo, benefit_hi=hi, confidence=benefit_confidence(mean, lo, hi),
            fire_arrival_min=None if arrival is None else round(arrival, 1),
            cells_saved=float((cells[0] - cells[v]).mean()),
            cells_lo=mean_ci(cells[0] - cells[v])[1], cells_hi=mean_ci(cells[0] - cells[v])[2],
            saves=effects(saves),
            worsens=effects(worse),
            protects=sorted(
                (TownShare(t.name, round(float(d), 3)) for t, d in zip(towns, share) if d >= MIN_SHARE),
                key=lambda e: e.share, reverse=True,
            ),
        ))
    return recs


def recommend_reliefs(tired: list[TiredCrew], towns: list[TownInfo], *, n: int = HOLDOUT_ROLLOUTS,
                      seed: int = 0, horizon: int = REC_HORIZON_TICKS) -> list[Rec]:
    """"Relieve this crew" (#178), for each working crew that tires inside
    the look-ahead. One paired batch per crew: the fire without it, with it
    carrying on (tiring from its fade_at), and with a fresh crew taking over
    at relief_at on the same ground and line. A relief's benefit is "carries
    on" minus "relieved", on identical luck. There's one candidate per crew,
    so no selection to correct for: each runs once on HOLDOUT_ROLLOUTS, and
    only reliefs that help at the low end of their interval are kept (#11),
    like any other card."""
    if not tired or not towns:
        return []
    out = []
    for i, c in enumerate(tired):
        h, w = c.without.state.shape
        fresh = replace(c.keep, relief_at=c.relief_at)
        first = rollout_paired(c.without, n, horizon, [c.keep, fresh], seed=seed + 104729 * (i + 1))[1:]
        [r] = _score(first, [(c.x, c.y)], towns, _town_masks(towns, h, w), n)
        if r.benefit_lo <= 0:
            continue
        r.relieve_id, r.eta_min = c.id, round(c.relief_eta_min, 1)
        # Send relief early enough to arrive before the crew starts to tire.
        r.act_by_min = round(max(c.keep.fade_at, 0) * SIM_MINUTES_PER_TICK - c.relief_eta_min, 1)
        out.append(r)
    return out


def _arrival(eta: np.ndarray | None, x: float, y: float) -> tuple[int, float | None]:
    """(start tick, minutes) for a unit reaching (x, y), from an arrival-time map (#104)."""
    if eta is None:
        return 0, None
    h, w = eta.shape
    m = float(eta[min(max(int(y), 0), h - 1), min(max(int(x), 0), w - 1)])
    if not math.isfinite(m):
        return 10**9, m  # no free unit can get there
    return int(math.ceil(m / SIM_MINUTES_PER_TICK)), m


def _reachable(spots, eta):
    return [s for s in spots if eta is None or math.isfinite(_arrival(eta, *s)[1])]


def _eval_at(snapshot, spots, towns, masks, n, seed, eta, keep=None, horizon: int = REC_HORIZON_TICKS) -> list[Rec]:
    """_evaluate with each crew starting when a unit can get there, plus the
    act-by time: how long the operator can wait and still have it dig in first."""
    arrivals = [_arrival(eta, x, y) for x, y in spots]
    recs = _evaluate(snapshot, spots, towns, masks, n, seed, keep=keep, starts=[a[0] for a in arrivals], horizon=horizon)
    for r, (_, m) in zip(recs, arrivals):
        r.eta_min = None if m is None else round(m, 1)
        if r.fire_arrival_min is not None:
            r.act_by_min = round(r.fire_arrival_min - (m or 0.0), 1)
    return recs


def _pool(snapshot, p30, ahead, towns, k: int, spacing: float) -> list[tuple[float, float]]:
    """Candidate spots on the 30-minute front and, with a look-ahead map
    (P(burn by T+90)), on where the fire is expected in 1-2 h, best first,
    at least `spacing` apart."""
    near = candidates(snapshot, p30, towns, k, spacing=spacing)
    if ahead is None:
        return near
    far = candidates(snapshot, ahead, towns, k, spacing=spacing)
    picks: list[tuple[float, float]] = []
    for spot in [s for pair in zip(near, far) for s in pair] + near[len(far):] + far[len(near):]:
        if all(math.hypot(spot[0] - a, spot[1] - b) >= spacing for a, b in picks):
            picks.append(spot)
    return picks[:k]


def recommend(
    snapshot: FireSnapshot,
    p30: np.ndarray,
    towns: list[TownInfo],
    *,
    k: int = N_CANDIDATES,
    n: int = N_ROLLOUTS,
    top: int = TOP,
    seed: int = 0,
    eta: np.ndarray | None = None,
    screened: bool = False,
    ahead: np.ndarray | None = None,
    horizon: int = REC_HORIZON_TICKS,
) -> list[Rec]:
    """The best `top` crew placements, best first, each re-scored on fresh
    seeds (#11):

    - With `screened` and the learned emulator available (#113), the k spots
      come from screening a bigger pool (screen()); otherwise from candidates().

    - Only placements whose benefit is above zero at the *lower* end of its
      90% interval are kept. A mean that might be luck isn't recommended.
    - If the top two still overlap, so the data can't say which is better,
      they're re-run head to head on more rollouts, rather than spending more
      rollouts on every candidate.
    - With `eta` (minutes for the fastest free crew to reach each cell, #104),
      each candidate's crew only starts digging in when it could get there,
      and spots no free crew can reach are skipped.
    - With `ahead` (P(burn by T+90), from the long forecast), half the
      candidates sit where the fire is expected in 1-2 h, so a crew can be
      there first. Every candidate is scored over REC_HORIZON_TICKS.
    """
    h, w = snapshot.state.shape
    masks = _town_masks(towns, h, w)
    emulator = _emulator() if screened else None
    if emulator is not None and towns:
        spots = screen(snapshot, p30, towns, masks, emulator, eta, k, ahead=ahead)
    else:
        spots = _reachable(_pool(snapshot, p30, ahead, towns, k, 2 * CREW_RADIUS), eta)
    if not spots:
        return []
    first_pass = _eval_at(snapshot, spots, towns, masks, n, seed, eta, horizon=horizon)
    best = sorted(first_pass, key=lambda r: r.benefit, reverse=True)[:top]
    held_out = sorted(_eval_at(snapshot, [(r.x, r.y) for r in best], towns, masks, HOLDOUT_ROLLOUTS, seed + 7919, eta,
                               horizon=horizon),
                      key=lambda r: r.benefit, reverse=True)
    if len(held_out) >= 2 and overlap((held_out[0].benefit_lo, held_out[0].benefit_hi),
                                      (held_out[1].benefit_lo, held_out[1].benefit_hi)):
        pair = _eval_at(snapshot, [(r.x, r.y) for r in held_out[:2]], towns, masks, REFINE_ROLLOUTS, seed + 15485, eta,
                        horizon=horizon)
        held_out = sorted(pair + held_out[2:], key=lambda r: r.benefit, reverse=True)
    return [r for r in held_out if r.benefit_lo > 0]


def recommend_moves(
    crews: list[PlacedCrew],
    p30: np.ndarray,
    towns: list[TownInfo],
    *,
    k: int = N_CANDIDATES - 2,
    n: int = N_ROLLOUTS,
    top: int = TOP,
    seed: int = 0,
) -> list[Rec]:
    """When every crew is placed (#77): the best `top` moves of one crew to a
    new spot, best first. For each crew, one paired batch runs the fire
    without it, then with it where it is, then with it at each candidate;
    a move's benefit is "where it is" minus "at the new spot". The best moves
    are re-run on fresh seeds and only ones that still help are kept.

    A moved crew digs in again from scratch (#56), so a move has to beat the
    crew staying put even after losing its ramp-up."""
    if not crews or not towns:
        return []
    h, w = p30.shape
    masks = _town_masks(towns, h, w)
    found: list[tuple[PlacedCrew, Rec]] = []
    for i, crew in enumerate(crews):
        spots = [s for s in _reachable(candidates(crew.without, p30, towns, k), crew.eta)
                 if all(np.hypot(s[0] - c.x, s[1] - c.y) >= 2 * CREW_RADIUS for c in crews)]
        if not spots:
            continue
        for r in _eval_at(crew.without, spots, towns, masks, n, seed + i, crew.eta, keep=crew.keep):
            found.append((crew, r))
    # Distinct moves: each crew moves at most once, and no two crews go to the same spot.
    best: list[tuple[PlacedCrew, Rec]] = []
    for crew, r in sorted(found, key=lambda cr: cr[1].benefit, reverse=True):
        if len(best) == top:
            break
        if any(c.id == crew.id or np.hypot(r.x - o.x, r.y - o.y) < 2 * CREW_RADIUS for c, o in best):
            continue
        best.append((crew, r))
    out = []
    for j, (crew, r) in enumerate(best):
        [again] = _eval_at(crew.without, [(r.x, r.y)], towns, masks, HOLDOUT_ROLLOUTS, seed + 7919 + j,
                           crew.eta, keep=crew.keep)
        if again.benefit_lo > 0:  # only moves that help at the low end of their interval (#11)
            again.move_id, again.from_x, again.from_y = crew.id, crew.x, crew.y
            out.append(again)
    return sorted(out, key=lambda r: r.benefit, reverse=True)


def _horizon_words() -> str:
    hours = REC_HORIZON_TICKS * SIM_MINUTES_PER_TICK / 60
    return "hour" if hours == 1 else f"{hours:g} hours" if hours != 2 else "two hours"


def describe(rec: Rec, acres_per_cell: float, from_place: str | None = None, station: str | None = None) -> str:
    """One sentence for a recommendation card or a briefing. For a move,
    `from_place` names where the crew is now ("near Pulga"). With dispatch
    (#104), `station` and the rec's ETA say who'd go and how long it takes."""
    acres = rec.cells_saved * acres_per_cell
    if rec.relieve_id is not None:
        who = (f"Relieving this crew with a fresh one from {station}, about {round(rec.eta_min)} minutes out,"
               if station and rec.eta_min is not None else "Relieving this crew before it tires")
    elif rec.move_id is not None:
        who = f"Moving the crew {from_place or 'you placed'} here"
    elif station and rec.eta_min is not None:
        who = f"A crew from {station}, about {round(rec.eta_min)} minutes out,"
    else:
        who = "A crew here"
    if rec.saves:
        best = max(rec.saves, key=lambda e: e.hits)
        text = f"{who} keeps the fire out of {best.town} in {best.hits} of {best.n} simulations"
    elif rec.protects:
        top = rec.protects[0]
        text = f"{who} shields {top.town}: about {round(top.share * 100)}% less of it burns in the next {_horizon_words()}"
    else:
        text = f"{who} holds back about {_round_acres(acres)} acres over the next {_horizon_words()}"
    if rec.worsens:
        worst = max(rec.worsens, key=lambda e: e.hits)
        text += f", but pushes it into {worst.town} in {worst.hits} of {worst.n}"
    return text + "."


def _round_acres(a: float) -> str:
    step = 100 if a >= 1000 else 10
    return f"{max(step, round(a / step) * step):,}"


class Recommender:
    """One worker process for recommendations, separate from the forecaster
    so a slow recommendation never delays the next forecast."""

    def __init__(self) -> None:
        ctx = multiprocessing.get_context("spawn")
        self._pool = ProcessPoolExecutor(max_workers=1, mp_context=ctx)

    def submit(self, snapshot: FireSnapshot, p30: np.ndarray, towns: list[TownInfo], seed: int,
               eta: np.ndarray | None = None, ahead: np.ndarray | None = None,
               tired: list[TiredCrew] | None = None) -> asyncio.Future[list[Rec]]:
        return self.run(_recommend_job, snapshot, p30, towns, seed, eta, ahead, tired)

    def submit_moves(self, crews: list[PlacedCrew], p30: np.ndarray, towns: list[TownInfo], seed: int,
                     tired: list[TiredCrew] | None = None) -> asyncio.Future[list[Rec]]:
        return self.run(_moves_job, crews, p30, towns, seed, tired)

    def run(self, fn, *args) -> asyncio.Future:
        """Any other picklable analysis job (the commander's what-ifs), on
        the same worker so it never competes with the live forecast."""
        loop = asyncio.get_running_loop()
        return loop.run_in_executor(self._pool, fn, *args)

    def warm(self) -> asyncio.Future:
        """Start the worker now (a spawned process takes ~1 s to import
        NumPy), so the first real job doesn't pay for it."""
        return self.run(_noop)

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)


def _noop() -> None:
    return None


_EMULATOR: list = []


def _emulator():
    """The fire emulator, loaded once per worker process; None without MLX or weights."""
    if not _EMULATOR:
        try:
            from emulator.model import load_emulator

            _EMULATOR.append(load_emulator())
        except Exception:  # a broken install shouldn't stop recommendations
            _EMULATOR.append(None)
    return _EMULATOR[0]


def _with_reliefs(recs: list[Rec], tired, towns, seed) -> list[Rec]:
    """Placement or move cards plus relief cards (#178), best first."""
    return sorted(recs + recommend_reliefs(tired or [], towns, seed=seed), key=lambda r: r.benefit, reverse=True)


def _recommend_job(snapshot, p30, towns, seed, eta=None, ahead=None, tired=None):
    return _with_reliefs(recommend(snapshot, p30, towns, seed=seed, eta=eta, screened=True, ahead=ahead),
                         tired, towns, seed)


def _moves_job(crews, p30, towns, seed, tired=None):
    return _with_reliefs(recommend_moves(crews, p30, towns, seed=seed), tired, towns, seed)
