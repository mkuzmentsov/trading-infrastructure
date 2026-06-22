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


def multi_window_forecast(
    panel: pd.DataFrame, windows: list[tuple[int, int]], vol_window: int, scale: float = 10.0
):
    """Carver-style blended trend forecast: average the vol-normalized tanh forecasts across
    several (fast, slow) speeds. A single a-priori speed *set* (no window search) — the fast
    components fire on fast trends (crypto), the slow ones on slow trends (macro), so one shared
    set self-adapts across asset classes and removes the grid-search overfitting / DSR deflation.
    Causal. Returns the blended forecast in [-1, 1] and per-asset per-bar volatility."""
    ret = np.log(panel).diff()
    vol = ret.rolling(vol_window).std()
    blended = None
    for fast, slow in windows:
        ema_f = panel.ewm(span=fast, adjust=False).mean()
        ema_s = panel.ewm(span=slow, adjust=False).mean()
        raw = (ema_f - ema_s) / panel / vol.replace(0.0, np.nan)
        fc = np.tanh(raw / scale)
        blended = fc if blended is None else blended + fc
    forecast = blended / max(len(windows), 1)
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


def _shrunk_cov(window_rets: np.ndarray, shrinkage: float) -> np.ndarray:
    """Ledoit-Wolf-style shrinkage of a sample covariance toward a constant-correlation
    target (keeps the average correlation — high for crypto alts — while denoising the noisy
    individual pairwise estimates that wreck a small-sample N-asset covariance)."""
    s = np.cov(window_rets, rowvar=False)
    s = np.atleast_2d(s)
    d = np.diag(s).copy()
    d[d <= 0] = 1e-12
    std = np.sqrt(d)
    corr = s / np.outer(std, std)
    n = s.shape[0]
    off = corr[~np.eye(n, dtype=bool)]
    r_bar = float(off.mean()) if off.size else 0.0
    target = r_bar * np.outer(std, std)
    np.fill_diagonal(target, d)
    return shrinkage * target + (1.0 - shrinkage) * s


def correlation_aware_weights(
    forecast: pd.DataFrame,
    vol: pd.DataFrame,
    rets: pd.DataFrame,
    *,
    target_vol: float,
    periods_per_year: float,
    leverage: float,
    cov_window: int,
    shrinkage: float,
) -> pd.DataFrame:
    """Signed weights scaled so the *portfolio* vol (from a shrunk covariance matrix) hits
    ``target_vol`` — the correlation-aware replacement for the √N independence assumption.

    Raw position per name is inverse-vol risk-scaled (``forecast/ann_vol``, same as the √N
    version's numerator). Then the whole book is scaled by ``target_vol / sqrt(wᵀΣw)`` using
    the annualized shrunk covariance Σ over a trailing window, and gross-capped at ``leverage``.
    When names are highly correlated, √(wᵀΣw) is large → the book scales DOWN (N correlated
    names ≠ N independent bets); the √N rule misses exactly this.
    """
    ann_vol = (vol * np.sqrt(periods_per_year)).replace(0.0, np.nan)
    raw = (forecast / ann_vol).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    r = rets.to_numpy()
    raw_np = raw.to_numpy()
    cols = forecast.shape[1]
    out = np.zeros_like(raw_np)
    for i in range(len(forecast)):
        if i < cov_window:
            continue
        w_raw = raw_np[i]
        if not np.any(w_raw):
            continue
        win = r[i - cov_window:i]                      # returns strictly before t (causal)
        active = np.where(np.abs(w_raw) > 0)[0]
        win_a = win[:, active]
        mask = ~np.isnan(win_a).any(axis=1)
        win_a = win_a[mask]
        if win_a.shape[0] < max(10, cols):             # not enough clean history yet
            continue
        cov_ann = _shrunk_cov(win_a, shrinkage) * periods_per_year
        wa = w_raw[active]
        port_var = float(wa @ cov_ann @ wa)
        if port_var <= 0:
            continue
        scale = target_vol / np.sqrt(port_var)
        out[i] = w_raw * scale
    w = pd.DataFrame(out, index=forecast.index, columns=forecast.columns)
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
    sizing: str = "sqrtn",
    cov_window: int = 100,
    shrinkage: float = 0.3,
) -> PanelResult:
    """Run the diversified TSM book; return net returns, equity, and metrics.

    ``sizing``: ``sqrtn`` (per-asset target_vol/√N, the independence assumption) or ``corr``
    (portfolio vol-target from a shrunk covariance matrix — correlation-aware).
    """
    rets = panel.pct_change()
    forecast, vol = ts_trend_forecast(panel, fast, slow, vol_window, scale)
    if sizing == "corr":
        target = correlation_aware_weights(
            forecast, vol, rets, target_vol=target_vol, periods_per_year=periods_per_year,
            leverage=leverage, cov_window=cov_window, shrinkage=shrinkage)
    else:
        target = ts_trend_weights(forecast, vol, target_vol=target_vol,
                                  periods_per_year=periods_per_year, leverage=leverage)

    if rebalance > 1:  # hold weights between rebalances
        target = target.iloc[::rebalance].reindex(target.index).ffill().fillna(0.0)

    return _panel_result_from_target(panel, target, fee_bps=fee_bps,
                                     periods_per_year=periods_per_year, starting_cash=starting_cash)


def _panel_result_from_target(
    panel: pd.DataFrame, target: pd.DataFrame, *,
    fee_bps: float, periods_per_year: float, starting_cash: float,
) -> PanelResult:
    """Lookahead-safe net backtest of a target-weight book: weights shift one bar before
    earning returns; turnover costs charged when the trade happens."""
    rets = panel.pct_change()
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


def run_sleeved_ts_trend_backtest(
    panel: pd.DataFrame,
    *,
    sleeves: dict[str, list[str]],
    sleeve_params: dict[str, tuple[int, int]],
    vol_window: int,
    scale: float,
    target_vol: float,
    leverage: float,
    fee_bps: float,
    periods_per_year: float,
    cov_window: int = 100,
    shrinkage: float = 0.3,
    starting_cash: float = 10_000.0,
) -> PanelResult:
    """Sleeved managed-futures book (experiment #5): each sleeve trades its OWN trend window
    and is risk-budgeted to ``target_vol/√K`` via its own shrunk covariance, then the K sleeves
    are netted assuming cross-sleeve independence (valid when sleeves are ~uncorrelated). Gross
    is capped globally at ``leverage``. Beats a single-window book on a heterogeneous universe.
    """
    budget = target_vol / np.sqrt(max(len(sleeves), 1))
    parts = []
    for name, syms in sleeves.items():
        cols = [s for s in syms if s in panel.columns]
        if not cols:
            continue
        sub = panel[cols]
        fast, slow = sleeve_params[name]
        forecast, vol = ts_trend_forecast(sub, fast, slow, vol_window, scale)
        parts.append(correlation_aware_weights(
            forecast, vol, sub.pct_change(), target_vol=budget, periods_per_year=periods_per_year,
            leverage=1e9, cov_window=cov_window, shrinkage=shrinkage))  # per-sleeve: no cap
    combined = pd.concat(parts, axis=1).reindex(columns=panel.columns).fillna(0.0)
    gross = combined.abs().sum(axis=1)
    factor = (leverage / gross.replace(0.0, np.nan)).clip(upper=1.0).fillna(1.0)  # global cap
    target = combined.mul(factor, axis=0)
    return _panel_result_from_target(panel, target, fee_bps=fee_bps,
                                     periods_per_year=periods_per_year, starting_cash=starting_cash)
