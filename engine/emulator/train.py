"""Train the fire emulator on emulator.data shards (#113).

    cd engine && uv run --extra ml python -m emulator.train --epochs 15
    cd engine && uv run --extra ml python -m emulator.train --device cpu   # force a device

It trains on whatever GPU MLX finds (emulator/device.py): Metal on Apple
silicon, or CUDA on an NVIDIA machine with mlx[cuda]; otherwise the CPU.

Loss is binary cross-entropy against the Monte Carlo labels, only on the
cells the net has to predict (features.masks): burning and burned cells are
certainly 1 and out-of-reach cells certainly 0. Training uses random flips,
with the directional channels swapped to match. Each epoch reports the
held-out Brier score next to a 32-rollout forecast's, so it's clear whether
the net is as good as what the engine draws today.

Speed (#193): inputs are built once (float16), not every epoch; a thread
builds the next batch while the GPU runs the current one; and the training
step is compiled (mx.compile), once per map shape.

Map size: the net is fully convolutional, so it runs on any map. On a map
twice as wide and tall (terrain mirrored outward), predictions moved 0.006 on
average and the Brier score rose 3%, so a bigger map needs no special handling.
"""

import argparse
import glob
import json
import queue
import threading
import time
from functools import partial

import mlx.core as mx
import mlx.nn as nn
import mlx.optimizers as optim
import numpy as np
from mlx.utils import tree_flatten

from emulator import device as D
from emulator import features as F
from emulator.data import _scenario, load
from emulator.model import WEIGHTS, FireUNet, pad_to
from sim.fire import Wind


def prepare(r: dict) -> dict:
    """A sample's inputs, label and loss mask, built once (float16)."""
    _, layers = _scenario(r["scenario"])
    x = F.inputs(r["state"], r["burn_left"], layers.spread, Wind(*map(float, r["wind"])), r["sup"] / 255.0)
    _, open_ = F.masks(r["state"])
    return {"x": x.astype(np.float16), "y": (r["label"] / 255.0).astype(np.float16), "m": open_.astype(np.float16)}


def tensors(samples: list[dict], flips: list[tuple[bool, bool]] | None = None):
    """(x, y, mask) as (B, H, W, C) MLX arrays, for samples of one map shape."""
    xs, ys, ms = [], [], []
    for i, s in enumerate(samples):
        x, y, m = s["x"], s["y"], s["m"]
        if flips:
            fy, fx = flips[i]
            x, y, m = F.flip(x, fy, fx), F.flip_grid(y, fy, fx), F.flip_grid(m, fy, fx)
        xs.append(pad_to(x)[0])
        ys.append(pad_to(y)[0])
        ms.append(pad_to(m)[0])
    t = lambda a: mx.array(np.stack(a).transpose(0, 2, 3, 1).astype(np.float32))  # noqa: E731
    return t(xs), t(ys), t(ms)


def prefetched(make, items, depth: int = 3):
    """make(item) for each item, built in a background thread so the next
    batch is ready when the GPU finishes the current one."""
    q: queue.Queue = queue.Queue(depth)

    def work():
        for it in items:
            q.put(make(it))
        q.put(None)

    threading.Thread(target=work, daemon=True).start()
    while (b := q.get()) is not None:
        yield b


def loss_fn(net, x, y, m):
    bce = nn.losses.binary_cross_entropy(net(x), y, with_logits=True, reduction="none")
    return (bce * m).sum() / mx.maximum(m.sum(), 1.0)


def batches(samples: list[dict], size: int, rng):
    """Shuffled batches of indices, each from a single map shape."""
    by_shape: dict[tuple, list[int]] = {}
    for i, s in enumerate(samples):
        by_shape.setdefault(s["x"].shape, []).append(i)
    out = []
    for idx in by_shape.values():
        idx = rng.permutation(idx)
        out += [idx[j : j + size] for j in range(0, len(idx), size)]
    return [out[i] for i in rng.permutation(len(out))]


def evaluate(net, test: list[dict], rows: list[dict]) -> dict:
    """Masked Brier on held-out samples: emulator vs the label (64 rollouts),
    and a 32-rollout forecast vs the same label when stored."""
    se_emu = se_32 = cells = 0.0
    for b in batches(test, 8, np.random.default_rng(0)):
        x, y, m = tensors([test[i] for i in b])
        p = mx.sigmoid(net(x))
        se_emu += float(((p - y) ** 2 * m).sum())
        cells += float(m.sum())
        if "p32" in rows[b[0]]:
            p32 = np.stack([pad_to(rows[i]["p32"] / 255.0)[0] for i in b])
            se_32 += float(((mx.array(p32.transpose(0, 2, 3, 1)) - y) ** 2 * m).sum())
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
    p.add_argument("--no-compile", action="store_true", help="run the training step uncompiled")
    p.add_argument("--max-steps", type=int, default=0, help="stop each epoch after this many steps (timing runs)")
    p.add_argument("--out", default=str(WEIGHTS))
    p.add_argument("--device", default="auto", choices=("auto", "gpu", "cpu"),
                   help="auto: Metal or CUDA GPU if MLX has one, else CPU")
    args = p.parse_args()
    dev = D.select(args.device)
    print(f"training on {D.describe(dev)}", flush=True)
    t0 = time.perf_counter()
    train = [prepare(r) for r in load(sorted(glob.glob(f"{args.train}/*.npz")))]
    test_rows = load(sorted(glob.glob(f"{args.test}/*.npz")))
    test = [prepare(r) for r in test_rows]
    print(f"{len(train)} training samples, {len(test)} test; prepared in {time.perf_counter() - t0:.0f} s", flush=True)
    rng = np.random.default_rng(0)
    net = FireUNet()
    mx.eval(net.parameters())
    n_params = sum(v.size for _, v in tree_flatten(net.parameters()))
    steps = args.epochs * len(batches(train, args.batch, np.random.default_rng(0)))
    opt = optim.AdamW(learning_rate=optim.cosine_decay(args.lr, steps), weight_decay=1e-4)
    loss_and_grad = nn.value_and_grad(net, loss_fn)
    print(f"{n_params:,} parameters", flush=True)
    state = [net.state, opt.state]

    def train_step(x, y, m):
        loss, grads = loss_and_grad(net, x, y, m)
        grads, _ = optim.clip_grad_norm(grads, 1.0)
        opt.update(net, grads)
        return loss

    if not args.no_compile:
        train_step = partial(mx.compile, inputs=state, outputs=state)(train_step)
    history = []
    for epoch in range(args.epochs):
        net.train()
        t0, total, count = time.perf_counter(), 0.0, 0
        order = batches(train, args.batch, rng)
        if args.max_steps:
            order = order[: args.max_steps]
        flips = [[(bool(rng.integers(2)), bool(rng.integers(2))) for _ in b] for b in order]
        make = lambda k: tensors([train[i] for i in order[k]], flips[k])  # noqa: E731
        for x, y, m in prefetched(make, range(len(order))):
            loss = train_step(x, y, m)
            mx.eval(state, loss)
            total, count = total + float(loss), count + 1
            if count % 100 == 0:
                print(f"epoch {epoch + 1} step {count}: loss {total / count:.4f} ({time.perf_counter() - t0:.0f} s)", flush=True)
        train_s = time.perf_counter() - t0
        net.eval()
        ev = evaluate(net, test, test_rows)
        history.append({"epoch": epoch + 1, "train_bce": total / count, **ev})
        print(json.dumps({**history[-1], "train_seconds": round(train_s), "seconds": round(time.perf_counter() - t0)}),
              flush=True)
        net.save_weights(args.out)
    with open(args.out.replace(".safetensors", ".json"), "w") as f:
        json.dump({"parameters": n_params, "trained_on": dev, "train_samples": len(train), "test_samples": len(test),
                   "epochs": args.epochs, "batch": args.batch,
                   "history": history}, f, indent=2)


if __name__ == "__main__":
    main()
