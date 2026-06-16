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
    """Inverse standard-normal CDF (Acklam's rational approximation, |err| < 1.15e-9)."""
    if p <= 0.0:
        return -math.inf
    if p >= 1.0:
        return math.inf
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    q = p - 0.5
    r = q * q
    return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)
