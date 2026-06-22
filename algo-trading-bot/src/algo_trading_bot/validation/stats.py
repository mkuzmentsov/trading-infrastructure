"""Small statistical helpers used by the validation harness."""

from __future__ import annotations

import math

import numpy as np


def norm_cdf(x: float) -> float:
    """Standard-normal CDF via the error function (exact, no SciPy dependency)."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def block_bootstrap_sharpe(
    returns: np.ndarray, periods_per_year: float, *, block: int = 21,
    n_boot: int = 2000, seed: int = 0,
) -> dict:
    """Circular block-bootstrap distribution of the annualized Sharpe.

    Resampling in blocks preserves short-horizon autocorrelation (a plain i.i.d. bootstrap
    overstates precision for serially-correlated returns). Returns the point Sharpe, the 5/50/95
    percentiles, and the fraction of resamples with Sharpe > 0 — an honest confidence interval,
    not a single point (roadmap §5b). Deterministic given ``seed`` (no global RNG)."""
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    n = r.size
    if n < block * 2:
        return {"sharpe": 0.0, "ci_low": 0.0, "ci_med": 0.0, "ci_high": 0.0, "p_positive": 0.0, "n": n}

    ann = math.sqrt(periods_per_year)
    point = float(r.mean() / r.std(ddof=1) * ann) if r.std(ddof=1) > 0 else 0.0

    rng = np.random.default_rng(seed)
    n_blocks = int(math.ceil(n / block))
    sharpes = np.empty(n_boot)
    for i in range(n_boot):
        starts = rng.integers(0, n, size=n_blocks)
        idx = (starts[:, None] + np.arange(block)[None, :]).ravel() % n  # circular blocks
        s = r[idx[:n]]
        sd = s.std(ddof=1)
        sharpes[i] = (s.mean() / sd * ann) if sd > 0 else 0.0

    return {
        "sharpe": point,
        "ci_low": float(np.percentile(sharpes, 5)),
        "ci_med": float(np.percentile(sharpes, 50)),
        "ci_high": float(np.percentile(sharpes, 95)),
        "p_positive": float((sharpes > 0).mean()),
        "n": n,
    }
