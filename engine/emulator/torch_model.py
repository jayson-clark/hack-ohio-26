"""The fire emulator's U-Net in PyTorch, for training and inference on
NVIDIA GPUs (CUDA), where MLX doesn't run (see the fire-emulator skill).

It is emulator.model.FireUNet layer for layer: the same parameter names, the
same GroupNorm (8 groups, eps 1e-5), exact GELU, nearest 2x upsampling and
max pooling, so a set of weights gives the same outputs in either framework
(tests/test_emulator.py checks this). Only the memory layout differs:
PyTorch is NCHW, MLX NHWC. Weights are read and written in MLX's layout
(emulator.weights_io), so the engine on a Mac loads a model trained here.
"""

from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as tf
from torch import nn

from emulator import weights_io
from emulator.features import N_CHANNELS

WIDTHS = (32, 64, 96, 128)  # emulator.model.WIDTHS


class Block(nn.Module):
    def __init__(self, cin: int, cout: int, dilation: int = 1) -> None:
        super().__init__()
        self.a = nn.Conv2d(cin, cout, 3, padding=dilation, dilation=dilation)
        self.b = nn.Conv2d(cout, cout, 3, padding=dilation, dilation=dilation)
        self.na = nn.GroupNorm(8, cout, eps=1e-5)
        self.nb = nn.GroupNorm(8, cout, eps=1e-5)

    def forward(self, x):
        return tf.gelu(self.nb(self.b(tf.gelu(self.na(self.a(x))))))


class FireUNet(nn.Module):
    def __init__(self, cin: int = N_CHANNELS, widths=WIDTHS) -> None:
        super().__init__()
        w1, w2, w3, w4 = widths
        self.e1, self.e2, self.e3, self.e4 = Block(cin, w1), Block(w1, w2), Block(w2, w3), Block(w3, w4)
        self.mid = nn.ModuleList([Block(w4, w4, 2), Block(w4, w4, 4)])
        self.d3, self.d2, self.d1 = Block(w4 + w3, w3), Block(w3 + w2, w2), Block(w2 + w1, w1)
        self.out = nn.Conv2d(w1, 2, 1)

    def forward(self, x):  # x: (B, C, H, W), H and W multiples of 8
        pool = lambda t: tf.max_pool2d(t, 2, 2)  # noqa: E731
        up = lambda t: tf.interpolate(t, scale_factor=2, mode="nearest")  # noqa: E731
        s1 = self.e1(x)
        s2 = self.e2(pool(s1))
        s3 = self.e3(pool(s2))
        y = self.e4(pool(s3))
        for m in self.mid:
            y = y + m(y)
        y = self.d3(torch.cat([up(y), s3], dim=1))
        y = self.d2(torch.cat([up(y), s2], dim=1))
        y = self.d1(torch.cat([up(y), s1], dim=1))
        return self.out(y)  # (B, 2, H, W) logits


def load(net: FireUNet, path: str | Path) -> None:
    """Weights from an MLX-layout file into `net`."""
    state = {k: torch.from_numpy(v) for k, v in weights_io.to_torch(weights_io.read(path)).items()}
    net.load_state_dict(state, strict=True)


def save(net: FireUNet, path: str | Path) -> None:
    """`net`'s weights to an MLX-layout file."""
    state = {k: v.detach().float().cpu().numpy() for k, v in net.state_dict().items()}
    weights_io.write(path, weights_io.to_mlx(state))


def device(prefer: str = "auto") -> torch.device:
    """auto: CUDA if there is one, else CPU; gpu: CUDA or an error; cpu."""
    if prefer not in ("auto", "gpu", "cpu"):
        raise ValueError(f"unknown device {prefer!r}: use auto, gpu or cpu")
    if prefer != "cpu" and torch.cuda.is_available():
        return torch.device("cuda")
    if prefer == "gpu":
        raise SystemExit("no CUDA GPU for PyTorch here (for a Mac's GPU, train with MLX: --backend mlx)")
    return torch.device("cpu")


def describe(dev: torch.device) -> dict:
    """Like emulator.device.select's dict, for the training record."""
    if dev.type == "cuda":
        p = torch.cuda.get_device_properties(dev)
        return {"backend": "cuda (pytorch)", "device": p.name, "memory_gb": round(p.total_memory / 2**30, 1),
                "compute_capability": f"{p.major}.{p.minor}"}
    return {"backend": "cpu (pytorch)", "device": "CPU", "memory_gb": None}


def predict(net: FireUNet, x: np.ndarray, dev: torch.device) -> np.ndarray:
    """Probabilities (B, 2, H, W) for a padded batch (B, C, H, W)."""
    with torch.no_grad():
        p = torch.sigmoid(net(torch.from_numpy(np.ascontiguousarray(x, np.float32)).to(dev)))
    return p.float().cpu().numpy()
