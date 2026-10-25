"""Pictures of the calibrated burn envelope (#12) at work, for docs and the demo.

Replays one Paradise fire under eval.run's "shift" wind (north-easterly, then
from the west at minute 60) with the engine's own forecaster and
EnvelopeLedger, a forecast every EVERY minutes. Writes, to --out:

  envelope_maps.png   three moments, T+60: the forecast's 50% band (the fill
                      the console draws), the calibrated outline (the line it
                      draws), and what really burned in the next hour, split
                      into caught by the outline and missed
  envelope_miss.png   the miss rate over time against the 10% target, as the
                      console's layers menu reports it, and the outline's
                      cutoff and margin moving in response

    cd engine && uv run python -m eval.envelope_figure --out ../docs/images/calibration
"""

import argparse
from pathlib import Path

import cv2
import numpy as np

from eval.run import IGNITIONS, schedule
from forecast.runner import HORIZONS_MIN, N_ROLLOUTS, horizon_ticks, run_forecast
from scenario import load_scenario
from server import ENVELOPE_WARM
from sim.fire import BURNING, FUEL, FireSim
from uq.conformal import ALPHA, WINDOW, EnvelopeLedger

TICKS = 240
EVERY = 5
SHOW = (40, 85, 125)  # issue ticks drawn as maps: before the shift, just after, caught up
SCALE = 3

# Colours (BGR), close to the console's map.
TERRAIN = (236, 236, 232)
C_BURNED = (110, 105, 105)
C_BURNING = (40, 70, 230)
BAND = (80, 170, 245)
LINE = (20, 90, 200)
CAUGHT = (200, 120, 40)
MISSED = (170, 30, 200)
INK = (40, 40, 40)
GRID = (215, 215, 215)


def run(seed: int = 0):
    scen = load_scenario("paradise")
    wind = schedule("shift", seed)
    sim = FireSim(scen, seed=seed)
    sim.set_wind(wind(0))
    sim.ignite(*IGNITIONS[0], radius=2)
    h60 = HORIZONS_MIN.index(60)
    ledger = EnvelopeLedger(tuple(horizon_ticks(m) for m in HORIZONS_MIN), ENVELOPE_WARM, N_ROLLOUTS)
    burn_tick = np.full(sim.state.shape, np.inf, np.float32)
    burn_tick[sim.state >= BURNING] = 0
    issued, scored, knobs = {}, [], []
    for tick in range(TICKS + 61):
        if tick <= TICKS and tick % EVERY == 0:
            f = run_forecast(sim.snapshot(), seed=seed * 1000 + tick)
            lit = sim.state >= BURNING
            envs = ledger.issue(tick, f.probability, lit, sim.state == FUEL)
            env = ledger.envs[h60]
            knobs.append((tick, env.threshold, env.margin))
            if tick in SHOW:
                issued[tick] = (sim.state.copy(), f.probability[h60] >= 0.5, envs[h60], env.threshold, env.margin)
        sim.set_wind(wind(tick))
        sim.step()
        lit = sim.state >= BURNING
        burn_tick[lit & np.isinf(burn_tick)] = sim.tick
        for hi, miss in ledger.mature(sim.tick, lit):
            scored.append((sim.tick, hi, miss))
    return scen, issued, burn_tick, scored, knobs


def hillshade(z: np.ndarray) -> np.ndarray:
    gy, gx = np.gradient(z.astype(np.float32))
    shade = np.clip(0.5 + (gx - gy) * 0.04, 0, 1)
    base = np.array(TERRAIN, np.float32)
    return (base * (0.82 + 0.18 * shade[..., None])).astype(np.uint8)


def blend(img, mask, color, alpha):
    img[mask] = (img[mask] * (1 - alpha) + np.array(color) * alpha).astype(np.uint8)


def outline(mask: np.ndarray) -> np.ndarray:
    m = mask.astype(np.uint8)
    return (cv2.dilate(m, np.ones((3, 3), np.uint8)) - m).astype(bool)


def map_panel(scen, issued_at, state, band, env, thr, margin, burn_tick, box):
    y0, y1, x0, x1 = box
    lit = state >= BURNING
    new = (burn_tick > issued_at) & (burn_tick <= issued_at + 60)
    miss = float((new & ~env).sum() / max(new.sum(), 1))
    img = hillshade(scen.heightmap)
    blend(img, lit & (state != BURNING), C_BURNED, 0.7)
    blend(img, band & ~lit, BAND, 0.35)
    blend(img, new & env, CAUGHT, 0.75)
    blend(img, new & ~env, MISSED, 0.9)
    blend(img, state == BURNING, C_BURNING, 0.95)
    crop = img[y0:y1, x0:x1]
    crop = cv2.resize(crop, ((x1 - x0) * SCALE, (y1 - y0) * SCALE), interpolation=cv2.INTER_NEAREST)
    line = cv2.resize(outline(env[y0:y1, x0:x1]).astype(np.uint8), (crop.shape[1], crop.shape[0]),
                      interpolation=cv2.INTER_NEAREST).astype(bool)
    line = cv2.dilate(line.astype(np.uint8), np.ones((2, 2), np.uint8)).astype(bool)
    crop[line] = LINE
    head = np.full((84, crop.shape[1], 3), 255, np.uint8)
    when = {SHOW[0]: "before the shift", SHOW[1]: "just after it", SHOW[2]: "caught up"}[issued_at]
    knob = f"cutoff P >= {thr:.2f}" + (f" + {margin} cells" if margin else "")
    for k, (text, size, bold) in enumerate([(f"Minute {issued_at}: {when}", 0.6, 2),
                                            (f"{miss:.0%} of next hour's fire missed", 0.5, 1),
                                            (f"outline: {knob}", 0.5, 1)]):
        cv2.putText(head, text, (8, 22 + 26 * k), cv2.FONT_HERSHEY_SIMPLEX, size, INK, bold, cv2.LINE_AA)
    return np.vstack([head, crop])


def legend(width: int) -> np.ndarray:
    items = [(BAND, "forecast: half the simulations burn (fill)"), (LINE, "calibrated outline (line)"),
             (CAUGHT, "burned in the next hour, inside the outline"), (MISSED, "burned in the next hour, missed"),
             (C_BURNING, "burning at the forecast"), (C_BURNED, "already burned")]
    img = np.full((72, width, 3), 255, np.uint8)
    x, y = 8, 12
    for color, text in items:
        tw = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)[0][0]
        if x + 30 + tw > width:
            x, y = 8, y + 30
        cv2.rectangle(img, (x, y), (x + 16, y + 16), color, -1)
        cv2.putText(img, text, (x + 22, y + 14), cv2.FONT_HERSHEY_SIMPLEX, 0.45, INK, 1, cv2.LINE_AA)
        x += 34 + tw
    return img


def maps(scen, issued, burn_tick) -> np.ndarray:
    seen = np.isfinite(burn_tick)
    ys, xs = np.nonzero(seen | np.any([v[2] for v in issued.values()], axis=0))
    h, w = burn_tick.shape
    box = (max(ys.min() - 6, 0), min(ys.max() + 7, h), max(xs.min() - 6, 0), min(xs.max() + 7, w))
    panels = [map_panel(scen, t, *issued[t], burn_tick, box) for t in SHOW]
    gap = np.full((panels[0].shape[0], 12, 3), 255, np.uint8)
    row = np.hstack([p if i == 0 else np.hstack([gap, p]) for i, p in enumerate(panels)])
    return np.vstack([row, legend(row.shape[1])])


def chart(scored, knobs) -> np.ndarray:
    w, h, pad = 980, 420, 60
    img = np.full((h, w, 3), 255, np.uint8)
    t_max = TICKS + 60
    sx = lambda t: int(pad + (w - 2 * pad) * t / t_max)  # noqa: E731
    sy = lambda v: int(h - pad - (h - 2 * pad) * min(v, 1.0))  # noqa: E731
    for t in range(0, t_max + 1, 60):
        cv2.putText(img, str(t), (sx(t) - 8, h - pad + 18), cv2.FONT_HERSHEY_SIMPLEX, 0.45, INK, 1, cv2.LINE_AA)
    for v in (0, 0.1, 0.25, 0.5, 0.75, 1.0):
        cv2.line(img, (pad, sy(v)), (w - pad, sy(v)), GRID, 1)
        cv2.putText(img, f"{v:.0%}", (8, sy(v) + 5), cv2.FONT_HERSHEY_SIMPLEX, 0.45, INK, 1, cv2.LINE_AA)
    cv2.line(img, (pad, sy(ALPHA)), (w - pad, sy(ALPHA)), (60, 160, 60), 2)
    cv2.putText(img, "target 10%", (w - pad - 90, sy(ALPHA) - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (60, 160, 60), 1,
                cv2.LINE_AA)
    cv2.line(img, (sx(60), pad - 10), (sx(60), h - pad), (150, 150, 150), 1)
    cv2.putText(img, "wind swings to the west", (sx(60) + 6, pad), cv2.FONT_HERSHEY_SIMPLEX, 0.45, INK, 1,
                cv2.LINE_AA)
    for hi, color, name in ((0, (140, 140, 220), "T+30"), (1, LINE, "T+60")):
        pts = [(t, m) for t, i, m in scored if i == hi]
        for t, m in pts:
            cv2.circle(img, (sx(t), sy(m)), 3, color, -1, cv2.LINE_AA)
        recent = [(t, float(np.mean([m for _, m in pts[max(0, k - WINDOW + 1): k + 1]]))) for k, (t, _) in enumerate(pts)]
        for (ta, a), (tb, b) in zip(recent, recent[1:]):
            cv2.line(img, (sx(ta), sy(a)), (sx(tb), sy(b)), color, 2, cv2.LINE_AA)
    cv2.putText(img, "Missed share of each forecast once scored (dots) and the last-20 average the console shows (line)",
                (pad, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.5, INK, 1, cv2.LINE_AA)
    cv2.putText(img, "sim minute (when each forecast is scored)", (w // 2 - 140, h - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.45, INK, 1, cv2.LINE_AA)
    leg = [((140, 140, 220), "T+30"), (LINE, "T+60")]
    for k, (c, name) in enumerate(leg):
        cv2.circle(img, (w - pad - 150 + 80 * k, pad + 10), 5, c, -1)
        cv2.putText(img, name, (w - pad - 140 + 80 * k, pad + 15), cv2.FONT_HERSHEY_SIMPLEX, 0.45, INK, 1, cv2.LINE_AA)
    # The T+60 knob underneath: cutoff and margin as the online update moves them.
    k_h = 150
    knob = np.full((k_h, w, 3), 255, np.uint8)
    ky = lambda v: int(k_h - 30 - (k_h - 60) * min(v, 0.25) / 0.25)  # noqa: E731
    for (ta, a, ma), (tb, b, mb) in zip(knobs, knobs[1:]):
        cv2.line(knob, (sx(ta), ky(a)), (sx(tb), ky(b)), LINE, 2, cv2.LINE_AA)
        if mb:
            cv2.putText(knob, str(mb), (sx(tb) - 4, ky(b) - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.35, MISSED, 1, cv2.LINE_AA)
    cv2.putText(knob, "T+60 outline: probability cutoff (line) and margin in cells (numbers), by the minute each forecast is issued",
                (pad, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, INK, 1, cv2.LINE_AA)
    for v in (0, 0.1, 0.2):
        cv2.putText(knob, f"{v:.1f}", (8, ky(v) + 5), cv2.FONT_HERSHEY_SIMPLEX, 0.45, INK, 1, cv2.LINE_AA)
    cv2.line(knob, (sx(60), 26), (sx(60), k_h - 20), (150, 150, 150), 1)
    return np.vstack([img, knob])


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--out", default="../docs/images/calibration")
    p.add_argument("--seed", type=int, default=0)
    args = p.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    scen, issued, burn_tick, scored, knobs = run(args.seed)
    cv2.imwrite(str(out / "envelope_maps.png"), maps(scen, issued, burn_tick))
    cv2.imwrite(str(out / "envelope_miss.png"), chart(scored, knobs))
    for hi, m in enumerate(HORIZONS_MIN):
        pts = [x for t, i, x in scored if i == hi]
        print(f"T+{m}: {len(pts)} forecasts scored, mean miss {np.mean(pts):.1%}")
    print("wrote", out / "envelope_maps.png", "and", out / "envelope_miss.png")


if __name__ == "__main__":
    main()
