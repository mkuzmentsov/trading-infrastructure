"""Cross-sectional momentum panel backtest (Tier-2, §6.2; research path §3.1).

Rank a universe by trailing momentum each rebalance, long the strongest / short the
weakest, dollar-neutral. This is the vectorized first-pass screener the requirements
bless for research — *not* the live path. If an edge survives here, it graduates to
the event engine as a forecast generator (§7); until then this answers the cheap
question: is there any cross-sectional momentum edge in crypto OOS, after costs?

Lookahead discipline (the thing that makes or breaks this):
* signal at close_t uses returns through close_t only;
* the weight decided at close_t is shifted forward one bar before earning returns, so
  a position never earns the same bar that formed it;
* turnover costs are charged when the trade happens, aligned to the same shift.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import metrics as M


def momentum_signal(panel: pd.DataFrame, lookback: int, skip: int = 0) -> pd.DataFrame:
    """Trailing momentum: return over [t-lookback-skip, t-skip]. Causal (uses past only)."""
    shifted = panel.shift(skip)
    return shifted / shifted.shift(lookback) - 1.0


def cross_sectional_weights(
    signal: pd.DataFrame, top_frac: float, rebalance: int, leverage: float = 1.0
) -> pd.DataFrame:
    """Per-bar target weights: long the top ``top_frac`` of ranked names, short the
    bottom ``top_frac``, dollar-neutral with gross exposure == ``leverage``.

    Weights are set on rebalance bars and held (forward-filled) in between.
    """
    # NaN on non-rebalance rows so held weights forward-fill; rebalance rows get a vector.
    weights = pd.DataFrame(np.nan, index=signal.index, columns=signal.columns)
    rebalance_rows = signal.index[::rebalance]
    for t in rebalance_rows:
        row = signal.loc[t].dropna()
        n = len(row)
        k = int(n * top_frac)
        if k < 1 or n < 2 * k:
            weights.loc[t] = 0.0
            continue
        ranked = row.sort_values()
        shorts, longs = ranked.index[:k], ranked.index[-k:]
        w = pd.Series(0.0, index=signal.columns)
        w[longs] = 0.5 / k
        w[shorts] = -0.5 / k
        weights.loc[t] = w.to_numpy() * leverage
    return weights.ffill().fillna(0.0)


@dataclass
class PanelResult:
    returns: pd.Series          # daily portfolio returns, net of costs
    equity: pd.Series
    gross_exposure: float
    avg_turnover: float
    metrics: M.MetricsReport


def run_panel_backtest(
    panel: pd.DataFrame,
    *,
    lookback: int,
    skip: int,
    top_frac: float,
    rebalance: int,
    leverage: float,
    fee_bps: float,
    periods_per_year: float,
    starting_cash: float = 10_000.0,
) -> PanelResult:
    """Run the dollar-neutral momentum book; return net returns, equity, and metrics."""
    rets = panel.pct_change()
    signal = momentum_signal(panel, lookback, skip)
    target = cross_sectional_weights(signal, top_frac, rebalance, leverage)

    w_eff = target.shift(1)                          # decided at t-1, earns return at t
    gross_ret = (w_eff * rets).sum(axis=1)

    turnover = (target - target.shift(1)).abs().sum(axis=1)
    cost = (turnover * fee_bps / 1e4).shift(1).fillna(0.0)   # paid when traded, aligned to w_eff
    port_ret = (gross_ret - cost).dropna()

    equity = starting_cash * (1.0 + port_ret).cumprod()
    report = M.compute(
        equity.to_numpy(), port_ret.to_numpy(), np.array([]),
        periods_per_year=periods_per_year,
        turnover=float(turnover.mean()),
        exposure=float(w_eff.abs().sum(axis=1).mean()),
    )
    return PanelResult(
        returns=port_ret,
        equity=equity,
        gross_exposure=float(w_eff.abs().sum(axis=1).mean()),
        avg_turnover=float(turnover.mean()),
        metrics=report,
    )
