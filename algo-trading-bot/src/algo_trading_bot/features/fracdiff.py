"""Fractional differentiation (§2.2).

Naive differencing makes a series stationary but erases its memory. Fractional
differentiation finds the *minimum* differencing order d (often well below 1) that
passes a stationarity test while retaining maximal memory — better features for ML
(López de Prado, AFML ch. 5).
"""

from __future__ import annotations

import numpy as np


def frac_diff_weights(d: float, threshold: float = 1e-5) -> np.ndarray:
    """Binomial weights for fixed-width-window fractional differencing of order ``d``.

    Weights are generated until their magnitude falls below ``threshold``.
    """
    weights = [1.0]
    k = 1
    while True:
        w = -weights[-1] * (d - k + 1) / k
        if abs(w) < threshold:
            break
        weights.append(w)
        k += 1
    return np.array(weights[::-1])


def frac_diff(series: np.ndarray, d: float, threshold: float = 1e-5) -> np.ndarray:
    """Fixed-width fractionally-differenced series. Leading window is NaN (no lookahead)."""
    raise NotImplementedError("convolve `series` with frac_diff_weights(d); pad front with NaN")


def min_ffd_order(series: np.ndarray, max_d: float = 1.0) -> float:
    """Smallest d in (0, max_d] whose fracdiff series is stationary (ADF). Search inside
    CV folds only — never on the full sample (NFR3)."""
    raise NotImplementedError("grid-search d, ADF-test each; return first stationary")
