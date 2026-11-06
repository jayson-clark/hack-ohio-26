"""Train the fire emulator on emulator.data shards (#113).

    cd engine && uv run --extra ml python -m emulator.train --epochs 15     # Mac: MLX on the GPU (Metal)
    cd engine && uv run python -m emulator.train --backend torch --device gpu   # NVIDIA: PyTorch on CUDA
    cd engine && uv run --extra ml python -m emulator.train --device cpu   # force a device
    cd engine && uv run --extra ml python -u -m emulator.train --wind-aware \
        --train emulator/data/train_wind --test emulator/data/test_wind      # -> weights/fire_emulator_wind.* (#229)

--wind-aware trains the wind-aware model: the same U-Net with 3 more input
planes (the label's future-wind uncertainty, features.wind_code) on
emulator.data --wind-aware shards. It writes its own weights file and never
overwrites an existing one unless --overwrite is given.

Backends (emulator/backends.py), one recipe: --backend auto uses PyTorch
when it sees a CUDA GPU, else MLX (Metal on Apple silicon), else PyTorch on
the CPU. MLX doesn't install on most Linux GPU servers (glibc, GPU age), so
NVIDIA training goes through PyTorch: `uv pip install torch` (on a V100, a
CUDA 12 build, e.g. --index-url https://download.pytorch.org/whl/cu126;
CUDA 13 builds dropped Volta). Either way the weights are saved in MLX's
layout (emulator.weights_io), which the engine loads; the two networks give
the same outputs for the same weights (tests/test_emulator.py).

Loss is binary cross-entropy against the Monte Carlo labels, only on the
cells the net has to predict (features.masks): burning and burned cells are
certainly 1 and out-of-reach cells certainly 0. Training uses random flips,
with the directional channels swapped to match. Each epoch reports the
held-out Brier score next to a 32-rollout forecast's, so it's clear whether
the net is as good as what the engine draws today.

Speed (#193): BUILDERS threads build upcoming batches while the GPU runs the
current one, and with MLX the training step is compiled (mx.compile), once
per input shape. With PyTorch, --torch-compile and --amp (float16) are
optional speedups, off by default. Loss masks are computed once; inputs are rebuilt per batch, because
holding every input of a 512 x 480 map in memory would take tens of GB.

Map size: the net is fully convolutional, so it runs on any map. On a map
twice as wide and tall (terrain mirrored outward), predictions moved 0.006 on
average and the Brier score rose 3%, so inference uses the whole map. On maps
bigger than WINDOW, training uses a random WINDOW x WINDOW square that holds
the fire's reach (anything farther can't change a label), so a big map
doesn't make training slower. Every map side no bigger than WINDOW is kept
whole, so there are only a few input shapes and few compiles.
"""

import argparse
import glob
import json
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from emulator import backends
from emulator import features as F
from emulator.data import _scenario, load
from emulator.model import WEIGHTS, WIND_WEIGHTS, pad_to
from sim.fire import BURNING, Wind

WINDOW = 256  # cells: on bigger maps, train on a square this size around the fire
REACH = max(F.HORIZONS) + 16  # the fire's reach by the longest horizon, plus context
BUILDERS = 4  # threads building batches ahead of the GPU (--builders)


def prepare(r: dict, wind_aware: bool = False) -> dict:
    """A sample with its loss mask (computed once) and the fire's bounding box.
    For the wind-aware model, also its wind-uncertainty planes' values."""
    _, open_ = F.masks(r["state"])
    ys, xs = np.nonzero(r["state"] >= BURNING)
    out = {"row": r, "m": open_, "box": (ys.min(), ys.max(), xs.min(), xs.max())}
    if wind_aware:
        if "wind_model" not in r:
            raise SystemExit("--wind-aware needs emulator.data --wind-aware shards (no wind_model in this data)")
        out["wind_unc"] = r["wind_model"]
    return out


def window(s: dict, rng: np.random.Generator | None = None) -> tuple[slice, slice]:
    """A random WINDOW-sized square holding the fire's reach (a map side no
    bigger than WINDOW stays whole), or the whole map if the reach is bigger.
    Without rng, the whole map."""
    h, w = s["m"].shape[1:]
    if rng is None:
        return slice(0, h), slice(0, w)
    y0, y1, x0, x1 = s["box"]
    out = []
    for lo, hi, n in ((y0 - REACH, y1 + REACH, h), (x0 - REACH, x1 + REACH, w)):
        size = min(WINDOW, n)
        lo, hi = max(lo, 0), min(hi, n - 1)
        if hi - lo + 1 > size:
            return slice(0, h), slice(0, w)
        first, last = max(hi - size + 1, 0), min(lo, n - size)
        start = int(rng.integers(first, last + 1))
        out.append(slice(start, start + size))
    return out[0], out[1]


def shape_of(win: tuple[slice, slice]) -> tuple[int, int]:
    return win[0].stop - win[0].start, win[1].stop - win[1].start


def piece(s: dict, win: tuple[slice, slice]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Inputs, label and loss mask inside a window."""
    r, (ys, xs) = s["row"], win
    _, layers = _scenario(r["scenario"])
    x = F.inputs(r["state"][ys, xs], r["burn_left"][ys, xs], layers.spread[:, ys, xs],
                 Wind(*map(float, r["wind"])), r["sup"][:, ys, xs] / 255.0, s.get("wind_unc"))
    return x, r["label"][:, ys, xs] / 255.0, s["m"][:, ys, xs]


def tensors(samples: list[dict], wins: list[tuple[slice, slice]], flips: list[tuple[bool, bool]] | None = None):
    """(x, y, mask) as (B, C, H, W) float32 NumPy arrays, for same-shaped windows."""
    xs, ys, ms = [], [], []
    for i, s in enumerate(samples):
        x, y, m = piece(s, wins[i])
        if flips:
            fy, fx = flips[i]
            x, y, m = F.flip(x, fy, fx), F.flip_grid(y, fy, fx), F.flip_grid(m, fy, fx)
        xs.append(pad_to(x)[0])
        ys.append(pad_to(y)[0])
        ms.append(pad_to(m)[0])
    t = lambda a: np.stack(a).astype(np.float32)  # noqa: E731
    return t(xs), t(ys), t(ms)


def prefetched(make, items, pool: ThreadPoolExecutor, ahead: int = 2 * BUILDERS):
    """make(item) for each item in order, built by the pool up to `ahead`
    items early (NumPy releases the GIL, so threads run in parallel)."""
    items = list(items)
    pending: deque = deque(pool.submit(make, it) for it in items[:ahead])
    for it in items[ahead:]:
        yield pending.popleft().result()
        pending.append(pool.submit(make, it))
    while pending:
        yield pending.popleft().result()


def batches(shapes: list[tuple[int, int]], size: int, rng):
    """Shuffled batches of indices, each of a single input shape."""
    by_shape: dict[tuple, list[int]] = {}
    for i, sh in enumerate(shapes):
        by_shape.setdefault(sh, []).append(i)
    out = []
    for idx in by_shape.values():
        idx = rng.permutation(idx)
        out += [idx[j : j + size] for j in range(0, len(idx), size)]
    return [out[i] for i in rng.permutation(len(out))]


def evaluate(trainer, test: list[dict], rows: list[dict]) -> dict:
    """Masked Brier on held-out samples: emulator vs the label (64 rollouts),
    and a 32-rollout forecast vs the same label when stored."""
    se_emu = se_32 = cells = 0.0
    wins = [window(s) for s in test]
    for b in batches([shape_of(w) for w in wins], 8, np.random.default_rng(0)):
        x, y, m = tensors([test[i] for i in b], [wins[i] for i in b])
        p = trainer.probs(x)
        se_emu += float(((p - y) ** 2 * m).sum())
        cells += float(m.sum())
        if "p32" in rows[b[0]]:
            p32 = np.stack([pad_to(rows[i]["p32"] / 255.0)[0] for i in b])
            se_32 += float(((p32 - y) ** 2 * m).sum())
    out = {"brier_emulator": se_emu / cells}
    if "p32" in rows[0]:
        out["brier_32_rollouts"] = se_32 / cells
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--train", default="emulator/data/train")
    p.add_argument("--test", default="emulator/data/test")
    p.add_argument("--epochs", type=int, default=12)
    p.add_argument("--batch", type=int, default=16)
    p.add_argument("--lr", type=float, default=1.5e-3)
    p.add_argument("--no-compile", action="store_true", help="MLX: run the training step uncompiled")
    p.add_argument("--backend", default="auto", choices=("auto", "mlx", "torch"),
                   help="auto: PyTorch if it sees a CUDA GPU, else MLX, else PyTorch on the CPU")
    p.add_argument("--torch-compile", action="store_true", help="PyTorch: torch.compile the network")
    p.add_argument("--amp", action="store_true", help="PyTorch on CUDA: float16 mixed precision")
    p.add_argument("--builders", type=int, default=BUILDERS, help="threads building batches")
    p.add_argument("--max-steps", type=int, default=0, help="stop each epoch after this many steps (timing runs)")
    p.add_argument("--out", help=f"weights file (default {WEIGHTS.name}, or {WIND_WEIGHTS.name} with --wind-aware)")
    p.add_argument("--wind-aware", action="store_true", help="train the wind-aware model (#229)")
    p.add_argument("--overwrite", action="store_true", help="allow replacing an existing weights file")
    p.add_argument("--seed", type=int, default=0, help="shuffling, windows and flips")
    p.add_argument("--device", default="auto", choices=("auto", "gpu", "cpu"),
                   help="auto: the backend's GPU if there is one, else CPU; gpu fails without one")
    args = p.parse_args()
    args.out = args.out or str(WIND_WEIGHTS if args.wind_aware else WEIGHTS)
    from pathlib import Path

    if Path(args.out).exists() and not args.overwrite:
        raise SystemExit(f"{args.out} exists; pass --overwrite or a new --out (keeps the baseline weights safe)")
    backend = backends.pick(args.backend, args.device)
    t0 = time.perf_counter()
    train = [prepare(r, args.wind_aware) for r in load(sorted(glob.glob(f"{args.train}/*.npz")))]
    test_rows = load(sorted(glob.glob(f"{args.test}/*.npz")))
    test = [prepare(r, args.wind_aware) for r in test_rows]
    print(f"{len(train)} training samples, {len(test)} test; prepared in {time.perf_counter() - t0:.0f} s", flush=True)
    rng = np.random.default_rng(args.seed)
    cin = F.N_CHANNELS_WIND if args.wind_aware else F.N_CHANNELS
    probe = np.random.default_rng(1)
    steps = args.epochs * len(batches([shape_of(window(s, probe)) for s in train], args.batch, probe))
    if args.max_steps:
        steps = min(steps, args.epochs * args.max_steps)
    trainer = backends.make(backend, cin, args.lr, steps, args.seed, args.device,
                            compile=args.torch_compile if backend == "torch" else not args.no_compile, amp=args.amp)
    dev = trainer.info
    print(f"training with {backend} on {dev['device']} ({dev['backend']}); {trainer.n_params:,} parameters", flush=True)
    history = []
    pool = ThreadPoolExecutor(args.builders)
    for epoch in range(args.epochs):
        trainer.train()
        t0, total, count = time.perf_counter(), 0.0, 0
        wins = [window(s, rng) for s in train]
        order = batches([shape_of(w) for w in wins], args.batch, rng)
        if args.max_steps:
            order = order[: args.max_steps]
        flips = [[(bool(rng.integers(2)), bool(rng.integers(2))) for _ in b] for b in order]
        make = lambda k: tensors([train[i] for i in order[k]], [wins[i] for i in order[k]], flips[k])  # noqa: E731
        for x, y, m in prefetched(make, range(len(order)), pool, ahead=2 * args.builders):
            total, count = total + trainer.step(x, y, m), count + 1
            if count % 100 == 0:
                print(f"epoch {epoch + 1} step {count}: loss {total / count:.4f} ({time.perf_counter() - t0:.0f} s)", flush=True)
        train_s = time.perf_counter() - t0
        trainer.eval()
        ev = evaluate(trainer, test, test_rows)
        history.append({"epoch": epoch + 1, "train_bce": total / count, **ev})
        print(json.dumps({**history[-1], "train_seconds": round(train_s), "seconds": round(time.perf_counter() - t0)}),
              flush=True)
        trainer.save(args.out)
    with open(args.out.replace(".safetensors", ".json"), "w") as f:
        json.dump({"parameters": trainer.n_params, "framework": backend, "trained_on": dev,
                   "train_samples": len(train), "test_samples": len(test),
                   "epochs": args.epochs, "batch": args.batch, "lr": args.lr, "seed": args.seed,
                   "amp": bool(args.amp and backend == "torch"),
                   "train_data": args.train, "test_data": args.test,
                   "wind_aware": args.wind_aware,
                   "input_channels": F.N_CHANNELS_WIND if args.wind_aware else F.N_CHANNELS,
                   "history": history}, f, indent=2)


if __name__ == "__main__":
    main()
