"""Training backends for the fire emulator: MLX (Apple silicon, Metal) and
PyTorch (NVIDIA, CUDA). emulator.train builds batches as NumPy arrays and
hands them to one of these; both train the same U-Net with the same recipe:

- loss: binary cross-entropy on logits, only on the cells the net must
  predict (the mask), averaged over those cells;
- AdamW (weight decay 1e-4), learning rate decaying from `lr` to 0 on a
  cosine over all `steps`;
- gradients clipped to a global norm of 1.0;

and save weights in MLX's layout (emulator.weights_io), which is what the
engine loads. Batches arrive as (B, C, H, W) float32 NumPy arrays.
"""

import numpy as np


def pick(backend: str, device: str) -> str:
    """'mlx' or 'torch'. auto: PyTorch when it sees a CUDA GPU, else MLX when
    it's installed (Metal on a Mac), else PyTorch on the CPU."""
    if backend in ("mlx", "torch"):
        return backend
    if backend != "auto":
        raise ValueError(f"unknown backend {backend!r}: use auto, mlx or torch")
    try:
        import torch

        if device != "cpu" and torch.cuda.is_available():
            return "torch"
    except ImportError:
        torch = None
    try:
        import mlx.core  # noqa: F401

        return "mlx"
    except ImportError:
        if torch is not None:
            return "torch"
    raise SystemExit("neither MLX (Apple silicon: uv sync --extra ml) nor PyTorch (uv pip install torch) is installed")


class MLXTrainer:
    def __init__(self, cin: int, lr: float, steps: int, seed: int, device: str = "auto", compile: bool = True) -> None:
        import mlx.core as mx
        import mlx.nn as nn
        import mlx.optimizers as optim
        from mlx.utils import tree_flatten

        from emulator import device as D
        from emulator.model import FireUNet

        self.mx = mx
        self.info = D.select(device)
        mx.random.seed(seed)
        self.net = FireUNet(cin=cin)
        mx.eval(self.net.parameters())
        self.n_params = sum(v.size for _, v in tree_flatten(self.net.parameters()))
        opt = optim.AdamW(learning_rate=optim.cosine_decay(lr, steps), weight_decay=1e-4)

        def loss_fn(net, x, y, m):
            bce = nn.losses.binary_cross_entropy(net(x), y, with_logits=True, reduction="none")
            return (bce * m).sum() / mx.maximum(m.sum(), 1.0)

        loss_and_grad = nn.value_and_grad(self.net, loss_fn)
        self.state = [self.net.state, opt.state]

        def step(x, y, m):
            loss, grads = loss_and_grad(self.net, x, y, m)
            grads, _ = optim.clip_grad_norm(grads, 1.0)
            opt.update(self.net, grads)
            return loss

        if compile:  # once per input shape (#193)
            from functools import partial

            step = partial(mx.compile, inputs=self.state, outputs=self.state)(step)
        self._step = step

    def _nhwc(self, a: np.ndarray):
        return self.mx.array(a.transpose(0, 2, 3, 1))

    def train(self) -> None:
        self.net.train()

    def eval(self) -> None:
        self.net.eval()

    def step(self, x: np.ndarray, y: np.ndarray, m: np.ndarray) -> float:
        loss = self._step(self._nhwc(x), self._nhwc(y), self._nhwc(m))
        self.mx.eval(self.state, loss)
        return float(loss)

    def probs(self, x: np.ndarray) -> np.ndarray:
        p = self.mx.sigmoid(self.net(self._nhwc(x)))
        self.mx.eval(p)
        return np.array(p).transpose(0, 3, 1, 2)

    def save(self, path: str) -> None:
        self.net.save_weights(path)


class TorchTrainer:
    """PyTorch on CUDA (or the CPU). `amp` runs the forward pass in float16
    with loss scaling (V100s and newer have fp16 tensor cores); off by
    default so results match the MLX recipe."""

    def __init__(self, cin: int, lr: float, steps: int, seed: int, device: str = "auto", compile: bool = False,
                 amp: bool = False) -> None:
        import math

        import torch

        from emulator import torch_model as T

        self.torch = torch
        torch.manual_seed(seed)
        self.dev = T.device(device)
        self.info = T.describe(self.dev)
        if self.dev.type == "cuda":
            torch.backends.cudnn.benchmark = True  # few input shapes, so autotuning pays off
        self.net = T.FireUNet(cin=cin).to(self.dev)
        self.n_params = sum(p.numel() for p in self.net.parameters())
        self.opt = torch.optim.AdamW(self.net.parameters(), lr=lr, weight_decay=1e-4)
        total = max(steps, 1)
        self.sched = torch.optim.lr_scheduler.LambdaLR(
            self.opt, lambda k: 0.5 * (1 + math.cos(math.pi * min(k, total) / total)))
        self.amp = amp and self.dev.type == "cuda"
        self.scaler = torch.amp.GradScaler("cuda", enabled=self.amp)
        self.model = torch.compile(self.net) if compile else self.net

    def _t(self, a: np.ndarray):
        return self.torch.from_numpy(np.ascontiguousarray(a, np.float32)).to(self.dev, non_blocking=True)

    def train(self) -> None:
        self.net.train()

    def eval(self) -> None:
        self.net.eval()

    def step(self, x: np.ndarray, y: np.ndarray, m: np.ndarray) -> float:
        torch = self.torch
        x, y, m = self._t(x), self._t(y), self._t(m)
        with torch.autocast("cuda", dtype=torch.float16, enabled=self.amp):
            logits = self.model(x)
        bce = torch.nn.functional.binary_cross_entropy_with_logits(logits.float(), y, reduction="none")
        loss = (bce * m).sum() / m.sum().clamp(min=1.0)
        self.opt.zero_grad(set_to_none=True)
        self.scaler.scale(loss).backward()
        self.scaler.unscale_(self.opt)
        torch.nn.utils.clip_grad_norm_(self.net.parameters(), 1.0)
        self.scaler.step(self.opt)
        self.scaler.update()
        self.sched.step()
        return float(loss.detach())

    def probs(self, x: np.ndarray) -> np.ndarray:
        with self.torch.no_grad():
            return self.torch.sigmoid(self.model(self._t(x)).float()).cpu().numpy()

    def save(self, path: str) -> None:
        from emulator import torch_model as T

        T.save(self.net, path)


def make(backend: str, cin: int, lr: float, steps: int, seed: int, device: str, compile: bool, amp: bool = False):
    if backend == "mlx":
        return MLXTrainer(cin, lr, steps, seed, device, compile)
    return TorchTrainer(cin, lr, steps, seed, device, compile, amp)
