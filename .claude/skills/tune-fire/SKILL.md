---
name: tune-fire
description: Tune the fire model's spread constants (p_h, wind, slope, burn time) or check how fast and which way the fire spreads. Use when the fire looks too fast, too slow, dies out, ignores the wind, or after changing engine/sim/fire.py.
---

Constants live at the top of `engine/sim/fire.py` (`P_H`, `C1`, `C2`, `SLOPE_A`, `BURN_TICKS`, `DIAGONAL`). The model and why each one differs from Alexandridis (2008) are in PLAN.md's "Fire model".

1. From `engine/`: `uv run python -m sim.tune` prints upwind/downwind/flank spread (cells) after 100 ticks for 0, 4, 8 and 15 m/s, on flat ground and on the real terrain.
2. Try values without editing: `uv run python -m sim.tune P_H=0.1 C1=0.12 BURN_TICKS=6`.
3. Current targets (100 ticks = 100 sim-minutes = 10 s of demo):
   - no wind: a disc of radius about 30, and it must stay alive ("still burning 4/4"). Too-low `P_H` or `BURN_TICKS` makes calm fires die out.
   - 8 m/s: downwind about 55, upwind about 1, flank under half the downwind run.
   - 15 m/s: downwind about 90. The CA caps at one cell per tick, so 100 is the ceiling.
4. Put the chosen values in `fire.py`, update the comment above them if the targets moved, and run `make test`. `engine/tests/test_fire.py` checks direction (wind, uphill, suppression), not exact speeds, so it shouldn't need changes.

Gotchas:
- Speed also changes the forecast: `SIM_MINUTES_PER_TICK` and the horizons in `engine/forecast/runner.py` assume a fire moving at most one cell per tick.
- `HOLD_P` decides how much partial suppression (crews, wet patches) weakens against intense spread. Raise it and crews hold head fire again; lower it and they only hold backing fire. Check with `uv run python -m eval.early_attack` (model-eval skill).
- Spotting (`SPOT_*`) only runs above `SPOT_MIN_WIND` (9 m/s). Check changes against the real Camp Fire: `uv run python -m eval.campfire` (one replay, ~3 s) or `--search` (432 settings in parallel, ~4 min). Its observations are upper bounds ("fire was here by then"), so only lateness counts as an error, and overburning shows up in the perimeter IoU and area ratio.
- Changing `C2` changes every wind, not just the head. It's 0.3, chosen against the Camp Fire replay, Marshall (`eval.marshall --measured`) and `eval.early_attack` together (PLAN.md, "Choosing C2"). At 0.4 fires at 3–8 m/s starve; a floor on flank and backing spread was tried and made both replays worse. Run all three before changing it.
- The learned emulator (fire-emulator skill) has to be retrained after any change here.
- `SLOPE_A` is per degree of real slope (metres, not the print's relief). Paradise's canyon walls hit 25–40°, so small changes matter a lot downhill.
- `rollout` timing grows with the fire's bounding box. Check `rollout(snapshot, 32, 60)` on a large fire stays well under a second.
