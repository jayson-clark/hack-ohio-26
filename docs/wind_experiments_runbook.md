# Wind experiments: runbook

Commands for the #228 (wind-scenario ensemble) and #229 (wind-aware emulator) experiments on the `ai/dtaci-envelope` branch. #227 (DtACI) is finished; its results are in `docs/conformal_compare.md` and `AI_README.md`.

The split that works:
- **A many-core Linux box** runs everything CPU-bound: the simulations, the training data and the Monte Carlo evals.
- **The model trains on a GPU:** NVIDIA through PyTorch, or a Mac through MLX.

MLX doesn't install on most Linux servers: its wheels need glibc >= 2.35, and its CUDA backend needs an SM 7.5+ GPU, so not a V100. Don't try `mlx[cuda]` there.

All commands run from `engine/`. The worker counts below are for a 24-core machine.

## 0. Setup

**Linux server:**

```sh
git fetch origin && git switch ai/dtaci-envelope && git pull
cd engine
uv sync
uv run pytest -q     # the MLX tests skip themselves
```

**Mac:**

```sh
cd engine
uv sync --extra ml
```

After that, use `uv run --no-sync`. A plain `uv run` without `--extra ml` uninstalls mlx, and removes anything installed with `uv pip`.

**Long runs on the server:** use `tmux new -s fire` (reattach with `tmux attach -t fire`). A dropped SSH session kills background jobs.

**Python 3.14 on Linux:** the worker pool's helper process (`multiprocessing.forkserver`) can outlive a run, so a script may not exit after printing its report. Its outputs are already written by then. Kill the helper with `pkill -f multiprocessing.forkserver` before the next big job.

## 1. Wind ensemble tuning (server; done for this round)

24 fires, one per worker:

```sh
uv run python -m eval.wind_ensemble --phase tune --workers 24 \
  --cache wind_tune.pkl --out wind_tune.md --json wind_tune.json > wind_tune.log 2>&1
```

The end of `wind_tune.md` names the selected setting. If it isn't `shifts 0.25/h`, set the `shift_rate_per_h` default in `engine/forecast/wind.py` to match, and commit it before step 3. This round it selected 0.25/h, so no change was needed.

## 2. Emulator data (server; done for this round)

```sh
uv run python -m emulator.data --wind-aware --samples 4000 --out emulator/data/train_wind --seed 2 --workers 20 \
  > datagen_train.log 2>&1 &
uv run python -m emulator.data --wind-aware --samples 400 --out emulator/data/test_wind --seed 3 --with-32 --workers 4 \
  > datagen_test.log 2>&1 &
wait
```

- **Why 20 + 4:** the training set has 40 shards and the test set 4, so this split keeps all 24 cores busy.
- **Samples:** about a quarter of samples are skipped because the fire burns out before the snapshot. This round gave 3,063 training and 301 test fires.
- **If a run died:** `emulator.data` refuses an `--out` that already has shards. Delete the directory and rerun.
- **Check the shards** before using them:

```sh
uv run python -c "
import glob, numpy as np
for d in ('emulator/data/train_wind', 'emulator/data/test_wind'):
    total, bad = 0, []
    for p in sorted(glob.glob(d + '/*.npz')):
        try:
            z = np.load(p); n = int(z['n']); z['label_' + str(n - 1)]; total += n
        except Exception as e:
            bad.append(p)
    print(d, total, 'samples, bad:', bad or 'none')"
```

## 3. Final eval, Monte Carlo part (server; done for this round)

48 fires, 2 forecasters:

```sh
uv run python -m eval.wind_ensemble --phase final --workers 24 \
  --cache wind_final.pkl --out wind_final.md --json wind_final.json > wind_final.log 2>&1
```

**Exploratory 1/h shift rate** (see AI_README.md for why it's exploratory). This adds one forecaster to the same cache and records only that one:

```sh
uv run python -m eval.wind_ensemble --phase final --explore --workers 24 \
  --cache wind_final.pkl --out wind_final.md --json wind_final.json > wind_final_explore.log 2>&1
```

## 4. Train the wind-aware U-Net

Both options write `emulator/weights/fire_emulator_wind.safetensors` plus a `.json` sidecar, in the layout the engine loads. Training refuses to overwrite an existing weights file unless you pass `--overwrite`.

**Option A: NVIDIA GPU with PyTorch** (on the server, where the data already is):

```sh
# V100 (Volta, sm_70) needs a CUDA 12 build; CUDA 13 builds dropped Volta. Try cu126, else cu128.
uv pip install torch --index-url https://download.pytorch.org/whl/cu126
uv run --no-sync python -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_capability(), torch.cuda.get_arch_list())"
# Expect True, (7, 0), and 'sm_70' in the arch list. If sm_70 is missing, use a different index URL.

uv run --no-sync python -u -m emulator.train --wind-aware --backend torch --device gpu --builders 8 \
  --train emulator/data/train_wind --test emulator/data/test_wind > emulator/data/train_wind.log 2>&1
```

- **`--amp`** (float16 mixed precision) is optional. V100 tensor cores run it faster, but it isn't the recipe the MLX model was trained with. Record it if you use it; the sidecar does.
- **`--builders 8`** gives batch-building threads to the spare cores.
- **Copy to the Mac:** `fire_emulator_wind.safetensors`, `fire_emulator_wind.json` and the log.

**Option B: Mac with MLX** (copy `emulator/data/train_wind/` and `test_wind/` over first):

```sh
uv run --no-sync python -u -m emulator.train --wind-aware \
  --train emulator/data/train_wind --test emulator/data/test_wind > emulator/data/train_wind.log 2>&1
```

## 5. Emulator evaluations

These run wherever the emulator runs: MLX on the Mac, or PyTorch on the server (`Emulator` falls back to PyTorch when MLX isn't installed).

```sh
# The same 48 fires: adds the original and wind-aware U-Nets (plus the 1/h exploratory input with --explore) to the cache
uv run --no-sync python -m eval.wind_ensemble --phase final --emulators --explore \
  --cache wind_final.pkl --out wind_final.md --json wind_final.json > wind_final_emulators.log 2>&1

# 301 held-out test fires: 4 predictors x 2 targets (Brier, calibration, IoU, latency)
uv run --no-sync python -m emulator.evaluate --compare --test emulator/data/test_wind --json emulator_compare.json
```

**Fairness across machines:** the emulator episodes must replay the same fires as the server's Monte Carlo ones. This was checked: a long surge fire and two short fires re-recorded on an M2 Mac matched the Linux server's recordings exactly.

## 6. Bring back for the write-up

- `wind_tune.md` and `.json`
- `wind_final.md` and `.json`
- `wind_final.pkl`
- `emulator_compare.json`
- the training log
- the wind-aware weights and their `.json`

## Notes

- **Caches:** `wind_*.pkl` are reused and extended (only missing forecasters are recorded), and are valid only for the same `--ticks`, `--every` and rollout count. Delete them after any change to the fire model or forecaster.
- **Leakage:**
  - Every forecaster sees only the snapshot at issue.
  - Wind paths start from the wind at issue.
  - The tuning seeds (0-3) and final seeds (4-11) don't overlap.
  - The emulator's test fires (seed 3) are generated separately from its training fires (seed 2).

## 7. Forecast-conditioned wind replay (#231, stage 2)

This tests the conditional wind ensemble on fires driven by real observed 2023-24 winds: 60 fires, 7 forecasters. It's CPU only.

**1. Get the code and the data onto the server.** The data is the station observations plus the HRRR point series, about 60 MB, gitignored. Either copy it from a machine that has it:

```sh
rsync -a <mac>:<repo>/engine/weather/data/ engine/weather/data/
```

or refetch it on the server (offline research data; downloads about 30 GB, keeps about 60 MB):

```sh
cd engine && uv run --with numcodecs python -m weather.fetch --workers 24
```

**2. Run it, in tmux.** The frozen risk models are committed in `engine/forecast/wind_risk_models/`, so don't refit.

```sh
cd engine
git pull
uv sync
uv run pytest -q tests/test_wind_risk.py
uv run python -m eval.wind_replay --workers 24 --cache wind_replay.pkl \
  --out wind_replay.md --json wind_replay.json > wind_replay.log 2>&1
pkill -f multiprocessing.forkserver   # once the report has printed, if it doesn't exit
```

**3. Bring back** `wind_replay.md`, `wind_replay.json`, `wind_replay.pkl` and `wind_replay.log`.
