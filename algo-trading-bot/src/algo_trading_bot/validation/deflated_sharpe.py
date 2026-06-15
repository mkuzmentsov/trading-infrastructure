"""Deflated Sharpe Ratio (§4.3).

A Sharpe estimated after trying N strategy configs is upward-biased: with enough
trials, something looks great by luck. The DSR deflates the observed Sharpe by the
*expected maximum* Sharpe under the null (no skill) given the number of trials and
the non-normality (skew/kurtosis) of returns. DSR is the probability the true
Sharpe exceeds zero after that correction (Bailey & López de Prado, 2014).
"""

from __future__ import annotations

import math

from .stats import norm_cdf


def expected_max_sharpe(n_trials: int, var_sharpe: float) -> float:
    """E[max Sharpe] under the null across ``n_trials`` independent trials.

    Uses the standard extreme-value approximation with the Euler-Mascheroni constant.
    ``var_sharpe`` is the variance of the Sharpe estimates across trials.
    """
    if n_trials < 2:
        return 0.0
    euler = 0.5772156649015329
    z1 = _inv_norm_cdf(1 - 1.0 / n_trials)
    z2 = _inv_norm_cdf(1 - 1.0 / (n_trials * math.e))
    return math.sqrt(var_sharpe) * ((1 - euler) * z1 + euler * z2)


def deflated_sharpe_ratio(
    observed_sharpe: float,
    n_obs: int,
    skew: float,
    kurtosis: float,
    n_trials: int,
    var_sharpe: float,
) -> float:
    """Probability (in [0, 1]) that the true Sharpe > the expected-max-under-null.

    ``observed_sharpe`` and the benchmark are per-observation (not annualized).
    ``kurtosis`` is the (non-excess) fourth moment; pass excess+3 if needed.
    """
    sr0 = expected_max_sharpe(n_trials, var_sharpe)
    denom = math.sqrt(1 - skew * observed_sharpe + (kurtosis - 1) / 4 * observed_sharpe**2)
    if denom == 0:
        return 0.0
    z = (observed_sharpe - sr0) * math.sqrt(n_obs - 1) / denom
    return norm_cdf(z)


def _inv_norm_cdf(p: float) -> float:
    """Inverse standard-normal CDF (Acklam's rational approximation)."""
    raise NotImplementedError("Acklam inverse-normal approximation")
