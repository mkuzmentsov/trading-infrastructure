"""Multi-asset daily time-series trend — managed-futures style (§6.2 Tier-1, roadmap 7b).

Each asset gets its OWN directional trend forecast (long an uptrend, short a downtrend),
is vol-targeted to an equal risk contribution, and the per-asset positions are netted
into one diversified book. This is distinct from cross-sectional momentum (panel.py):
TSM is directional per asset, not a rank-based long/short.

Why multi-asset: diversification across many uncorrelated trends is what historically
makes trend-following work, and it multiplies the independent evidence — the most direct
lever on the Deflated Sharpe the single-asset daily trend fell short on.

Lookahead discipline is identical to the panel backtest: forecast at close_t uses only
data through close_t; weights are shifted one bar before earning returns; turnover costs
are charged when the trade happens.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import metrics as M
from .panel import PanelResult


def ts_trend_forecast(
    panel: pd.DataFrame, fast: int, slow: int, vol_window: int, scale: float = 10.0
):
    """Per-asset trend forecast in [-1, +1] (vol-normalized EMA spread, tanh-squashed),
    plus per-asset per-bar volatility. Causal."""
    ema_f = panel.ewm(span=fast, adjust=False).mean()
    ema_s = panel.ewm(span=slow, adjust=False).mean()
    ret = np.log(panel).diff()
    vol = ret.rolling(vol_window).std()
    raw = (ema_f - ema_s) / panel / vol.replace(0.0, np.nan)
    forecast = np.tanh(raw / scale)
    return forecast, vol


def ts_trend_weights(
    forecast: pd.DataFrame,
    vol: pd.DataFrame,
    *,
    target_vol: float,
    periods_per_year: float,
    leverage: float,
) -> pd.DataFrame:
    """Signed weight per asset, vol-targeted to equal risk and capped at gross ``leverage``.

    Per-asset target vol = target_vol / sqrt(N_active) (the uncorrelated-diversification
    assumption), so each name contributes roughly equally to portfolio vol. Gross exposure
    is then clamped to ``leverage``.
    """
    ann_vol = vol * np.sqrt(periods_per_year)
    n_active = forecast.notna().sum(axis=1).clip(lower=1)
    per_asset_target = target_vol / np.sqrt(n_active)            # Series over dates
    w = forecast.mul(per_asset_target, axis=0) / ann_vol.replace(0.0, np.nan)
    w = w.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    gross = w.abs().sum(axis=1)
    factor = (leverage / gross.replace(0.0, np.nan)).clip(upper=1.0).fillna(1.0)
    return w.mul(factor, axis=0)


def run_ts_trend_backtest(
    panel: pd.DataFrame,
    *,
    fast: int,
    slow: int,
    vol_window: int,
    scale: float,
    target_vol: float,
    leverage: float,
    fee_bps: float,
    rebalance: int,
    periods_per_year: float,
    starting_cash: float = 10_000.0,
) -> PanelResult:
    """Run the diversified TSM book; return net returns, equity, and metrics."""
    rets = panel.pct_change()
    forecast, vol = ts_trend_forecast(panel, fast, slow, vol_window, scale)
    target = ts_trend_weights(forecast, vol, target_vol=target_vol,
                              periods_per_year=periods_per_year, leverage=leverage)

    if rebalance > 1:  # hold weights between rebalances
        target = target.iloc[::rebalance].reindex(target.index).ffill().fillna(0.0)

    w_eff = target.shift(1)                                  # decided at t-1, earns r_t
    gross_ret = (w_eff * rets).sum(axis=1)
    turnover = (target - target.shift(1)).abs().sum(axis=1)
    cost = (turnover * fee_bps / 1e4).shift(1).fillna(0.0)
    port_ret = (gross_ret - cost).dropna()

    equity = starting_cash * (1.0 + port_ret).cumprod()
    report = M.compute(
        equity.to_numpy(), port_ret.to_numpy(), np.array([]),
        periods_per_year=periods_per_year, turnover=float(turnover.mean()),
        exposure=float(w_eff.abs().sum(axis=1).mean()),
    )
    return PanelResult(
        returns=port_ret, equity=equity,
        gross_exposure=float(w_eff.abs().sum(axis=1).mean()),
        avg_turnover=float(turnover.mean()), metrics=report,
    )
