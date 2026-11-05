"""Fixed-rate ACI against the DtACI-inspired controller for the burn envelope (#227).

    cd engine && uv run python -m eval.conformal_compare                    # record + compare (~10 min)
    cd engine && uv run python -m eval.conformal_compare --cache streams.pkl --out report.md --json cmp.json

Each episode is one Paradise fire under a wind schedule, with the engine's
forecaster (32 rollouts, a forecast every 5 sim minutes). It is recorded
once: for every forecast and horizon, the loss curve L(theta) of what newly
burned by that horizon, and the area of C(theta). The envelope never feeds
back into the fire, so every controller can then be replayed on the
identical stream (same scenarios, seeds and forecasts), in the order the
ledger would see it: forecasts mature h minutes after issue, and a step's
maturities are processed before that step's new forecast.

Controllers: "static" (the warm start, never updated; what the forecast and
warm start do alone), "aci" (the original fixed step) and "dtaci".

Wind schedules (from 45 deg is north-easterly):
  steady    10 m/s from 45 deg throughout
  reversal  from 45 deg, then from 225 deg at minute 120
  surge     7 m/s, then 18 m/s at minute 120, same direction (ignition 4 of
            eval.run.IGNITIONS burns out in light wind before the surge)
  flipflop  45 / 225 deg, alternating every 30 min from minute 90
  gusty     eval.run's: a new random speed (4-15 m/s) and direction every 15 min
  veer      10 m/s, turning steadily from 45 to 135 deg over minutes 90-210 (gradual,
            no abrupt shift; used by eval.wind_ensemble)

Metrics per controller, schedule and horizon (episodes pooled):
  miss        mean share of newly burned area outside the shown envelope
  worst30     worst trailing 30-min mean miss (6 forecasts, by score time,
              as the console's recent rate sees it), averaged over episodes
  over15      share of those 30-min windows above alpha + 5 points
  area        mean envelope area beyond the fire at issue, km^2
  vs_oracle   that area over the area of the tightest envelope that would
              have met alpha on each forecast (a hindsight yardstick, not
              achievable online)
  sat         share of envelopes shown at the widest setting
  infeasible  share of forecasts where even the widest envelope misses > alpha
  recovery    single-shift schedules: minutes after the shift until the
              trailing 30-min miss of envelopes *issued* (shown) from then on
              stays within alpha + 5 points, and the same by score time
  post-shift  mean miss and vs_oracle of envelopes issued in the 2 h after a shift
"""

import argparse
import json
import pickle
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field

import numpy as np

from eval.run import IGNITIONS, schedule as run_schedule
from forecast.runner import HORIZONS_MIN, N_ROLLOUTS, horizon_ticks, run_forecast
from scenario import load_scenario
from sim.fire import BURNING, FUEL, FireSim, Wind
from uq.conformal import ALPHA, LR, MAX_MARGIN, DTACI_INTERVAL, RiskCurve, ScoreMap, is_widest, make_controller, theta_floor

WARM = (0.2, 0.15)  # server.ENVELOPE_WARM, copied so recording needn't import the engine
RECORD_MARGIN = 40  # cells: recorded wide, so any cap up to this can be replayed
SCHEDULES = ("steady", "reversal", "surge", "flipflop", "gusty")
SHIFT = 120
WINDOW = 6  # forecasts: 30 sim minutes at EVERY = 5
TOL = 0.05
ETA_SCALES = (1, 3, 10, 30, 100, 300)


def schedule(name: str, seed: int):
    """(wind(tick), shift ticks) for an episode."""
    if name == "steady":
        return (lambda t: Wind(10.0, 45.0)), []
    if name == "reversal":
        return (lambda t: Wind(10.0, 45.0) if t < SHIFT else Wind(10.0, 225.0)), [SHIFT]
    if name == "surge":
        return (lambda t: Wind(7.0, 45.0) if t < SHIFT else Wind(18.0, 45.0)), [SHIFT]
    if name == "flipflop":
        return (lambda t: Wind(10.0, 45.0 if t < 90 or ((t - 90) // 30) % 2 else 225.0)), list(range(90, 400, 30))
    if name == "gusty":
        return run_schedule("gusty", seed), list(range(15, 400, 15))
    if name == "veer":
        return (lambda t: Wind(10.0, 45.0 + 90.0 * min(max(t - 90, 0), 120) / 120)), []
    raise ValueError(f"unknown schedule {name!r}")


# --- Recording ------------------------------------------------------------------------

@dataclass
class Record:
    """One matured forecast at one horizon, independent of any controller."""

    horizon: int
    issue_tick: int
    mature_tick: int
    new: RiskCurve | None  # scores of the newly burned cells (None: nothing new burned)
    area: RiskCurve  # scores of every cell not alight at issue: area(theta) = n * (1 - loss(theta))


@dataclass
class Episode:
    sched: str
    seed: int
    shifts: list[int]
    cell_km2: float
    records: list[Record] = field(default_factory=list)
    forecaster: str = "constant"  # which forecast produced the records (eval.wind_ensemble)
    forecast_s: list[float] = field(default_factory=list)  # wall time of each forecast


def record(sched: str, seed: int, ticks: int, every: int, n: int, scenario: str = "paradise",
           forecasters: dict | None = None) -> Episode | list[Episode]:
    """Record one fire. With `forecasters` ({name: run_forecast kwargs}),
    every forecaster forecasts from the same snapshots of the same fire (the
    fire never depends on a forecast), and one Episode per forecaster is
    returned; without, one Episode for the engine's default forecast. A
    forecaster may also be a callable, snapshot -> probability (2, H, W)
    (a learned emulator, eval.wind_ensemble)."""
    single = forecasters is None
    forecasters = forecasters or {"constant": {}}
    scen = load_scenario(scenario)
    wind, shifts = schedule(sched, seed)
    sim = FireSim(scen, seed=seed)
    sim.set_wind(wind(0))
    sim.ignite(*IGNITIONS[seed % len(IGNITIONS)], radius=2)
    lam = 1.0 / n
    hz = [int(np.ceil(horizon_ticks(m))) for m in HORIZONS_MIN]
    burn_tick = np.full(sim.state.shape, np.inf, np.float32)
    burn_tick[sim.state >= BURNING] = 0
    eps = {name: Episode(sched, seed, [s for s in shifts if s <= ticks], (scen.cell_size_m / 1000) ** 2,
                         forecaster=name) for name in forecasters}
    pending = []  # (forecaster, issue, horizon index, ScoreMap, unburned, not alight)
    for tick in range(ticks + max(hz) + 1):
        if tick <= ticks and tick % every == 0 and (sim.state == BURNING).any():
            snap = sim.snapshot()  # the only thing a forecast sees: the fire and wind now
            lit = sim.state >= BURNING
            for name, kw in forecasters.items():
                t0 = time.perf_counter()
                prob = kw(snap) if callable(kw) else run_forecast(snap, n=n, seed=seed * 1000 + tick, **kw).probability
                eps[name].forecast_s.append(time.perf_counter() - t0)
                for i in range(len(hz)):
                    pending.append((name, tick, i, ScoreMap.of(prob[i], lam, RECORD_MARGIN),
                                    sim.state == FUEL, ~lit))
        sim.set_wind(wind(tick))
        sim.step()
        burn_tick[(sim.state >= BURNING) & np.isinf(burn_tick)] = sim.tick
        for p in [p for p in pending if p[1] + hz[p[2]] == sim.tick]:
            name, issue, i, sm, unburned, dark = p
            newly = unburned & (burn_tick <= issue + hz[i])
            eps[name].records.append(Record(i, issue, issue + hz[i], sm.curve(newly) if newly.any() else None,
                                            sm.curve(dark)))
            pending.remove(p)
    return eps["constant"] if single else list(eps.values())


def _record_job(args):
    t0 = time.perf_counter()
    ep = record(*args)
    print(f"  recorded {args[0]} seed {args[1]}: {len(ep.records)} forecasts ({time.perf_counter() - t0:.0f} s)", flush=True)
    return ep


# --- Replay -----------------------------------------------------------------------------

class Static:
    """The warm start, never updated: the forecast's own skill at a fixed cutoff."""

    def __init__(self, theta: float, lam_min: float, max_margin: int) -> None:
        self.theta, self.floor = theta, theta_floor(lam_min, max_margin)

    def state(self):
        return self.theta

    def learn(self, curve, issued):
        return curve.loss(issued)


def _controller(method: str, warm: float, lam: float, max_margin: int, lr: float, interval: int, eta_scale: float):
    if method == "static":
        return Static(warm, lam, max_margin)
    kw = {"max_margin": max_margin}
    if method == "dtaci":
        kw |= {"interval": interval, "eta_scale": eta_scale}
    return make_controller(method, warm, lam, lr=lr, **kw)


@dataclass
class Shown:
    """One scored envelope under one controller."""

    issue_tick: int
    mature_tick: int
    miss: float
    area_km2: float
    oracle_km2: float
    saturated: bool
    infeasible: bool


def replay(ep: Episode, method: str, n: int = N_ROLLOUTS, max_margin: int = MAX_MARGIN, lr: float = LR,
           interval: int = DTACI_INTERVAL, eta_scale: float = 1.0) -> list[list[Shown]]:
    """Run one controller per horizon over a recorded episode, exactly as the
    ledger would. Returns the scored envelopes per horizon, in score order."""
    lam = 1.0 / n
    out = []
    for h, warm in enumerate(WARM):
        ctl = _controller(method, warm, lam, max_margin, lr, interval, eta_scale)
        recs = [r for r in ep.records if r.horizon == h]
        if max_margin < RECORD_MARGIN:
            recs = [Record(r.horizon, r.issue_tick, r.mature_tick, r.new and r.new.capped(lam, max_margin),
                           r.area.capped(lam, max_margin)) for r in recs]
        events = sorted([(r.issue_tick, 1, r) for r in recs] + [(r.mature_tick, 0, r) for r in recs],
                        key=lambda e: (e[0], e[1], e[2].issue_tick))
        issued, scored = {}, []
        for _, kind, r in events:
            if kind == 1:
                st = ctl.state()
                issued[r.issue_tick] = (st, st[1] if isinstance(st, tuple) else st)
                continue
            st, shown = issued.pop(r.issue_tick)
            if r.new is None:
                if hasattr(ctl, "empty"):
                    ctl.empty += 1
                continue
            miss = ctl.learn(r.new, st)
            floor = theta_floor(lam, max_margin)
            area = r.area.n * (1 - r.area.loss(shown)) * ep.cell_km2
            scored.append(Shown(r.issue_tick, r.mature_tick, miss, area,
                                r.area.n * (1 - r.area.loss(oracle_theta(r.new, floor))) * ep.cell_km2,
                                is_widest(shown, lam, max_margin), r.new.loss(floor) > ALPHA))
        out.append(scored)
    return out


def oracle_theta(curve: RiskCurve, floor: float, alpha: float = ALPHA) -> float:
    """The largest theta whose envelope would have missed at most alpha of
    this forecast's new burning (floor if none does): hindsight only."""
    cells = np.repeat(curve.values, curve.counts)
    t = cells[int(np.floor(alpha * len(cells)))]
    return float(np.clip(t, floor, 1.0)) if np.isfinite(t) else floor


def paper_eta_scale(k: int = 6, interval: int = 500, alpha: float = ALPHA) -> float:
    """eta_scale that gives Gibbs & Candes's practical DtACI step (their
    section 3.1, |I| = 500): eta = sqrt(3/I) sqrt((log(kI) + 2) / ((1-alpha)^2 alpha^2))."""
    from uq.conformal import DtACIEnvelope

    eta = np.sqrt(3 / interval) * np.sqrt((np.log(k * interval) + 2) / ((1 - alpha) ** 2 * alpha ** 2))
    return float(eta / DtACIEnvelope(lam_min=1 / N_ROLLOUTS, interval=interval).eta)


# --- Metrics ----------------------------------------------------------------------------

def _trailing(x: np.ndarray, k: int = WINDOW) -> np.ndarray:
    if len(x) < k:
        return np.array([x.mean()]) if len(x) else np.array([])
    c = np.cumsum(np.concatenate([[0.0], x]))
    return (c[k:] - c[:-k]) / k


def _recovery(scored: list[Shown], shift: int, end: int, key: str) -> float | None:
    """Minutes after `shift` until the trailing 30-min miss (ordered by
    `key`: issue or score time) stays within alpha + TOL up to `end`."""
    rows = sorted(scored, key=lambda s: getattr(s, key))
    t = np.array([getattr(s, key) for s in rows])
    tr = _trailing(np.array([s.miss for s in rows]))
    if len(tr) == 0:
        return None
    t_end = t[WINDOW - 1:] if len(t) >= WINDOW else t[-1:]
    sel = (t_end >= shift) & (t_end <= end)
    if not sel.any():
        return None
    bad = t_end[sel & (tr > ALPHA + TOL)]
    return float(bad.max() - shift + 5) if len(bad) else 0.0


def metrics(eps: list[Episode], runs: list[list[list[Shown]]], h: int) -> dict:
    rows = [s for r in runs for s in r[h]]
    if not rows:
        return {}
    worst, over, rec_i, rec_s, post_m, post_a, post_o = [], [], [], [], [], [], []
    for ep, r in zip(eps, runs):
        sc = r[h]
        tr = _trailing(np.array([s.miss for s in sc]))
        if len(tr):
            worst.append(tr.max())
            over.append(float((tr > ALPHA + TOL).mean()))
        if len(ep.shifts) == 1:  # recovery is only well defined for one shift
            s0 = ep.shifts[0]
            rec_i.append(_recovery(sc, s0, s0 + 180, "issue_tick"))
            rec_s.append(_recovery(sc, s0, s0 + 180, "mature_tick"))
            post = [s for s in sc if s0 <= s.issue_tick < s0 + 120]
            if post:
                post_m.append(np.mean([s.miss for s in post]))
                post_a.append(sum(s.area_km2 for s in post))
                post_o.append(sum(s.oracle_km2 for s in post))
    area = np.array([s.area_km2 for s in rows])
    oracle = np.array([s.oracle_km2 for s in rows])
    out = {
        "scored": len(rows),
        "miss": float(np.mean([s.miss for s in rows])),
        "worst30": float(np.mean(worst)) if worst else None,
        "over15": float(np.mean(over)) if over else None,
        "area_km2": float(area.mean()),
        "vs_oracle": float(area.sum() / max(oracle.sum(), 1e-9)),
        "sat": float(np.mean([s.saturated for s in rows])),
        "infeasible": float(np.mean([s.infeasible for s in rows])),
    }
    ri = [x for x in rec_i if x is not None]
    rs = [x for x in rec_s if x is not None]
    if ri:
        out |= {"recovery_shown_min": float(np.mean(ri)), "recovery_scored_min": float(np.mean(rs)),
                "post_miss": float(np.mean(post_m)), "post_vs_oracle": float(sum(post_a) / max(sum(post_o), 1e-9))}
    return out


def diagnose(eps: list[Episode], h: int, n: int = N_ROLLOUTS) -> dict:
    """Where the misses come from after a single shift, independent of any
    controller: forecasts issued before the shift whose window crosses it
    ("stale") against those issued after ("fresh"), at the hindsight-tightest
    knob and at the widest envelope for several margin caps."""
    lam = 1.0 / n
    hz = int(np.ceil(horizon_ticks(HORIZONS_MIN[h])))
    out = {}
    for name, pick in (("stale", lambda r, s: s - hz < r.issue_tick < s), ("fresh", lambda r, s: s <= r.issue_tick < s + 60),
                       ("all", lambda r, s: True)):
        recs = [r for ep in eps for r in ep.records
                if r.horizon == h and r.new is not None and len(ep.shifts) == 1 and pick(r, ep.shifts[0])]
        if not recs:
            continue
        row = {"forecasts": len(recs),
               "miss_at_warm": float(np.mean([r.new.capped(lam, MAX_MARGIN).loss(WARM[h]) for r in recs]))}
        for cap in (10, 20, 40):
            c = [r.new.capped(lam, cap) for r in recs]
            row[f"widest_miss_cap{cap}"] = float(np.mean([x.loss(theta_floor(lam, cap)) for x in c]))
            row[f"infeasible_cap{cap}"] = float(np.mean([x.loss(theta_floor(lam, cap)) > ALPHA for x in c]))
        out[name] = row
    return out


# --- Report -----------------------------------------------------------------------------

def _f(x, pct=False, digits=2):
    if x is None:
        return "–"
    return f"{100 * x:.1f}%" if pct else f"{x:.{digits}f}"


def report(summary: dict) -> str:
    lines = ["# Burn envelope: fixed-rate ACI vs DtACI-inspired (#227)", "",
             f"{summary['episodes']} episodes per schedule, seeds {summary['seeds']}, {summary['ticks']} min of "
             f"forecasts every {summary['every']} min, {summary['rollouts']} rollouts, margin cap {MAX_MARGIN} cells, "
             f"target miss {ALPHA:.0%}.", ""]
    for hname, res in summary["main"].items():
        lines += [f"## {hname}", "",
                  "| schedule | controller | miss | worst 30 min | windows > 15% | area km² | vs oracle | at widest | "
                  "infeasible | recovery (shown) | recovery (scored) | post-shift miss | post-shift vs oracle |",
                  "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for sched, by in res.items():
            for m, r in by.items():
                lines.append(
                    f"| {sched} | {m} | {_f(r.get('miss'), True)} | {_f(r.get('worst30'), True)} | {_f(r.get('over15'), True)} | "
                    f"{_f(r.get('area_km2'))} | {_f(r.get('vs_oracle'))}× | {_f(r.get('sat'), True)} | "
                    f"{_f(r.get('infeasible'), True)} | {_f(r.get('recovery_shown_min'), digits=0)} | "
                    f"{_f(r.get('recovery_scored_min'), digits=0)} | {_f(r.get('post_miss'), True)} | "
                    f"{_f(r.get('post_vs_oracle'))}{'×' if 'post_vs_oracle' in r else ''} |")
        lines.append("")
    lines += ["## Where the misses come from (single-shift schedules, no controller)", "",
              "| horizon | schedule | forecasts | window | miss at warm start | widest miss cap 10 | cap 20 | cap 40 | "
              "infeasible cap 10 | cap 20 | cap 40 |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for hname, by in summary["diagnosis"].items():
        for sched, d in by.items():
            for win, r in d.items():
                lines.append(f"| {hname} | {sched} | {r['forecasts']} | {win} | {_f(r['miss_at_warm'], True)} | "
                             f"{_f(r['widest_miss_cap10'], True)} | {_f(r['widest_miss_cap20'], True)} | "
                             f"{_f(r['widest_miss_cap40'], True)} | {_f(r['infeasible_cap10'], True)} | "
                             f"{_f(r['infeasible_cap20'], True)} | {_f(r['infeasible_cap40'], True)} |")
    lines += ["", "## Sensitivity (all schedules pooled: miss, worst 30 min, vs oracle)", "",
              "| horizon | variant | miss | worst 30 min | vs oracle | at widest |", "|---|---|---|---|---|---|"]
    for hname, by in summary["sweep"].items():
        for v, r in by.items():
            lines.append(f"| {hname} | {v} | {_f(r['miss'], True)} | {_f(r['worst30'], True)} | {_f(r['vs_oracle'])}× | "
                         f"{_f(r['sat'], True)} |")
    lines += ["", "## DtACI weight step (selection seeds 0-3: miss, vs oracle)", "",
              "eta x1 is the worst-case Hedge step. Per-forecast loss gaps between experts are ~100x smaller than "
              "that worst case, so larger multiples were tried.", "",
              "| variant | T+30 miss | T+30 vs oracle | T+60 miss | T+60 vs oracle |", "|---|---|---|---|---|"]
    for v, r in summary.get("eta", {}).items():
        a, b = r["T+30"], r["T+60"]
        lines.append(f"| {v} | {_f(a['miss'], True)} | {_f(a['vs_oracle'])}× | {_f(b['miss'], True)} | {_f(b['vs_oracle'])}× |")
    return "\n".join(lines) + "\n"


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--schedules", default=",".join(SCHEDULES))
    p.add_argument("--episodes", type=int, default=6)
    p.add_argument("--ticks", type=int, default=300, help="sim minutes of forecasts per episode")
    p.add_argument("--every", type=int, default=5, help="sim minutes between forecasts")
    p.add_argument("--rollouts", type=int, default=N_ROLLOUTS)
    p.add_argument("--workers", type=int, default=6)
    p.add_argument("--cache", help="pickle of recorded episodes (for the same --ticks, --every and --rollouts): reused, and any missing ones recorded into it")
    p.add_argument("--out", help="write the markdown report here")
    p.add_argument("--json", help="write the summary as JSON here")
    args = p.parse_args()
    scheds = args.schedules.split(",")

    cached: list[Episode] = []
    if args.cache:
        try:
            with open(args.cache, "rb") as f:
                cached = pickle.load(f)
            print(f"loaded {len(cached)} recorded episodes from {args.cache}")
        except FileNotFoundError:
            pass
    have = {(e.sched, e.seed) for e in cached}
    jobs = [(s, seed, args.ticks, args.every, args.rollouts) for s in scheds for seed in range(args.episodes)
            if (s, seed) not in have]
    if jobs:
        print(f"recording {len(jobs)} episodes on {args.workers} workers")
        with ProcessPoolExecutor(args.workers) as pool:
            cached += list(pool.map(_record_job, jobs))
        if args.cache:
            with open(args.cache, "wb") as f:
                pickle.dump(cached, f)
    eps = [e for e in cached if e.sched in scheds and e.seed < args.episodes]

    by_sched = {s: [e for e in eps if e.sched == s] for s in scheds}
    summary = {"episodes": args.episodes, "seeds": f"0-{args.episodes - 1}", "ticks": args.ticks, "every": args.every,
               "rollouts": args.rollouts, "main": {}, "diagnosis": {}, "sweep": {}}
    variants = {"static": dict(method="static"),
                "aci lr 0.05": dict(method="aci", lr=0.05), "aci lr 0.1 (baseline)": dict(method="aci", lr=0.1),
                "aci lr 0.2": dict(method="aci", lr=0.2),
                "dtaci I 10": dict(method="dtaci", interval=10), "dtaci I 20 (default)": dict(method="dtaci", interval=20),
                "dtaci I 50": dict(method="dtaci", interval=50),
                "dtaci paper settings (I 500)": dict(method="dtaci", interval=500, eta_scale=paper_eta_scale()),
                "aci lr 0.1, cap 20": dict(method="aci", max_margin=20),
                "dtaci I 20, cap 20": dict(method="dtaci", max_margin=20)}
    runs = {v: [replay(e, n=args.rollouts, **kw) for e in eps] for v, kw in variants.items()}
    main_variants = {"static": "static", "aci": "aci lr 0.1 (baseline)", "dtaci": "dtaci I 20 (default)"}
    for h, m in enumerate(HORIZONS_MIN):
        hname = f"T+{m}"
        summary["main"][hname] = {
            s: {name: metrics(es, [runs[v][eps.index(e)] for e in es], h) for name, v in main_variants.items()}
            for s, es in by_sched.items()}
        summary["diagnosis"][hname] = {s: diagnose(es, h, args.rollouts) for s, es in by_sched.items()
                                       if es and len(es[0].shifts) == 1}
        summary["sweep"][hname] = {v: metrics(eps, runs[v], h) for v in variants}
    # The weight step: chosen on seeds 0-3 only (lowest pooled miss), then checked on the rest.
    sel = [e for e in eps if e.seed < 4]
    summary["eta"] = {}
    for v, kw in [("aci lr 0.1 (baseline)", dict(method="aci"))] + [
            (f"dtaci eta x{k}", dict(method="dtaci", eta_scale=k)) for k in ETA_SCALES]:
        rs = [replay(e, n=args.rollouts, **kw) for e in sel]
        summary["eta"][v] = {f"T+{m}": metrics(sel, rs, h) for h, m in enumerate(HORIZONS_MIN)}
    text = report(summary)
    if args.json:
        with open(args.json, "w") as f:
            json.dump(summary, f, indent=2)
    if args.out:
        with open(args.out, "w") as f:
            f.write(text)
        print(f"wrote {args.out}")
    print(text)


if __name__ == "__main__":
    main()
