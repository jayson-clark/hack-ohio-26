---
name: model-eval
description: Measure how well the forecast, arrival-time ranges, evacuation routing and crew recommendations hold up, by running headless fire episodes (engine/eval/run.py). Use after changing the fire model, forecaster, router, recommender or any uncertainty code, to get numbers for a PR or the demo, or to get warm-start values for conformal calibration.
---

```sh
cd engine && uv run python -m eval.run                                   # 4 episodes x steady/shift/gusty, ~75 s
cd engine && uv run python -m eval.run --schedules shift --episodes 8 --out report.md --json eval.json
```
Options: `--ticks` (sim minutes per episode, default 240), `--every` (minutes between forecasts), `--rollouts`, `--rec-every`, `--scenario`.

Early attack (does dropping crews on a new ignition still contain it?):
```sh
cd engine && uv run python -m eval.early_attack            # ~10 s; no crews / instant / dispatched, at 3, 8, 13 m/s
cd engine && uv run python -m eval.early_attack --no-hold  # without the head-fire rule (sim.fire.HOLD_P), for a before/after
```

## What it reports (per wind schedule)
- **Calibration:** reliability (mean predicted P against the observed share that burned), Brier score, and the share of what actually burned that each raw contour (P ≥ 0.1, P ≥ 0.5) missed. Steady wind should be close to the diagonal, which is the sanity check. After a wind shift, high-P bins come out overconfident.
- **Arrival times:** coverage of the rollouts' full range (about 88% nominal with 16 rollouts) by lead time, and the mean width.
- **Routing:** predicted risk against routes actually cut, and, the key number, routes where the forecast changed the choice compared with a current-fire-only router, and how often each was cut. Also route changes per town, raw against shown (hysteresis).
- **Recommendations:** realized benefit of the top pick against a random front spot, run forward under the episode's real (changing) wind, and predicted against realized benefit (overpromising after a shift is expected).
- **Warm starts for #12/#13:** `lambda_for_fnr_10pct` per horizon, and `qhat_90` per lead bucket.

## Gotchas
- The truth is the live sim, which runs the same fire model, so this measures wind changes, luck and forecaster shortcuts, not realism (that's the Camp Fire replay, #15).
- "λ: none" means even P ≥ 0.02 misses more than 10% of what burned: some cells burned that no rollout reached. The conformal envelope then needs a spatial margin, not just a lower threshold.
- Ignitions rotate over 4 starts (episode i uses start i mod 4). The 4th, between Magalia and Paradise, is the one that exercises routing, so keep `--episodes` a multiple of 4.
- Run it from `engine/` (flat imports). Each run is seeded, so the numbers are reproducible.
