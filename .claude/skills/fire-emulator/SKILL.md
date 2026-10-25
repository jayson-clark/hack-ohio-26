---
name: fire-emulator
description: Regenerate training data for, retrain, evaluate or debug the learned fire emulator (engine/emulator/, MLX U-Net that predicts the Monte Carlo forecast in milliseconds). Use after changing the fire model (sim/fire.py constants, effects, fuel), adding a scenario, when previews look wrong, or to turn the emulator on or off.
---

The emulator mimics `run_forecast`: P(burn by T+30/T+60) from the fire state, per-direction spread (fuel x slope x wind) and suppression at +0/15/30/60 ticks. It's an optional `ml` extra (mlx, Apple silicon). Without it, or without `engine/emulator/weights/fire_emulator.safetensors`, the engine is Monte Carlo only.

Run the engine with it: `ENGINE_EXTRAS=ml` in `.env`, then `make engine`. The log says "fire emulator loaded".

Retrain (needed whenever the fire model changes, since it learned the old one):
```sh
cd engine
uv run python -m emulator.data --samples 6000 --out emulator/data/train          # ~45 min on 11 cores
uv run python -m emulator.data --samples 400 --out emulator/data/test --seed 1 --with-32
uv run --extra ml python -u -m emulator.train --epochs 12 > emulator/data/train.log   # ~25 min; tail -f the log
uv run --extra ml python -m emulator.evaluate                                     # Brier, IoU, calibration, speed
```
Commit the new `weights/fire_emulator.safetensors` and `.json` (training history). `emulator/data/` is gitignored.

Device: training and `evaluate` print the device they use, and the `.json` records it under `trained_on`. `--device auto` (the default) picks MLX's GPU: Metal on Apple silicon, which is what PyTorch calls MPS, or CUDA on NVIDIA. With no GPU it falls back to the CPU, which is slow (`emulator/device.py`). `--device gpu` fails instead of falling back, and `--device cpu` forces the CPU.

Training on an NVIDIA machine (e.g. a cluster) is optional. The repo is macOS-only, so the `ml` extra only installs on Apple silicon. On Linux, sync normally, run `uv pip install "mlx[cuda]"`, then `uv run --no-sync python -m emulator.train --device gpu`. The weights are plain safetensors, so they load on a Mac whichever GPU trained them.

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

Retrained with ember spotting (#118): Brier 0.0034 (32 rollouts: 0.0010), IoU of the 50% area 0.88 (0.94). Screening helps most after wind shifts: the top rec beat a random spot 23/32 vs 17/32 without screening. In steady wind it's within noise.
