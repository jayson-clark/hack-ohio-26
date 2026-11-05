"""The fire emulator network and its runtime wrapper (#113). Needs MLX
(Apple silicon): `uv sync --extra ml`. Without it, `load_emulator()` returns
None and the engine runs exactly as before.

A small U-Net: three 2x downsamplings, then dilated convolutions at 1/8
scale, so each output sees ~160 cells around it, more than the 60 a fire can
travel in the T+60 horizon. Two output logits per cell, for T+30 and T+60.
"""

import os
from pathlib import Path

import numpy as np

import json

from emulator.features import MULTIPLE, N_CHANNELS, finish, from_snapshot, wind_code

WEIGHTS = Path(__file__).resolve().parent / "weights" / "fire_emulator.safetensors"
# The wind-aware model (#229): trained on wind-scenario ensemble labels, with
# the ensemble's uncertainty as 3 extra input planes. A separate file, so the
# original stays the baseline; EMULATOR=wind loads this one in the engine.
WIND_WEIGHTS = WEIGHTS.with_name("fire_emulator_wind.safetensors")
WIDTHS = (32, 64, 96, 128)

try:
    import mlx.core as mx
    import mlx.nn as nn
except ImportError:  # the ml extra isn't installed: the engine falls back to Monte Carlo only
    mx = nn = None


if nn is not None:

    class Block(nn.Module):
        def __init__(self, cin: int, cout: int, dilation: int = 1) -> None:
            super().__init__()
            self.a = nn.Conv2d(cin, cout, 3, padding=dilation, dilation=dilation)
            self.b = nn.Conv2d(cout, cout, 3, padding=dilation, dilation=dilation)
            self.na = nn.GroupNorm(8, cout, pytorch_compatible=True)
            self.nb = nn.GroupNorm(8, cout, pytorch_compatible=True)

        def __call__(self, x):
            return nn.gelu(self.nb(self.b(nn.gelu(self.na(self.a(x))))))

    class FireUNet(nn.Module):
        def __init__(self, cin: int = N_CHANNELS, widths=WIDTHS) -> None:
            super().__init__()
            w1, w2, w3, w4 = widths
            self.e1, self.e2, self.e3, self.e4 = Block(cin, w1), Block(w1, w2), Block(w2, w3), Block(w3, w4)
            self.mid = [Block(w4, w4, 2), Block(w4, w4, 4)]
            self.d3, self.d2, self.d1 = Block(w4 + w3, w3), Block(w3 + w2, w2), Block(w2 + w1, w1)
            self.out = nn.Conv2d(w1, 2, 1)
            self.pool = nn.MaxPool2d(2, 2)
            self.up = nn.Upsample(scale_factor=2, mode="nearest")

        def __call__(self, x):  # x: (B, H, W, C), H and W multiples of 8
            s1 = self.e1(x)
            s2 = self.e2(self.pool(s1))
            s3 = self.e3(self.pool(s2))
            y = self.e4(self.pool(s3))
            for m in self.mid:
                y = y + m(y)
            y = self.d3(mx.concatenate([self.up(y), s3], axis=-1))
            y = self.d2(mx.concatenate([self.up(y), s2], axis=-1))
            y = self.d1(mx.concatenate([self.up(y), s1], axis=-1))
            return self.out(y)  # (B, H, W, 2) logits


def pad_to(x: np.ndarray, multiple: int = MULTIPLE) -> tuple[np.ndarray, int, int]:
    """Zero-pad (..., H, W) up to multiples of `multiple`; returns the original size."""
    h, w = x.shape[-2:]
    ph, pw = -h % multiple, -w % multiple
    if ph or pw:
        x = np.pad(x, [(0, 0)] * (x.ndim - 2) + [(0, ph), (0, pw)])
    return x, h, w


def sidecar(path: Path) -> dict:
    """The training record saved next to the weights (emulator.train)."""
    try:
        return json.loads(Path(path).with_suffix(".json").read_text())
    except (OSError, ValueError):
        return {}


class Emulator:
    """Loaded weights, ready to predict. predict() takes a batch of input
    stacks (B, C, H, W) for one map and returns raw probabilities (B, 2, H, W);
    inputs() builds that stack for a snapshot; forecast() does a whole
    snapshot, certain cells included. A wind-aware model (its sidecar says
    "wind_aware") also takes the forecast's wind uncertainty, a
    forecast.wind.WindScenarios or None for constant wind."""

    def __init__(self, path: Path = WEIGHTS, wind_model=None) -> None:
        meta = sidecar(path)
        self.wind_aware = bool(meta.get("wind_aware", False))
        self.wind_model = wind_model
        self.net = FireUNet(cin=int(meta.get("input_channels", N_CHANNELS)))
        self.net.load_weights(str(path))
        self.net.eval()

    def inputs(self, snapshot) -> np.ndarray:
        """Input channels (C, H, W) for a snapshot, as this model expects them."""
        return from_snapshot(snapshot, wind_code(self.wind_model) if self.wind_aware else None)

    def predict(self, x: np.ndarray) -> np.ndarray:
        x, h, w = pad_to(x.astype(np.float32))
        logits = self.net(mx.array(x.transpose(0, 2, 3, 1)))
        p = mx.sigmoid(logits)
        mx.eval(p)
        return np.array(p).transpose(0, 3, 1, 2)[:, :, :h, :w]

    def forecast(self, snapshot) -> np.ndarray:
        """P(burn by T+30, T+60), float32 (2, H, W), like Forecast.probability."""
        return finish(self.predict(self.inputs(snapshot)[None])[0], snapshot.state)


def disabled() -> bool:
    """EMULATOR=off (or 0, false, no) in the environment turns it off: the
    engine runs Monte Carlo only, as without the ml extra. The engine's
    worker processes inherit it, so screening is off too."""
    return os.environ.get("EMULATOR", "").strip().lower() in ("off", "0", "false", "no")


def load_emulator(path: Path | None = None) -> Emulator | None:
    """The trained emulator, or None when it's switched off (EMULATOR=off) or
    there's no MLX or no weights. EMULATOR=wind picks the wind-aware model,
    told the live forecast's wind model (forecast.runner.WIND_MODEL)."""
    if path is None:
        path = WIND_WEIGHTS if os.environ.get("EMULATOR", "").strip().lower() == "wind" else WEIGHTS
    if disabled() or nn is None or not path.exists():
        return None
    from forecast.runner import WIND_MODEL

    return Emulator(path, wind_model=WIND_MODEL)
