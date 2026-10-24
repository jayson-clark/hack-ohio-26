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
import multiprocessing
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field

import numpy as np

from forecast.rollout import rollout_paired
from sim.effects import CREW_RADIUS, crew_footprint
from sim.fire import FUEL, FireSnapshot

N_CANDIDATES = 8
N_ROLLOUTS = 8
TOP = 3
HORIZON_TICKS = 60
FRONT_BAND = (0.2, 0.8)  # P(burn by T+30) range that counts as "the front"
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
    saves: list[TownEffect] = field(default_factory=list)  # baseline reaches the town, crew stops it
    worsens: list[TownEffect] = field(default_factory=list)  # the reverse (fire deflected onto it)
    protects: list[TownShare] = field(default_factory=list)  # towns where less burns, biggest first


def candidates(snapshot: FireSnapshot, p30: np.ndarray, towns: list[TownInfo], k: int = N_CANDIDATES) -> list[tuple[float, float]]:
    """Up to k (x, y) spots on the predicted front, best first, at least a
    crew's reach (2 x CREW_RADIUS) apart."""
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
        score[np.hypot(cx - (x + 0.5), cy - (y + 0.5)) < 2 * CREW_RADIUS] = -1.0
    return picks


def _town_masks(towns: list[TownInfo], h: int, w: int) -> np.ndarray:
    cy, cx = np.mgrid[:h, :w].astype(np.float32) + 0.5
    return np.stack([np.hypot(cx - t.x, cy - t.y) <= t.radius for t in towns]).astype(np.float32)


def _evaluate(snapshot, spots, towns, masks, n, seed) -> list[Rec]:
    """Paired run of the baseline plus a crew at each spot."""
    h, w = snapshot.state.shape
    variants = np.stack([crew_footprint(w, h, x, y) for x, y in spots])
    first = rollout_paired(snapshot, n, HORIZON_TICKS, variants, seed=seed)
    burned = np.isfinite(first).reshape(len(spots) + 1, n, h * w).astype(np.float32)
    area = masks.reshape(len(towns), -1).sum(axis=1)
    frac = burned @ masks.reshape(len(towns), -1).T / np.maximum(area, 1.0)  # (V, n, T)
    pop = np.array([t.population for t in towns], np.float32)
    cells = burned.sum(axis=2)  # (V, n)
    loss = frac @ pop + ACRE_WEIGHT * cells  # (V, n)
    reached = frac > 0
    recs = []
    for v, (x, y) in enumerate(spots, start=1):
        saves = (reached[0] & ~reached[v]).sum(axis=0)
        share = (frac[0] - frac[v]).mean(axis=0)  # (T,)
        worse = (~reached[0] & reached[v]).sum(axis=0)
        recs.append(Rec(
            x=round(x, 2), y=round(y, 2),
            benefit=float((loss[0] - loss[v]).mean()),
            cells_saved=float((cells[0] - cells[v]).mean()),
            saves=[TownEffect(t.name, int(c), n) for t, c in zip(towns, saves) if c > 0],
            worsens=[TownEffect(t.name, int(c), n) for t, c in zip(towns, worse) if c > 0],
            protects=sorted(
                (TownShare(t.name, round(float(d), 3)) for t, d in zip(towns, share) if d >= MIN_SHARE),
                key=lambda e: e.share, reverse=True,
            ),
        ))
    return recs


def recommend(
    snapshot: FireSnapshot,
    p30: np.ndarray,
    towns: list[TownInfo],
    *,
    k: int = N_CANDIDATES,
    n: int = N_ROLLOUTS,
    top: int = TOP,
    seed: int = 0,
) -> list[Rec]:
    """The best `top` crew placements, best first, each re-scored on fresh
    seeds. Placements that don't help on the re-run are dropped."""
    spots = candidates(snapshot, p30, towns, k)
    if not spots:
        return []
    h, w = snapshot.state.shape
    masks = _town_masks(towns, h, w)
    first_pass = _evaluate(snapshot, spots, towns, masks, n, seed)
    best = sorted(first_pass, key=lambda r: r.benefit, reverse=True)[:top]
    held_out = _evaluate(snapshot, [(r.x, r.y) for r in best], towns, masks, n, seed + 7919)
    return [r for r in sorted(held_out, key=lambda r: r.benefit, reverse=True) if r.benefit > 0]


def describe(rec: Rec, acres_per_cell: float) -> str:
    """One sentence for a recommendation card or a briefing."""
    acres = rec.cells_saved * acres_per_cell
    if rec.saves:
        best = max(rec.saves, key=lambda e: e.hits)
        text = f"A crew here keeps the fire out of {best.town} in {best.hits} of {best.n} simulations"
    elif rec.protects:
        top = rec.protects[0]
        text = f"A crew here shields {top.town}: about {round(top.share * 100)}% less of it burns in the next hour"
    else:
        text = f"A crew here holds back about {_round_acres(acres)} acres over the next hour"
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

    def submit(self, snapshot: FireSnapshot, p30: np.ndarray, towns: list[TownInfo], seed: int) -> asyncio.Future[list[Rec]]:
        loop = asyncio.get_running_loop()
        return loop.run_in_executor(self._pool, _recommend_job, snapshot, p30, towns, seed)

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)


def _recommend_job(snapshot, p30, towns, seed):
    return recommend(snapshot, p30, towns, seed=seed)
