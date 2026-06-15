"""Performance metrics (§3.3).

Per run: CAGR, vol, Sharpe + deflated Sharpe, Sortino, max drawdown & duration,
turnover, hit rate, profit factor, skew/kurtosis, exposure — plus a per-regime
breakdown. The standard ratios are implemented here; the *deflated* Sharpe (which
penalizes for the number of trials) lives in validation/deflated_sharpe.py because
it depends on the search history, not just one return series.

Skew/kurtosis are first-class (§3.3, principle #12): positive skew is a survival
signal; a high Sharpe built on negative skew is a blow-up waiting to happen.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# Default periods-per-year for annualization; set per bar interval at the call site.
DEFAULT_PERIODS_PER_YEAR = 365 * 24  # 1h bars

# Returns whose std is below this (relative to |mean|) are treated as varianceless.
# numpy's variance has float cancellation that leaves ~1e-19 for "constant" arrays,
# which would otherwise produce an absurd Sharpe.
_VAR_EPS = 1e-12


def _degenerate_std(r: np.ndarray, s: float) -> bool:
    return r.size < 2 or s <= _VAR_EPS or s <= _VAR_EPS * abs(r.mean())


def sharpe(returns: np.ndarray, periods_per_year: float = DEFAULT_PERIODS_PER_YEAR) -> float:
    r = np.asarray(returns, dtype=float)
    s = r.std(ddof=1) if r.size > 1 else 0.0
    if _degenerate_std(r, s):
        return 0.0
    return float(r.mean() / s * np.sqrt(periods_per_year))


def sortino(returns: np.ndarray, periods_per_year: float = DEFAULT_PERIODS_PER_YEAR) -> float:
    r = np.asarray(returns, dtype=float)
    downside = r[r < 0]
    if downside.size == 0:
        return float("inf") if r.mean() > 0 else 0.0
    dd = downside.std(ddof=1)
    if dd == 0:
        return 0.0
    return float(r.mean() / dd * np.sqrt(periods_per_year))


def max_drawdown(equity: np.ndarray) -> tuple[float, int]:
    """Return (max drawdown as a negative fraction, duration in periods)."""
    eq = np.asarray(equity, dtype=float)
    if eq.size == 0:
        return 0.0, 0
    peak = np.maximum.accumulate(eq)
    dd = eq / peak - 1.0
    trough = int(np.argmin(dd))
    peak_idx = int(np.argmax(eq[: trough + 1])) if trough > 0 else 0
    return float(dd.min()), trough - peak_idx


def cagr(equity: np.ndarray, periods_per_year: float = DEFAULT_PERIODS_PER_YEAR) -> float:
    eq = np.asarray(equity, dtype=float)
    if eq.size < 2 or eq[0] <= 0:
        return 0.0
    years = eq.size / periods_per_year
    return float((eq[-1] / eq[0]) ** (1 / years) - 1) if years > 0 else 0.0


def skew(returns: np.ndarray) -> float:
    r = np.asarray(returns, dtype=float)
    if r.size < 3 or r.std() == 0:
        return 0.0
    z = (r - r.mean()) / r.std()
    return float((z**3).mean())


def kurtosis(returns: np.ndarray) -> float:
    """Excess kurtosis (normal = 0)."""
    r = np.asarray(returns, dtype=float)
    if r.size < 4 or r.std() == 0:
        return 0.0
    z = (r - r.mean()) / r.std()
    return float((z**4).mean() - 3.0)


def profit_factor(pnls: np.ndarray) -> float:
    p = np.asarray(pnls, dtype=float)
    gains = p[p > 0].sum()
    losses = -p[p < 0].sum()
    if losses == 0:
        return float("inf") if gains > 0 else 0.0
    return float(gains / losses)


def hit_rate(pnls: np.ndarray) -> float:
    p = np.asarray(pnls, dtype=float)
    return float((p > 0).mean()) if p.size else 0.0


@dataclass
class MetricsReport:
    """The §3.3 deliverable. ``per_regime`` maps regime name -> a nested report."""

    cagr: float
    vol: float
    sharpe: float
    deflated_sharpe: float
    sortino: float
    max_drawdown: float
    drawdown_duration: int
    turnover: float
    hit_rate: float
    profit_factor: float
    skew: float
    kurtosis: float
    exposure: float
    per_regime: dict


def compute(
    equity: np.ndarray,
    returns: np.ndarray,
    trade_pnls: np.ndarray,
    periods_per_year: float = DEFAULT_PERIODS_PER_YEAR,
    deflated: float = 0.0,
    turnover: float = 0.0,
    exposure: float = 0.0,
    per_regime: dict | None = None,
) -> MetricsReport:
    """Assemble the full metrics report from raw series. ``deflated`` comes from the
    validation harness (depends on trial count), so it is passed in."""
    mdd, dur = max_drawdown(equity)
    return MetricsReport(
        cagr=cagr(equity, periods_per_year),
        vol=float(np.std(returns, ddof=1) * np.sqrt(periods_per_year)) if len(returns) > 1 else 0.0,
        sharpe=sharpe(returns, periods_per_year),
        deflated_sharpe=deflated,
        sortino=sortino(returns, periods_per_year),
        max_drawdown=mdd,
        drawdown_duration=dur,
        turnover=turnover,
        hit_rate=hit_rate(trade_pnls),
        profit_factor=profit_factor(trade_pnls),
        skew=skew(returns),
        kurtosis=kurtosis(returns),
        exposure=exposure,
        per_regime=per_regime or {},
    )
