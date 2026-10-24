"""Train the fire emulator on emulator.data shards (#113).

    cd engine && uv run --extra ml python -m emulator.train --epochs 15

Loss is binary cross-entropy against the Monte Carlo labels, only on the
cells the net has to predict (features.masks): burning and burned cells are
certainly 1 and out-of-reach cells certainly 0. Training uses random flips,
with the directional channels swapped to match. Each epoch reports the
held-out Brier score next to a 32-rollout forecast's, so it's clear whether
the net is as good as what the engine draws today.
"""

import argparse
import glob
import json
import math
import time

import mlx.core as mx
import mlx.nn as nn
import mlx.optimizers as optim
import numpy as np
from mlx.utils import tree_flatten

from emulator import features as F
from emulator.data import _scenario, load
from emulator.model import WEIGHTS, FireUNet, pad_to
from sim.fire import Wind


def tensors(rows: list[dict], flips: list[tuple[bool, bool]] | None = None):
    """(x, y, mask) batches, all (B, H, W, C), for rows of one map."""
    xs, ys, ms = [], [], []
    for i, r in enumerate(rows):
        _, layers = _scenario(r["scenario"])
        x = F.inputs(r["state"], r["burn_left"], layers.spread, Wind(*map(float, r["wind"])), r["sup"] / 255.0)
        y = r["label"] / 255.0
        _, open_ = F.masks(r["state"])
        if flips:
            fy, fx = flips[i]
            x, y, open_ = F.flip(x, fy, fx), F.flip_grid(y, fy, fx), F.flip_grid(open_, fy, fx)
        xs.append(pad_to(x)[0])
        ys.append(pad_to(y.astype(np.float32))[0])
        ms.append(pad_to(open_.astype(np.float32))[0])
    t = lambda a: mx.array(np.stack(a).transpose(0, 2, 3, 1))  # noqa: E731
    return t(xs), t(ys), t(ms)


def loss_fn(net, x, y, m):
    bce = nn.losses.binary_cross_entropy(net(x), y, with_logits=True, reduction="none")
    return (bce * m).sum() / mx.maximum(m.sum(), 1.0)


def batches(rows: list[dict], size: int, rng):
    """Shuffled batches, each from a single map (maps differ in size)."""
    by_map: dict[str, list[int]] = {}
    for i, r in enumerate(rows):
        by_map.setdefault(r["scenario"], []).append(i)
    out = []
    for idx in by_map.values():
        idx = rng.permutation(idx)
        out += [idx[j : j + size] for j in range(0, len(idx), size)]
    return [out[i] for i in rng.permutation(len(out))]


def evaluate(net, rows: list[dict]) -> dict:
    """Masked Brier on held-out samples: emulator vs the label (64 rollouts),
    and a 32-rollout forecast vs the same label when stored."""
    se_emu = se_32 = cells = 0.0
    for b in batches(rows, 8, np.random.default_rng(0)):
        part = [rows[i] for i in b]
        x, y, m = tensors(part)
        p = mx.sigmoid(net(x))
        se_emu += float(((p - y) ** 2 * m).sum())
        cells += float(m.sum())
        if "p32" in part[0]:
            p32 = mx.array(np.stack([pad_to(r["p32"] / 255.0)[0] for r in part]).transpose(0, 2, 3, 1))
            se_32 += float(((p32 - y) ** 2 * m).sum())
    out = {"brier_emulator": se_emu / cells}
    if "p32" in rows[0]:
        out["brier_32_rollouts"] = se_32 / cells
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--train", default="emulator/data/train")
    p.add_argument("--test", default="emulator/data/test")
    p.add_argument("--epochs", type=int, default=15)
    p.add_argument("--batch", type=int, default=8)
    p.add_argument("--lr", type=float, default=1e-3)
    p.add_argument("--out", default=str(WEIGHTS))
    args = p.parse_args()
    train = load(sorted(glob.glob(f"{args.train}/*.npz")))
    test = load(sorted(glob.glob(f"{args.test}/*.npz")))
    print(f"{len(train)} training samples, {len(test)} test", flush=True)
    rng = np.random.default_rng(0)
    net = FireUNet()
    mx.eval(net.parameters())
    n_params = sum(v.size for _, v in tree_flatten(net.parameters()))
    steps = args.epochs * math.ceil(len(train) / args.batch) + 2 * len(set(r["scenario"] for r in train))
    opt = optim.AdamW(learning_rate=optim.cosine_decay(args.lr, steps), weight_decay=1e-4)
    step = nn.value_and_grad(net, loss_fn)
    print(f"{n_params:,} parameters", flush=True)
    history = []
    for epoch in range(args.epochs):
        net.train()
        t0, total, count = time.perf_counter(), 0.0, 0
        for b in batches(train, args.batch, rng):
            flips = [(bool(rng.integers(2)), bool(rng.integers(2))) for _ in b]
            x, y, m = tensors([train[i] for i in b], flips)
            loss, grads = step(net, x, y, m)
            grads, _ = optim.clip_grad_norm(grads, 1.0)
            opt.update(net, grads)
            mx.eval(net.parameters(), opt.state, loss)
            total, count = total + float(loss), count + 1
            if count % 100 == 0:
                print(f"epoch {epoch + 1} step {count}: loss {total / count:.4f} ({time.perf_counter() - t0:.0f} s)", flush=True)
        net.eval()
        ev = evaluate(net, test)
        history.append({"epoch": epoch + 1, "train_bce": total / count, **ev})
        print(json.dumps({**history[-1], "seconds": round(time.perf_counter() - t0)}), flush=True)
        net.save_weights(args.out)
    with open(args.out.replace(".safetensors", ".json"), "w") as f:
        json.dump({"parameters": n_params, "train_samples": len(train), "test_samples": len(test),
                   "epochs": args.epochs, "history": history}, f, indent=2)


if __name__ == "__main__":
    main()
