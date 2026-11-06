---
name: fire-emulator
description: Regenerate training data for, retrain, evaluate or debug the learned fire emulator (engine/emulator/, MLX U-Net that predicts the Monte Carlo forecast in milliseconds). Use after changing the fire model (sim/fire.py constants, effects, fuel), adding a scenario, when previews look wrong, or to turn the emulator on or off.
---

The emulator mimics `run_forecast`: P(burn by T+30/T+60) from the fire state, per-direction spread (fuel x slope x wind) and suppression at +0/15/30/60 ticks. It's an optional `ml` extra (mlx, Apple silicon). Without it, or without `engine/emulator/weights/fire_emulator.safetensors`, the engine is Monte Carlo only.

Run the engine with it: `ENGINE_EXTRAS=ml` in `.env`, then `make engine`. The log says "fire emulator loaded". To run without it but keep MLX installed (for example while the weights predate a fire-model change), set `EMULATOR=off`. The log then says "switched off", and previews and crew-spot screening stop. The conformal calibration never uses the emulator, so it works the same either way.

Retrain (needed whenever the fire model changes, since it learned the old one):
```sh
cd engine
uv run python -m emulator.data --samples 6000 --out emulator/data/train          # ~45 min on 11 cores
uv run python -m emulator.data --samples 400 --out emulator/data/test --seed 1 --with-32
uv run --extra ml python -u -m emulator.train > emulator/data/train.log   # 12 epochs, batch 16, ~15 min; tail -f the log
uv run --extra ml python -m emulator.evaluate                                     # Brier, IoU, calibration, speed
```
Commit the new `weights/fire_emulator.safetensors` and `.json` (training history). `emulator/data/` is gitignored.

Device: training and `evaluate` print the device they use, and the `.json` records it under `trained_on`. `--device auto` (the default) picks MLX's GPU: Metal on Apple silicon, which is what PyTorch calls MPS, or CUDA on NVIDIA. With no GPU it falls back to the CPU, which is slow (`emulator/device.py`). `--device gpu` fails instead of falling back, and `--device cpu` forces the CPU.

**Backends:** `emulator.train` trains with MLX on a Mac (Metal) or PyTorch on NVIDIA (CUDA). `--backend auto` (the default) uses PyTorch when it sees a CUDA GPU, else MLX. The recipe is the same either way (`emulator/backends.py`).
- **Weights:** both save MLX's weights layout (`emulator/weights_io.py`, NumPy only), so the engine loads any of them.
- **Equivalence:** `emulator/torch_model.py` is the same net with the same parameter names. The same weights give the same outputs (within 1e-4) in both frameworks; `tests/test_emulator.py` checks it.
- **Inference:** `Emulator` uses MLX if installed, else PyTorch, so the emulator evals also run on a CUDA box.
- **MLX on Linux:** don't use it. Its wheels need glibc >= 2.35 (RHEL/Rocky 9 have 2.34), and its CUDA backend needs an SM 7.5+ GPU (no V100).
- **PyTorch for NVIDIA:** install it by hand, `uv pip install torch --index-url https://download.pytorch.org/whl/cu126`. A V100 needs a CUDA 12 build, since CUDA 13 dropped Volta. Check that `torch.cuda.get_arch_list()` includes your GPU's `sm_XX`. It isn't in the lockfile: an optional, platform-specific install, like the old `mlx[cuda]` note.
- **CUDA run:** `uv run --no-sync python -u -m emulator.train --backend torch --device gpu --builders 8 ...`. `--amp` (float16) and `--torch-compile` are optional speedups, off by default so results match the MLX recipe.
- **The GPU is rarely the bottleneck:** training takes ~15 min on an M2 Max, while data generation is CPU-bound. `docs/wind_experiments_runbook.md` has the full server/Mac workflow.
- **What worked (#229):** run `emulator.data` (and the CPU evals) on a many-core Linux box with a plain `uv sync`; it doesn't import MLX. Copy `emulator/data/<set>/` back, then train and evaluate on the Mac.
- **Big runs:** use `tmux` on the server, since a dropped SSH session kills background jobs.
- **Python 3.14 on Linux:** a stray `multiprocessing.forkserver` can outlive the script. Its outputs are already written; `pkill -f multiprocessing.forkserver`.
- **Bad shards:** `emulator.data` refuses an `--out` that already has shards. If a run died, delete the directory and rerun.

**Wind-aware model (#229).** Same U-Net, 18 inputs: the 15 above plus 3 constant planes holding the label's future-wind uncertainty (`features.wind_code`: shift rate, direction and speed wander of a `forecast.wind.WindScenarios`; zeros = constant wind). The wind channels stay the wind at issue. It has its own data and weights, and never touches the original:
```sh
uv run python -m emulator.data --wind-aware --samples 4000 --out emulator/data/train_wind --seed 2 --workers 20
uv run python -m emulator.data --wind-aware --samples 400 --out emulator/data/test_wind --seed 3 --with-32 --workers 4
uv run --extra ml python -u -m emulator.train --wind-aware --train emulator/data/train_wind --test emulator/data/test_wind > emulator/data/train_wind.log
uv run --extra ml python -m emulator.evaluate --compare --test emulator/data/test_wind   # 4 predictors x 2 targets
```
- **Weights:** `weights/fire_emulator_wind.safetensors`, plus a `.json` sidecar (`wind_aware`, `input_channels`) that `Emulator` reads to build the right net. Training refuses to overwrite existing weights unless `--overwrite`.
- **In the engine:** `EMULATOR=wind` loads it for previews and screening, told `forecast.runner.WIND_MODEL`. The original stays the default.
- **Samples:** about a quarter of samples are skipped because the fire burns out before the snapshot (4000 requested gave 3063).
- **Results:** in AI_README.md.

Training speed (#193): `BUILDERS` threads build batches ahead of the GPU and the step is compiled (`mx.compile`), so an epoch of 5,200 fires takes ~74 s at batch 16 (was ~125 s at batch 8). On maps bigger than `WINDOW` (256 cells), training uses a random 256 x 256 square holding the fire's 76-cell reach, so the 512 x 480 Paradise trains about as fast as today's maps. Inference still runs on the whole map. Inputs are rebuilt per batch rather than held in memory, since a 512 x 480 map's inputs would take tens of GB.
- **Batch 16 is the sweet spot on an M2 Max.** Batch 32 took 264 s an epoch at full map size and learned less per epoch.
- **Don't crop to many shapes.** MLX compiles kernels per input shape; 24 crop shapes never finished 100 steps in 10 min. One fixed `WINDOW` square plus the whole maps is a handful of shapes.
- **Epochs:** the held-out Brier prints after each one. On the bigger maps each sample carries more cells, so start at 8 epochs and add more only if it's still falling.
- **Map size barely matters.** On a map twice as wide and tall, predictions moved 0.006 on average (Brier +3%), so bigger maps need no special handling.

Gotchas:
- Don't run data generation, training and the test suite at once. They fight over CPU and GPU, and training slowed 10x (1.6 s/step instead of 0.16 s).
- Use `python -u` with a log file. Piping through grep buffers the output, so nothing shows for minutes.
- Without GroupNorm the U-Net diverged in a few steps (loss to 1e5). Keep the norms and grad clipping.
- `uv run` without `--extra ml` uninstalls mlx from the venv, which is normal. `--offline` works since mlx is cached.
- Flipped training data must swap the 8 directional channels (`features.flip`). `tests/test_emulator.py` checks this against the fire model.
- Burning and burned cells are 1, and cells beyond h king moves from the fire are 0 (`features.finish`). The net only learns the band in between.
- What's honest: previews and screening only. Every shown number, route, alert and commander answer still comes from Monte Carlo.

Baseline (#113, 5,754 training and 385 test fires):

| | Emulator | 32 rollouts |
|---|---|---|
| Brier vs 64-rollout label | 0.0033 | 0.0009 |
| IoU of the 50% area | 0.88 | 0.94 |
| Time per forecast | 6 ms | ~0.6 s |

Retrained with ember spotting (#118): Brier 0.0034 (32 rollouts: 0.0010), IoU of the 50% area 0.88 (0.94).

Retrained at C2 0.3 with model noise in the labels, plus Marshall (#170; 5,600 training and 342 test fires):
- **What changed in the data:** each label uses its own `C2` (`C2_RANGE` 0.22–0.4), a `P_H_SCALE` of 0.85–1.15, and per-rollout wind (`LABEL_WIND`) in `emulator/data.py`. The test set's `p32` stays at the nominal constants (what the engine shows).
- **Brier against the hedged label:** emulator 0.0038, 32 rollouts 0.0039.
- **Overlap with the engine's forecast:** 79% for the 50% outline. The preview's P ≥ 0.1 area is about 27% larger and its P ≥ 0.9 core about half the size.
- **Expect those numbers to differ:** the emulator learns the hedged forecast, so it never matches the nominal Monte Carlo exactly.
- **Timing:** data took 16 min, training 34 min (12 epochs, batch 8). Screening helps most after wind shifts: the top rec beat a random spot 23/32 vs 17/32 without screening. In steady wind it's within noise.
