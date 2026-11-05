# Wind experiments: runbook for a big Linux + CUDA machine

The remaining experiments for #228 (wind-scenario ensemble) and #229 (wind-aware emulator) need many CPU cores and a GPU. Run them in this order on the `ai/dtaci-envelope` branch. #227 (DtACI) is already finished; its results are in `docs/conformal_compare.md` and `AI_README.md`.

All commands run from `engine/`. Replace `16` in `--workers 16` with your core count. Split the cores when two jobs run at once.

## 0. Setup

```sh
git fetch origin
git switch ai/dtaci-envelope
cd engine
uv sync
uv pip install "mlx[cuda]"        # the ml extra only installs on Apple silicon
uv run --no-sync pytest -q        # expect 309 passed before starting anything long
```

From here on, always use `uv run --no-sync`. A plain `uv run` re-syncs and removes mlx.

**Baseline weights:** the "original U-Net" in every comparison is `emulator/weights/fire_emulator.safetensors`. A fresh checkout has the committed version. To compare against a newer local retrain instead, copy that file and its `.json` into `emulator/weights/` before step 4, and note which one you used.

## 1. Tune the wind ensemble, and generate emulator data (CPU, in parallel)

The tuning run and the data generation are independent, so start both. Each line is one job.

```sh
# Wind ensemble tuning: seeds 0-3, 6 wind schedules, constant wind + 4 ensemble settings
uv run --no-sync python -m eval.wind_ensemble --phase tune --workers 16 \
  --cache wind_tune.pkl --out wind_tune.md --json wind_tune.json > wind_tune.log 2>&1

# Wind-aware emulator data: 4000 training fires, then 400 held-out test fires (different seeds)
uv run --no-sync python -m emulator.data --wind-aware --samples 4000 --out emulator/data/train_wind --seed 2 --workers 16 \
  > emulator/data/datagen_wind.log 2>&1
uv run --no-sync python -m emulator.data --wind-aware --samples 400 --out emulator/data/test_wind --seed 3 --with-32 --workers 16 \
  >> emulator/data/datagen_wind.log 2>&1
```

Time on an 8-core M2 Max: tuning about 1.5 h, and data about 2 s per training sample per core. The test samples cost about twice as much, since they also store the comparison targets.

## 2. Apply the tuning result

The end of `wind_tune.md` names the selected setting. The rule was fixed before running: the least outline area needed for a pooled 10% miss, relative to constant wind.

- If it's anything other than `shifts 0.25/h`, set the `shift_rate_per_h` default in `engine/forecast/wind.py` to match: `wander only` is 0.0, `shifts 0.5/h` is 0.5, `shifts 1/h` is 1.0.
- Commit that one-line change.

The final eval and the wind-aware U-Net's eval both use these defaults. The emulator's training data does not, so step 1's data stays valid.

## 3. Train the wind-aware U-Net (GPU)

Don't run this while data generation is still going. They fight over the CPU.

```sh
uv run --no-sync python -u -m emulator.train --wind-aware --device gpu \
  --train emulator/data/train_wind --test emulator/data/test_wind > emulator/data/train_wind.log 2>&1
```

- **Output:** `emulator/weights/fire_emulator_wind.safetensors`, plus a `.json` with the training record.
- **Safety:** training refuses to overwrite an existing weights file. Pass `--overwrite` only if you mean it.
- **Defaults:** 12 epochs, batch 16, seed 0.
- **Progress:** the held-out Brier score prints after every epoch.

## 4. Final evaluations

```sh
# Held-out seeds 4-11: constant wind vs the selected ensemble, plus both U-Nets, under the conformal controller
uv run --no-sync python -m eval.wind_ensemble --phase final --emulators --workers 16 \
  --cache wind_final.pkl --out wind_final.md --json wind_final.json > wind_final.log 2>&1

# Held-out emulator test fires: Brier, calibration, IoU for all four predictors against both targets
uv run --no-sync python -m emulator.evaluate --compare --device gpu --test emulator/data/test_wind \
  --json emulator_compare.json > emulator_compare.log 2>&1
```

The Monte Carlo episodes record on the CPU workers first. The emulator episodes then record in the main process on the GPU, on the same seeded fires.

## 5. Bring back

- `wind_tune.md`, `wind_tune.json`
- `wind_final.md`, `wind_final.json`
- `emulator_compare.json`
- `emulator/data/train_wind.log`
- `emulator/weights/fire_emulator_wind.safetensors` and `fire_emulator_wind.json`, if the model should go into the repo

`AI_README.md` gets updated from these files only.

## Notes

- **Caches:** `wind_tune.pkl` and `wind_final.pkl` are reused if present, and are valid only for the same `--ticks`, `--every` and rollout count. Delete a cache after any change to the fire model or forecaster, or if a run died partway.
- **Data directories:** `emulator.data` refuses to write into a directory that already has shards, so a half-finished run can't mix with a new one. Delete the directory and rerun.
- **Leakage:** every forecaster sees only the snapshot at issue (the fire and wind then). Wind paths start from the wind at issue. The tuning seeds (0-3) and final seeds (4-11) don't overlap. The emulator test fires (seed 3) are generated separately from the training fires (seed 2).
