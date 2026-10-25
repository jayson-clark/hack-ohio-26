"""Sampling uncertainty of Monte Carlo estimates (#11).

Every probability the engine shows is a count over N simulated rollouts:
"fire reaches Paradise in 24 of 32". With N that small the count is itself
noisy, so these give it an honest range, and tell the rest of the engine
when an estimate is too shaky to say out loud.

This is sampling uncertainty only: how far the estimate could be from what
infinitely many rollouts of the same forecast would say. Whether the
forecast's assumptions hold (wind shifts, moved tokens) is a different
question, handled by conformal calibration (#12, #13).

Everything is NumPy and the standard library; no SciPy.
"""

import math
from statistics import NormalDist

import numpy as np

CONF = 0.9  # two-sided confidence for every interval the engine shows


def _z(conf: float) -> float:
    return NormalDist().inv_cdf(0.5 + conf / 2)


def wilson(k, n, conf: float = CONF):
    """Wilson score interval for k successes in n trials. Works on scalars or
    arrays. Unlike k/n ± z·se, it stays inside [0, 1] and behaves at k = 0 or n."""
    k = np.asarray(k, dtype=float)
    n = np.asarray(n, dtype=float)
    z = _z(conf)
    safe_n = np.maximum(n, 1.0)
    p = k / safe_n
    denom = 1 + z * z / safe_n
    centre = (p + z * z / (2 * safe_n)) / denom
    half = z * np.sqrt(p * (1 - p) / safe_n + z * z / (4 * safe_n * safe_n)) / denom
    lo, hi = np.clip(centre - half, 0, 1), np.clip(centre + half, 0, 1)
    lo, hi = np.where(k <= 0, 0.0, lo), np.where(k >= n, 1.0, hi)  # exact at the edges
    lo, hi = np.where(n > 0, lo, 0.0), np.where(n > 0, hi, 1.0)
    if lo.ndim == 0:
        return float(lo), float(hi)
    return lo, hi


def t_quantile(conf: float, df: int) -> float:
    """Two-sided Student t critical value, e.g. 1.895 for 90% at df = 7.
    Cornish-Fisher expansion around the normal: within 0.2% of exact for
    df >= 3, and conservative (slightly large) for df 1-2."""
    if df <= 0:
        return math.inf
    z = _z(conf)
    g1 = (z**3 + z) / 4
    g2 = (5 * z**5 + 16 * z**3 + 3 * z) / 96
    g3 = (3 * z**7 + 19 * z**5 + 17 * z**3 - 15 * z) / 384
    g4 = (79 * z**9 + 776 * z**7 + 1482 * z**5 - 1920 * z**3 - 945 * z) / 92160
    return z + g1 / df + g2 / df**2 + g3 / df**3 + g4 / df**4


def mean_ci(values, conf: float = CONF) -> tuple[float, float, float]:
    """(mean, lo, hi) of a sample, with a Student t interval. For paired
    comparisons pass the per-rollout differences: recommendations run
    "crew" and "no crew" on the same random draws, so the differences carry
    far less noise than either side alone."""
    v = np.asarray(values, dtype=float).ravel()
    n = len(v)
    if n == 0:
        return 0.0, -math.inf, math.inf
    m = float(v.mean())
    if n == 1:
        return m, -math.inf, math.inf
    half = t_quantile(conf, n - 1) * float(v.std(ddof=1)) / math.sqrt(n)
    return m, m - half, m + half


def confidence_word(lo: float, hi: float) -> str:
    """How firmly to say a probability whose interval is [lo, hi]: 'high'
    under 20 points wide, 'moderate' under 40, else 'low'. With 32 rollouts
    a mid-range count is about 25 points wide (moderate); with 8, about 45 (low)."""
    width = hi - lo
    return "high" if width < 0.2 else "moderate" if width < 0.4 else "low"


def benefit_confidence(mean: float, lo: float, hi: float) -> str:
    """How firmly to state a positive benefit with interval [lo, hi]: 'high'
    if even the low end is at least half the estimate, 'moderate' if it's
    still above zero, else 'low' (and then the engine doesn't show it)."""
    if lo <= 0 or mean <= 0:
        return "low"
    return "high" if lo >= mean / 2 else "moderate"


def overlap(a: tuple[float, float], b: tuple[float, float]) -> bool:
    """Whether two intervals overlap, i.e. the data can't tell them apart."""
    return a[0] <= b[1] and b[0] <= a[1]
