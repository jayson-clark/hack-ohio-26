"""Short-term wind-shift risk from forecast-time information (#231).

A logistic model: P(event within h minutes) = sigmoid(b + w . z), where z
are standardized features known at issue time (weather.dataset: the
on-board wind history, and optionally a forecast loaded before flight).
It is tiny on purpose: a handful of multiply-adds, NumPy only, and the
fitted model is a few numbers in a JSON file, so it can run on a drone's
flight computer with no network and no ML runtime.

Fitting is L2-regularized maximum likelihood by Newton's method with
backtracking.
Baselines in the same interface: persistence (P = 0: the wind holds, the
current engine's assumption) and a constant rate (the training base rate,
what an unconditional wind ensemble assumes).
"""

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np


@dataclass
class ShiftRisk:
    features: list[str]
    mean: list[float] = field(default_factory=list)
    scale: list[float] = field(default_factory=list)
    weights: list[float] = field(default_factory=list)
    bias: float = 0.0
    kind: str = "logistic"  # or "constant" / "persistence"

    def predict(self, x: np.ndarray) -> np.ndarray:
        """P(event) for rows of x (n, len(features)), in feature order."""
        x = np.atleast_2d(np.asarray(x, np.float64))
        if self.kind == "persistence":
            return np.zeros(len(x))
        if self.kind == "constant":
            return np.full(len(x), 1.0 / (1.0 + np.exp(-self.bias)))
        z = (x - np.asarray(self.mean)) / np.asarray(self.scale)
        return 0.5 * (1.0 + np.tanh(0.5 * (z @ np.asarray(self.weights) + self.bias)))

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(asdict(self), indent=1))

    @classmethod
    def load(cls, path: str | Path) -> "ShiftRisk":
        return cls(**json.loads(Path(path).read_text()))


def persistence(features: list[str] | None = None) -> ShiftRisk:
    return ShiftRisk(features or [], kind="persistence")


def constant(y: np.ndarray) -> ShiftRisk:
    p = float(np.clip(np.mean(y), 1e-6, 1 - 1e-6))
    return ShiftRisk([], bias=float(np.log(p / (1 - p))), kind="constant")


def _objective(z: np.ndarray, y: np.ndarray, w: np.ndarray, reg: np.ndarray) -> float:
    """Penalized negative log-likelihood, computed stably (log(1 + e^s) via logaddexp)."""
    s = z @ w
    return float(np.sum(np.logaddexp(0.0, s) - y * s) + 0.5 * np.sum(reg * w * w))


def fit(x: np.ndarray, y: np.ndarray, features: list[str], l2: float = 1.0, iters: int = 100) -> ShiftRisk:
    """L2-regularized logistic regression (the bias only negligibly), by
    Newton's method with backtracking: a step that doesn't lower the
    penalized loss is halved until it does, so rare events can't make it
    diverge."""
    x = np.asarray(x, np.float64)
    y = np.asarray(y, np.float64)
    mean = x.mean(axis=0)
    scale = x.std(axis=0)
    scale[scale == 0] = 1.0
    z = np.column_stack([(x - mean) / scale, np.ones(len(x))])
    w = np.zeros(z.shape[1])
    w[-1] = np.log(max(y.mean(), 1e-6) / max(1 - y.mean(), 1e-6))
    reg = np.full(z.shape[1], l2)
    reg[-1] = 1e-4  # a whisker on the bias keeps the Hessian invertible when events are rare
    obj = _objective(z, y, w, reg)
    for _ in range(iters):
        p = 0.5 * (1.0 + np.tanh(0.5 * (z @ w)))  # the logistic, without overflow
        grad = z.T @ (p - y) + reg * w
        hess = (z * (p * (1 - p))[:, None]).T @ z + np.diag(reg)
        step = np.linalg.solve(hess, grad)
        t = 1.0
        while t > 1e-10:
            new = _objective(z, y, w - t * step, reg)
            if new <= obj:
                break
            t *= 0.5
        w -= t * step
        done = obj - new < 1e-10 * max(1.0, abs(obj))
        obj = new
        if done:
            break
    return ShiftRisk(list(features), mean.tolist(), scale.tolist(), w[:-1].tolist(), float(w[-1]))
