"""Headless evaluation of the modeling pieces (#14).

    cd engine && uv run python -m eval.run                       # all schedules, a few episodes each
    cd engine && uv run python -m eval.run --episodes 10 --schedules shift --out report.md --json eval.json

Plays the fire with no UI, for several seeded episodes per wind schedule
(steady, a mid-run shift, gusty), and checks each modeling claim against
what actually happened in the live sim:

- Forecast calibration: do cells given P(burn) = p burn about p of the
  time? Reliability by bin, Brier score, and how much of what actually
  burned each raw contour (P >= 0.1, 0.5) missed: its false-negative rate.
- Arrival-time ranges: how often a cell's actual arrival falls inside the
  rollouts' 5-95% range, and how wide that range is, by lead time.
- Routing: predicted route risk vs routes actually cut before the bus got
  through; forecast-aware routing vs a "current fire only" router; and
  how often routes change on screen (with and without RouteTracker).
- Recommendations: realized benefit of the top recommendation vs a random
  spot on the front, run forward under the episode's real (changing) wind,
  plus predicted vs realized benefit (does the forecast overpromise?).

It also prints warm-start values for the conformal pieces: the λ that
holds each horizon's envelope FNR at 10% (#12), and the 90% quantile of the
arrival-range conformity score per lead bucket (#13).

The "truth" is the live sim, which runs the same fire model as the
forecaster. So this measures what the forecast can't know (wind changes,
luck) and its shortcuts, not the fire model against a real fire (#15).
"""

import argparse
import json
import math
import time
from dataclasses import dataclass, field

import numpy as np

from forecast.recommend import ACRE_WEIGHT, REC_HORIZON_TICKS, TownInfo, _town_masks, candidates, recommend
from forecast.runner import horizon_ticks, run_forecast
from uq.conformal import EnvelopeLedger
from routing.evac import BUS_SPEED_KMH, plan_routes, replan_routes
from routing.roads import load_network
from routing.tracker import RouteTracker
from scenario import load_scenario
from sim.effects import crew_layer
from sim.fire import BURNED, BURNING, FUEL, SIM_MINUTES_PER_TICK, FireSim, Wind, advance

HORIZONS = (30, 60)  # sim minutes
BINS = np.linspace(0, 1, 11)
LAMBDAS = np.round(np.linspace(0.02, 0.9, 45), 3)
LEAD_BUCKETS = ((0, 15), (15, 30), (30, 60))  # sim minutes until the cell burned
# Camp Fire origin, east of Concow, north of Magalia, and between Magalia and
# Paradise (where a north-easterly pushes fire across the Skyway, so routing
# decisions actually get tested).
IGNITIONS = [(217.3, 54.5), (175.0, 70.0), (120.0, 40.0), (75.0, 85.0)]
ALPHA = 0.1
WARM_THETA = (0.2, 0.2)  # the online envelope's starting threshold per horizon (#12)
ENVELOPE_LR = 0.1  # its step size; --envelope-lr overrides


# --- Wind schedules ------------------------------------------------------------

def schedule(name: str, seed: int):
    """wind(tick) for an episode."""
    if name == "steady":
        return lambda t: Wind(10.0, 45.0)
    if name == "shift":
        # North-easterly, then it swings round to come from the west at minute 60.
        return lambda t: Wind(10.0, 45.0) if t < 60 else Wind(10.0, 270.0)
    if name == "gusty":
        rng = np.random.default_rng(seed + 991)
        legs = [(float(rng.uniform(4, 15)), float(45 + rng.normal(0, 35))) for _ in range(64)]
        return lambda t: Wind(*legs[min(t // 15, len(legs) - 1)])
    raise ValueError(f"unknown schedule {name!r}")


# --- Accumulators ----------------------------------------------------------------

@dataclass
class Calibration:
    """Per horizon: reliability bins, Brier, and envelope FNR at every λ."""

    sum_p: np.ndarray = field(default_factory=lambda: np.zeros(10))
    sum_y: np.ndarray = field(default_factory=lambda: np.zeros(10))
    count: np.ndarray = field(default_factory=lambda: np.zeros(10))
    brier: float = 0.0
    cells: int = 0
    missed: np.ndarray = field(default_factory=lambda: np.zeros(len(LAMBDAS)))  # burned but p < λ
    burned: int = 0
    per_forecast_fnr: list[np.ndarray] = field(default_factory=list)  # for the conformal warm start

    def add(self, p: np.ndarray, y: np.ndarray) -> None:
        idx = np.minimum((p * 10).astype(int), 9)
        self.sum_p += np.bincount(idx, weights=p, minlength=10)
        self.sum_y += np.bincount(idx, weights=y, minlength=10)
        self.count += np.bincount(idx, minlength=10)
        self.brier += float(((p - y) ** 2).sum())
        self.cells += len(p)
        burned_p = p[y > 0]
        miss = (burned_p[None, :] < LAMBDAS[:, None]).sum(axis=1)
        self.missed += miss
        self.burned += len(burned_p)
        if len(burned_p):
            self.per_forecast_fnr.append(miss / len(burned_p))


@dataclass
class Arrival:
    """Per lead bucket: coverage and width of the rollouts' 5-95% arrival range."""

    covered: np.ndarray = field(default_factory=lambda: np.zeros(len(LEAD_BUCKETS)))
    total: np.ndarray = field(default_factory=lambda: np.zeros(len(LEAD_BUCKETS)))
    width: np.ndarray = field(default_factory=lambda: np.zeros(len(LEAD_BUCKETS)))
    scores: list[list[float]] = field(default_factory=lambda: [[] for _ in LEAD_BUCKETS])


@dataclass
class Routing:
    bins: dict = field(default_factory=lambda: {k: [0, 0] for k in ("0-10%", "10-25%", "25-50%", "50%+")})
    aware_cut: int = 0
    aware_total: int = 0
    naive_cut: int = 0
    naive_total: int = 0
    differ: int = 0  # routes where the forecast-aware router chose differently from current-fire-only
    differ_aware_cut: int = 0
    differ_naive_cut: int = 0
    raw_changes: int = 0
    shown_changes: int = 0
    town_episodes: int = 0

    def bin(self, risk: float) -> str:
        return "0-10%" if risk < 0.1 else "10-25%" if risk < 0.25 else "25-50%" if risk < 0.5 else "50%+"


@dataclass
class Recs:
    rec_realized: list[float] = field(default_factory=list)
    random_realized: list[float] = field(default_factory=list)
    predicted: list[float] = field(default_factory=list)
    shown: int = 0
    asked: int = 0


@dataclass
class Results:
    cal: dict = field(default_factory=lambda: {h: Calibration() for h in HORIZONS})
    # The online conformal envelope (#12), learning across this schedule's episodes.
    ledger: EnvelopeLedger | None = None
    envelope_misses: dict = field(default_factory=lambda: {h: [] for h in HORIZONS})
    arrival: Arrival = field(default_factory=Arrival)
    routing: Routing = field(default_factory=Routing)
    recs: Recs = field(default_factory=Recs)
    episodes: int = 0
    seconds: float = 0.0


# --- One episode ---------------------------------------------------------------------

def _future_losses(snapshot, variants, n, ticks, wind_at, start_tick, seed, towns, masks):
    """Loss per variant and rollout, run forward under the episode's actual
    wind (changing tick by tick), with paired draws across variants.
    Index 0 is "no new crew"."""
    h, w = snapshot.state.shape
    k = len(variants)
    state = np.repeat(snapshot.state[None], (k + 1) * n, axis=0)
    burn_left = np.repeat(snapshot.burn_left[None], (k + 1) * n, axis=0)
    rng = np.random.default_rng(seed)
    for t in range(ticks):
        # One grid per variant (a fresh crew ramping up, #56); advance repeats it per rollout.
        sup = np.empty((k + 1, h, w), np.float32)
        sup[0] = snapshot.suppression
        for i, v in enumerate(variants, start=1):
            g = v.grid(t)
            np.maximum(snapshot.suppression, g if g is not None else 0.0, out=sup[i])
        if advance(state, burn_left, snapshot.layers, wind_at(start_tick + t), sup, rng, group=k + 1) is None:
            break
    burned = ((state == BURNING) | (state == BURNED)).reshape(k + 1, n, -1).astype(np.float32)
    m = masks.reshape(len(towns), -1)
    frac = burned @ m.T / np.maximum(m.sum(axis=1), 1.0)
    pop = np.array([t.population for t in towns], np.float32)
    return frac @ pop + ACRE_WEIGHT * burned.sum(axis=2)  # (k+1, n)


def run_episode(scenario, net, towns, sched: str, seed: int, ticks: int, every: int, n: int, res: Results,
                rec_every: int) -> None:
    wind_at = schedule(sched, seed)
    sim = FireSim(scenario, seed=seed)
    sim.set_wind(wind_at(0))
    sim.ignite(*IGNITIONS[seed % len(IGNITIONS)], radius=2)
    H, W = scenario.height, scenario.width
    live_first = np.full((H, W), np.inf, np.float32)  # tick each cell first caught, live
    live_first[sim.state >= BURNING] = 0
    masks = _town_masks(towns, H, W) if towns else None
    pending = []  # (issue_tick, forecast, unburned_at_issue)
    routes_pending = []  # (issue_tick, route, naive_route)
    tracker = RouteTracker()
    last_raw: dict[str, list[int]] = {}
    last_shown: dict[str, list[int]] = {}
    speed = BUS_SPEED_KMH * 1000 / 60 * SIM_MINUTES_PER_TICK  # metres per tick
    rng = np.random.default_rng(seed + 77)

    for tick in range(ticks + max(HORIZONS) + 1):
        if tick < ticks and tick % every == 0 and (sim.state == BURNING).any():
            snap = sim.snapshot()
            f = run_forecast(snap, n=n, seed=seed * 1000 + tick)
            pending.append((tick, f, sim.state == FUEL))  # fuel that hasn't caught yet
            if res.ledger is None:
                res.ledger = EnvelopeLedger(tuple(horizon_ticks(h) for h in HORIZONS), WARM_THETA, n, lr=ENVELOPE_LR)
            res.ledger.issue(tick, f.probability, sim.state >= BURNING, sim.state == FUEL)
            if net is not None:
                best, rescored = replan_routes(net, f.first_burn, tracker.held())
                shown, _ = tracker.choose(best, rescored, tick)
                closed = _burning_edges(net, sim.state)
                naive = {r.town: r for r in plan_routes(net, None, closed=closed)}
                for raw, sh in zip(best, shown):
                    res.routing.raw_changes += raw.town in last_raw and last_raw[raw.town] != raw.edges
                    res.routing.shown_changes += sh.town in last_shown and last_shown[sh.town] != sh.edges
                    last_raw[raw.town], last_shown[sh.town] = raw.edges, sh.edges
                    if raw.status != "cut":
                        routes_pending.append((tick, raw, naive.get(raw.town)))
            if towns and (tick // every) % rec_every == 0:
                res.recs.asked += 1
                recs = recommend(snap, f.probability[0], towns, seed=seed * 7 + tick)
                spots = candidates(snap, f.probability[0], towns)
                if recs and spots:
                    res.recs.shown += 1
                    top = recs[0]
                    rnd = spots[int(rng.integers(len(spots)))]
                    wf = snap.wind.from_deg
                    variants = [crew_layer(W, H, top.x, top.y, wind_from=wf), crew_layer(W, H, *rnd, wind_from=wf)]
                    # Realized over the same window the recommendation was scored on.
                    loss = _future_losses(snap, variants, 8, REC_HORIZON_TICKS, wind_at, tick,
                                          seed * 31 + tick, towns, masks)
                    res.recs.rec_realized.append(float((loss[0] - loss[1]).mean()))
                    res.recs.random_realized.append(float((loss[0] - loss[2]).mean()))
                    res.recs.predicted.append(top.benefit)

        if tick < ticks + max(HORIZONS):
            sim.set_wind(wind_at(tick))
            sim.step()
            caught = (sim.state >= BURNING) & np.isinf(live_first)
            live_first[caught] = tick + 1

        if res.ledger is not None:
            for hi, miss in res.ledger.mature(sim.tick, sim.state >= BURNING):
                res.envelope_misses[HORIZONS[hi]].append(miss)
        # Forecasts whose horizons have now passed.
        for issue, f, unburned in list(pending):
            for h in HORIZONS:
                if sim.tick == issue + horizon_ticks(h):
                    hi = HORIZONS.index(h)
                    y = (live_first <= issue + horizon_ticks(h)) & unburned
                    p = f.probability[hi]
                    res.cal[h].add(p[unburned].astype(float), y[unburned].astype(float))
            if sim.tick == issue + horizon_ticks(max(HORIZONS)):
                _score_arrivals(f, live_first, unburned, issue, res.arrival)
                pending.remove((issue, f, unburned))

    # Routes: was any road on the path burning by the time the bus got there?
    if res.ledger is not None:
        res.ledger.clear_pending()  # the next episode is a new fire
    for issue, route, naive in routes_pending:
        if _route_done_by(route, issue) > sim.tick:
            continue  # the bus wouldn't have finished before the episode ended
        cut = _route_cut(net, route, live_first, issue, speed)
        res.routing.bins[res.routing.bin(route.risk)][0] += cut
        res.routing.bins[res.routing.bin(route.risk)][1] += 1
        res.routing.aware_cut += cut
        res.routing.aware_total += 1
        if naive is not None and naive.status != "cut":
            naive_cut = _route_cut(net, naive, live_first, issue, speed)
            res.routing.naive_cut += naive_cut
            res.routing.naive_total += 1
            if naive.edges != route.edges:  # where the forecast actually changed the decision
                res.routing.differ += 1
                res.routing.differ_aware_cut += cut
                res.routing.differ_naive_cut += naive_cut
    res.routing.town_episodes += len(last_raw)
    res.episodes += 1


def _burning_edges(net, state):
    from routing.evac import burning_edges

    return burning_edges(net, state, BURNING)


def _route_done_by(route, issue) -> float:
    """Sim tick the bus reaches the safe zone (eta_min is drive time in sim minutes)."""
    return issue + route.eta_min / SIM_MINUTES_PER_TICK


def _route_cut(net, route, live_first, issue, speed) -> bool:
    """True if a cell on any edge caught fire before the bus reached that edge's middle."""
    t = 0.0
    flat = live_first.ravel()
    for eid in route.edges:
        length = net.length_m[eid]
        t_mid = issue + t + 0.5 * length / speed
        end = net.sample_start[eid + 1] if eid + 1 < len(net.sample_start) else len(net.sample_cell)
        cells = net.sample_cell[net.sample_start[eid]:end]
        if (flat[cells] <= t_mid).any():
            return True
        t += length / speed
    return False


def _score_arrivals(f, live_first, unburned, issue, acc: Arrival) -> None:
    """Coverage of the rollouts' 5-95% arrival range for cells that burned within the forecast."""
    horizon = horizon_ticks(max(HORIZONS))
    actual = live_first - issue
    cells = unburned & (actual <= horizon)
    if not cells.any():
        return
    fb = f.first_burn[:, cells]  # (n, c), inf = not within the horizon
    # Order statistics, not interpolation: rollouts that never burned the cell
    # are inf, and interpolating between two infs gives NaN.
    q_lo = np.quantile(fb, 0.05, axis=0, method="lower")
    q_hi = np.quantile(fb, 0.95, axis=0, method="higher")
    y = actual[cells]
    lead_min = y * SIM_MINUTES_PER_TICK
    score = np.maximum(q_lo - y, y - q_hi)  # CQR conformity score (#13); <= 0 means inside
    for b, (lo, hi) in enumerate(LEAD_BUCKETS):
        sel = (lead_min > lo) & (lead_min <= hi)
        if not sel.any():
            continue
        acc.total[b] += sel.sum()
        acc.covered[b] += (score[sel] <= 0).sum()
        lo_b, hi_b = q_lo[sel], q_hi[sel]
        finite = np.isfinite(hi_b)
        width = np.full(len(hi_b), float(horizon))  # an open-ended range counts as the whole horizon
        width[finite] = hi_b[finite] - lo_b[finite]
        acc.width[b] += float(width.sum()) * SIM_MINUTES_PER_TICK
        acc.scores[b].extend(np.where(np.isfinite(score[sel]), score[sel], horizon).tolist())


# --- Report -----------------------------------------------------------------------------

def _envelope_summary(r: Results, h: int) -> dict:
    """How the online conformal envelope did (#12): its average miss over all
    scored forecasts and over the second half (after it has adapted), and where
    its threshold ended up."""
    m = r.envelope_misses[h]
    if not m or r.ledger is None:
        return {}
    env = r.ledger.envs[HORIZONS.index(h)]
    half = m[len(m) // 2:]
    return {
        "envelope_miss": round(float(np.mean(m)), 3),
        "envelope_miss_2nd_half": round(float(np.mean(half)), 3),
        "envelope_scored": len(m),
        "envelope_threshold": round(env.threshold, 3),
        "envelope_margin_cells": env.margin,
    }


def summarize(results: dict[str, Results]) -> dict:
    out = {}
    for sched, r in results.items():
        cal = {}
        for h, c in r.cal.items():
            fnr = c.missed / max(c.burned, 1)
            ok = LAMBDAS[fnr <= ALPHA]
            cal[f"T+{h}"] = {
                "cells": c.cells,
                "brier": round(c.brier / max(c.cells, 1), 4),
                "reliability": [
                    {"bin": f"{i / 10:.1f}-{(i + 1) / 10:.1f}", "mean_p": round(c.sum_p[i] / c.count[i], 3),
                     "observed": round(c.sum_y[i] / c.count[i], 3), "cells": int(c.count[i])}
                    for i in range(10) if c.count[i] > 0
                ],
                "fnr_at_0.1": round(float(fnr[np.argmin(abs(LAMBDAS - 0.1))]), 3),
                "fnr_at_0.5": round(float(fnr[np.argmin(abs(LAMBDAS - 0.5))]), 3),
                "lambda_for_fnr_10pct": float(ok.max()) if len(ok) else None,
                **_envelope_summary(r, h),
            }
        a = r.arrival
        arrival = {
            f"{lo}-{hi} min": {
                "cells": int(a.total[b]),
                "coverage_5_95": round(a.covered[b] / a.total[b], 3) if a.total[b] else None,
                "mean_width_min": round(a.width[b] / a.total[b], 1) if a.total[b] else None,
                "qhat_90": round(float(np.quantile(a.scores[b], 0.9)) * SIM_MINUTES_PER_TICK, 1) if a.scores[b] else None,
            }
            for b, (lo, hi) in enumerate(LEAD_BUCKETS)
        }
        ro = r.routing
        routing = {
            "predicted_vs_cut": {k: {"routes": v[1], "cut": v[0], "cut_rate": round(v[0] / v[1], 3) if v[1] else None}
                                 for k, v in ro.bins.items()},
            "forecast_aware_cut_rate": round(ro.aware_cut / ro.aware_total, 3) if ro.aware_total else None,
            "current_fire_only_cut_rate": round(ro.naive_cut / ro.naive_total, 3) if ro.naive_total else None,
            "routes_where_the_forecast_changed_the_choice": ro.differ,
            "of_those_cut_forecast_aware": ro.differ_aware_cut,
            "of_those_cut_current_fire_only": ro.differ_naive_cut,
            "route_changes_per_town_raw": round(ro.raw_changes / max(ro.town_episodes, 1), 2),
            "route_changes_per_town_shown": round(ro.shown_changes / max(ro.town_episodes, 1), 2),
        }
        rc = r.recs

        def mean(xs):
            return round(float(np.mean(xs)), 1) if xs else None

        recs = {
            "asked": rc.asked,
            "shown": rc.shown,
            "realized_benefit_top_rec": mean(rc.rec_realized),
            "realized_benefit_random_front_spot": mean(rc.random_realized),
            "predicted_benefit_top_rec": mean(rc.predicted),
            # Ties (often both 0: neither spot changes the outcome) are counted apart.
            "top_rec_beats_random": f"{sum(a > b for a, b in zip(rc.rec_realized, rc.random_realized))} of {len(rc.rec_realized)}"
                                    f" ({sum(a == b for a, b in zip(rc.rec_realized, rc.random_realized))} ties)",
        }
        out[sched] = {"episodes": r.episodes, "seconds": round(r.seconds, 1), "calibration": cal,
                      "arrival": arrival, "routing": routing, "recommendations": recs}
    return out


def markdown(summary: dict, args) -> str:
    lines = [
        "# Fireline model evaluation",
        "",
        f"{args.episodes} episodes per schedule, {args.ticks} sim-minutes each, forecasts every {args.every} min "
        f"with {args.rollouts} rollouts. Truth is the live sim (same fire model), so this measures what the "
        "forecast can't know (wind changes, luck) and its shortcuts, not realism (#15).",
        "",
    ]
    for sched, s in summary.items():
        lines += [f"## {sched} wind ({s['episodes']} episodes, {s['seconds']} s)", "", "**Forecast calibration**", "",
                  "| Horizon | Brier | Missed at P≥0.1 | Missed at P≥0.5 | λ for 10% missed |", "|---|---|---|---|---|"]
        for h, c in s["calibration"].items():
            lam = c["lambda_for_fnr_10pct"]
            lam = "none: misses >10% even at P ≥ 0.02" if lam is None else lam
            lines.append(f"| {h} | {c['brier']} | {c['fnr_at_0.1']:.0%} | {c['fnr_at_0.5']:.0%} | {lam} |")
        lines += ["", "Reliability at T+60 (predicted vs observed share burned):", "",
                  "| P bin | mean P | observed | cells |", "|---|---|---|---|"]
        for b in s["calibration"]["T+60"]["reliability"]:
            lines.append(f"| {b['bin']} | {b['mean_p']} | {b['observed']} | {b['cells']:,} |")
        lines += ["", "**Arrival times** (rollouts' 5–95% range, target ~90%)", "",
                  "| Fire arrived after | cells | coverage | mean width | Q̂ (90%) |", "|---|---|---|---|---|"]
        for k, a in s["arrival"].items():
            cov = "–" if a["coverage_5_95"] is None else f"{a['coverage_5_95']:.0%}"
            lines.append(f"| {k} | {a['cells']:,} | {cov} | {a['mean_width_min']} min | {a['qhat_90']} min |")
        ro = s["routing"]
        lines += ["", "**Routing**", "", "| Predicted risk | routes | actually cut |", "|---|---|---|"]
        for k, v in ro["predicted_vs_cut"].items():
            rate = "–" if v["cut_rate"] is None else f"{v['cut_rate']:.0%}"
            lines.append(f"| {k} | {v['routes']} | {rate} |")
        lines += ["", f"- Cut before the bus got through: forecast-aware {ro['forecast_aware_cut_rate']}, "
                      f"current-fire-only {ro['current_fire_only_cut_rate']}",
                  f"- Where the forecast changed the route ({ro['routes_where_the_forecast_changed_the_choice']} routes): "
                  f"cut {ro['of_those_cut_forecast_aware']} times on the forecast-aware route vs "
                  f"{ro['of_those_cut_current_fire_only']} on the current-fire-only route",
                  f"- Route changes per town per episode: best route {ro['route_changes_per_town_raw']}, "
                  f"shown (with hysteresis) {ro['route_changes_per_town_shown']}"]
        rc = s["recommendations"]
        lines += ["", "**Recommendations** (benefit = person-equivalents spared vs no new crew, under the real wind)", "",
                  f"- Shown {rc['shown']} times of {rc['asked']} asked",
                  f"- Realized benefit: top recommendation {rc['realized_benefit_top_rec']}, random front spot "
                  f"{rc['realized_benefit_random_front_spot']}; top beats random {rc['top_rec_beats_random']}",
                  f"- Predicted benefit of the top recommendation {rc['predicted_benefit_top_rec']} (vs realized above)", ""]
    return "\n".join(lines)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--episodes", type=int, default=4, help="per schedule (episode i uses ignition i mod 4)")
    p.add_argument("--schedules", default="steady,shift,gusty")
    p.add_argument("--ticks", type=int, default=240, help="sim minutes per episode (forecasts stop then)")
    p.add_argument("--every", type=int, default=10, help="sim minutes between forecasts")
    p.add_argument("--rollouts", type=int, default=16)
    p.add_argument("--rec-every", type=int, default=3, help="evaluate recommendations every Nth forecast")
    p.add_argument("--scenario", default="paradise")
    p.add_argument("--out", help="write the markdown report here")
    p.add_argument("--json", help="write the summary as JSON here")
    p.add_argument("--envelope-lr", type=float, help="step size of the online conformal envelope (#12)")
    args = p.parse_args()
    if args.envelope_lr is not None:
        global ENVELOPE_LR
        ENVELOPE_LR = args.envelope_lr

    scenario = load_scenario(args.scenario)
    net = load_network(scenario.dir, scenario.width, scenario.height)
    towns = [TownInfo(t.name, t.x, t.y, t.radius, t.population) for t in net.towns] if net else []
    results = {}
    for sched in args.schedules.split(","):
        r = Results()
        t0 = time.perf_counter()
        for ep in range(args.episodes):
            run_episode(scenario, net, towns, sched, ep, args.ticks, args.every, args.rollouts, r, args.rec_every)
            print(f"{sched} episode {ep + 1}/{args.episodes} done ({time.perf_counter() - t0:.0f} s)", flush=True)
        r.seconds = time.perf_counter() - t0
        results[sched] = r
    summary = summarize(results)
    report = markdown(summary, args)
    if args.json:
        with open(args.json, "w") as f:
            json.dump(summary, f, indent=2)
    if args.out:
        with open(args.out, "w") as f:
            f.write(report)
        print(f"wrote {args.out}")
    else:
        print(report)


if __name__ == "__main__":
    main()
