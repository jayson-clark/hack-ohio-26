"""Sampling-uncertainty helpers (#11)."""

import math

import numpy as np
import pytest

from uq.mc import benefit_confidence, confidence_word, mean_ci, overlap, t_quantile, wilson

# Two-sided 90% Student t critical values from a standard table.
T90 = {3: 2.353, 5: 2.015, 7: 1.895, 10: 1.812, 15: 1.753, 30: 1.697, 63: 1.669}


@pytest.mark.parametrize("df,expected", sorted(T90.items()))
def test_t_quantile_matches_the_table(df, expected):
    assert math.isclose(t_quantile(0.9, df), expected, rel_tol=0.002)


@pytest.mark.parametrize("p,n", [(0.05, 32), (0.3, 32), (0.5, 8), (0.75, 16), (0.95, 32), (0.6, 64)])
def test_wilson_covers_about_90_percent(p, n):
    rng = np.random.default_rng(0)
    k = rng.binomial(n, p, size=20000)
    lo, hi = wilson(k, n, 0.9)
    coverage = ((lo <= p) & (p <= hi)).mean()
    assert 0.85 <= coverage <= 0.97, coverage  # Wilson is approximate at small n, never wildly off


def test_wilson_edges():
    assert wilson(0, 32) == (0.0, pytest.approx(0.0779, abs=1e-3))
    lo, hi = wilson(32, 32)
    assert hi == 1.0 and lo == pytest.approx(0.922, abs=1e-3)
    assert wilson(0, 0) == (0.0, 1.0)
    lo, hi = wilson(np.array([5, 24]), np.array([8, 32]))
    assert lo.shape == (2,) and (lo < hi).all()


def test_mean_ci_covers_for_paired_differences():
    rng = np.random.default_rng(1)
    hits = 0
    for _ in range(4000):
        d = rng.normal(3.0, 10.0, size=8)
        _, lo, hi = mean_ci(d, 0.9)
        hits += lo <= 3.0 <= hi
    assert 0.87 <= hits / 4000 <= 0.93


def test_mean_ci_degenerate_samples():
    assert mean_ci([]) == (0.0, -math.inf, math.inf)
    m, lo, hi = mean_ci([4.0])
    assert m == 4.0 and lo == -math.inf and hi == math.inf
    assert mean_ci([2.0, 2.0, 2.0]) == (2.0, 2.0, 2.0)


def test_words():
    assert confidence_word(*wilson(24, 32)) == "moderate"
    assert confidence_word(*wilson(5, 8)) == "low"
    assert confidence_word(0.6, 0.7) == "high"
    assert benefit_confidence(10, 6, 14) == "high"
    assert benefit_confidence(10, 1, 19) == "moderate"
    assert benefit_confidence(10, -2, 22) == "low"
    assert overlap((1, 3), (2, 5)) and not overlap((1, 2), (3, 4))
