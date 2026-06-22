"""Experiment #5 — per-sleeve trend windows + cluster-aware sizing on the mixed universe.

#4 found mixing macro INTO the crypto TSM hurt, for two fixable reasons:
  (1) one global (fast,slow) can't serve both fast crypto (10/50) and slow macro (20/200);
  (2) √N sizing mis-allocates a heterogeneous (16 correlated + 8 uncorrelated) book.

This harness fixes both:
  - each SLEEVE (crypto / macro) gets its OWN trend window;
  - each sleeve is risk-budgeted to target_vol/√K via its OWN shrunk covariance
    (correlation_aware_weights), then the K sleeves are combined assuming cross-sleeve
    independence — justified by the measured +0.02 crypto-macro correlation.

Joint-grid selection on train, OOS eval, Deflated Sharpe + PBO over the full joint grid (so
the larger search space is penalized honestly). Compares against crypto-only and #4 mixed-global.

Usage:  PYTHONPATH=src python3 scripts/sleeved_tsm_experiment.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from algo_trading_bot.backtest import metrics as M
from algo_trading_bot.backtest.ts_trend import correlation_aware_weights, ts_trend_forecast
from algo_trading_bot.core.types import Symbol
from algo_trading_bot.data.bars import PERIODS_PER_YEAR
from algo_trading_bot.data.store import PointInTimeStore
from algo_trading_bot.validation.cpcv import cscv_pbo
from algo_trading_bot.validation.deflated_sharpe import deflated_sharpe_ratio

CRYPTO = ["BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "DOGE", "AVAX",
          "LINK", "DOT", "LTC", "TRX", "ATOM", "BCH", "ETC", "XLM"]
MACRO = ["SPY", "QQQ", "TLT", "IEF", "GLD", "DBC", "USO", "UUP"]
SLEEVES = {"crypto": CRYPTO, "macro": MACRO}

GRID = [(f, s) for f in (10, 20, 40) for s in (50, 100, 200) if f < s]  # 9 per sleeve

# fixed (a-priori) knobs, same as the TSM baseline
TARGET_VOL, LEVERAGE, FEE_BPS = 0.20, 2.0, 4.5
VOL_WINDOW, SCALE, COV_WINDOW, SHRINK = 48, 10.0, 100, 0.3


def _perbar_sharpe(r: np.ndarray) -> float:
    r = np.asarray(r, float)
    return float(r.mean() / r.std(ddof=1)) if r.size > 1 and r.std(ddof=1) > 0 else 0.0


def combined_target(panel: pd.DataFrame, params: dict, ppy: float) -> pd.DataFrame:
    """Per-sleeve forecast+sizing, each sleeve budgeted to target_vol/√K, then netted."""
    budget = TARGET_VOL / np.sqrt(len(SLEEVES))
    parts = []
    for name, syms in SLEEVES.items():
        cols = [s for s in syms if s in panel.columns]
        sub = panel[cols]
        fast, slow = params[name]
        fc, vol = ts_trend_forecast(sub, fast, slow, VOL_WINDOW, SCALE)
        w = correlation_aware_weights(
            fc, vol, sub.pct_change(), target_vol=budget, periods_per_year=ppy,
            leverage=1e9, cov_window=COV_WINDOW, shrinkage=SHRINK)  # no per-sleeve cap
        parts.append(w)
    combined = pd.concat(parts, axis=1).reindex(columns=panel.columns).fillna(0.0)
    gross = combined.abs().sum(axis=1)
    factor = (LEVERAGE / gross.replace(0.0, np.nan)).clip(upper=1.0).fillna(1.0)  # global cap
    return combined.mul(factor, axis=0)


def backtest(panel: pd.DataFrame, target: pd.DataFrame) -> pd.Series:
    rets = panel.pct_change()
    w_eff = target.shift(1)
    gross_ret = (w_eff * rets).sum(axis=1)
    turnover = (target - target.shift(1)).abs().sum(axis=1)
    cost = (turnover * FEE_BPS / 1e4).shift(1).fillna(0.0)
    return (gross_ret - cost).dropna()


def main() -> int:
    store = PointInTimeStore("./data")
    syms = [Symbol(s) for s in CRYPTO + MACRO]
    panel = store.close_panel(syms, datetime(2017, 1, 1, tzinfo=timezone.utc),
                              datetime.now(timezone.utc), "1d", venue="mixed")
    ppy = PERIODS_PER_YEAR["1d"]
    n = len(panel)
    split_i, embargo = int(n * 0.6), int(n * 0.01)
    train_end = panel.index[split_i]
    test_start = panel.index[min(split_i + embargo, n - 1)]
    print(f"mixed panel: {panel.shape[1]} symbols, {n} bars; OOS from {test_start.date()}")

    # joint grid over (crypto window, macro window) — selected on TRAIN, full-grid PBO/DSR
    returns_by_trial, trials = {}, []
    for cf, cs in GRID:
        for mf, ms in GRID:
            params = {"crypto": (cf, cs), "macro": (mf, ms)}
            ret = backtest(panel, combined_target(panel, params, ppy))
            key = f"c{cf}/{cs}-m{mf}/{ms}"
            returns_by_trial[key] = ret
            tr = ret[ret.index < train_end].to_numpy()
            trials.append({"key": key, "params": params,
                           "train_sharpe": M.sharpe(tr, ppy), "train_perbar": _perbar_sharpe(tr)})
    best = max(trials, key=lambda t: t["train_sharpe"])

    best_ret = returns_by_trial[best["key"]]
    test_ret = best_ret[best_ret.index >= test_start]
    test_eq = 10000.0 * (1 + test_ret).cumprod()
    oos = M.compute(test_eq.to_numpy(), test_ret.to_numpy(), np.array([]),
                    periods_per_year=ppy, turnover=0.0)

    tr_test = test_ret.to_numpy()
    obs = _perbar_sharpe(tr_test)
    var_sharpe = float(np.var([t["train_perbar"] for t in trials], ddof=1))
    dsr = deflated_sharpe_ratio(obs, len(tr_test), M.skew(tr_test), M.kurtosis(tr_test) + 3.0,
                                len(trials), var_sharpe) if obs and var_sharpe > 0 else 0.0
    pbo = cscv_pbo(pd.DataFrame(returns_by_trial).dropna(how="any"), n_blocks=10)

    print("\n=== Sleeved TSM (per-sleeve windows + cluster sizing) ===")
    print(f"selected: crypto window {best['params']['crypto']}, macro window {best['params']['macro']}  "
          f"(train Sharpe {best['train_sharpe']:.2f}, {len(trials)} joint trials)")
    print("-- OUT-OF-SAMPLE --")
    print(f"Sharpe={oos.sharpe:.2f}  Sortino={oos.sortino:.2f}  CAGR={oos.cagr:+.1%}  "
          f"maxDD={oos.max_drawdown:.1%}  vol={oos.vol:.1%}  skew={oos.skew:+.2f}")
    print(f"Deflated Sharpe (P[true SR>0], {len(trials)} trials)={dsr:.3f}")
    print(f"PBO (CSCV)={pbo.pbo:.2f}   P(OOS loss)={pbo.prob_oos_loss:.2f}")
    print("\n-- context (from experiments #4, business-day calendar) --")
    print("  crypto-only (1 window, √N)   OOS Sharpe 0.38  DSR 0.609  PBO 0.04")
    print("  mixed global (1 window, √N)  OOS Sharpe 0.16  DSR 0.512  PBO 0.29")
    print("  mixed global (1 window, corr) OOS Sharpe 0.26  DSR 0.546  PBO 0.32")
    verdict = "BEATS crypto-only DSR (0.609)" if dsr > 0.609 else "does NOT beat crypto-only DSR (0.609)"
    print(f"\nverdict: sleeved DSR {dsr:.3f} — {verdict}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
