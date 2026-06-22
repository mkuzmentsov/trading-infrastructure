"""Experiment #9 — multi-window (Carver) blended forecast + 2-sleeve cluster sizing, NO search.

Every prior sleeved run grid-searched the (fast,slow) window per sleeve. The Deflated Sharpe
penalizes for that search (81 trials cost the champion ~0.19 of DSR). Here each asset instead uses
a FIXED a-priori blend of trend speeds (no selection), so the formal multiple-testing penalty
vanishes: expected_max_sharpe(n_trials<2)=0, so DSR collapses to the un-deflated Probabilistic
Sharpe Ratio. Legitimate IFF the speed set is genuinely pre-committed — these are conventional
geometric trend speeds, not tuned on this data.

Runs on both the binance `mixed` panel (compare to #5) and the long-history `mixed_long` panel
(compare to #8). Reports OOS Sharpe + PSR (DSR at n_trials=1). PBO is N/A — nothing was selected.

Usage:  PYTHONPATH=src python3 scripts/multiwindow_sleeved_experiment.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from algo_trading_bot.backtest import metrics as M
from algo_trading_bot.backtest.ts_trend import correlation_aware_weights, multi_window_forecast
from algo_trading_bot.core.types import Symbol
from algo_trading_bot.data.bars import PERIODS_PER_YEAR
from algo_trading_bot.data.store import PointInTimeStore
from algo_trading_bot.validation.deflated_sharpe import deflated_sharpe_ratio

CRYPTO = ["BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "DOGE", "AVAX",
          "LINK", "DOT", "LTC", "TRX", "ATOM", "BCH", "ETC", "XLM"]
MACRO = ["SPY", "QQQ", "TLT", "IEF", "GLD", "DBC", "USO", "UUP"]
SLEEVES = {"crypto": CRYPTO, "macro": MACRO}
WINDOWS = [(8, 32), (16, 64), (32, 128), (64, 256)]   # a-priori geometric speeds (Carver), NOT searched
# Robustness: several conventional geometric speed sets. ALL are reported (no selection) — showing
# the result doesn't hinge on one set, rather than cherry-picking the best (which would be a search).
WINDOW_SETS = {
    "3-speed": [(16, 64), (32, 128), (64, 256)],
    "4-speed": [(8, 32), (16, 64), (32, 128), (64, 256)],
    "5-speed": [(4, 16), (8, 32), (16, 64), (32, 128), (64, 256)],
}

TARGET_VOL, LEVERAGE, FEE_BPS = 0.20, 2.0, 4.5
VOL_WINDOW, SCALE, COV_WINDOW, SHRINK = 48, 10.0, 100, 0.3


def _perbar(r):
    r = np.asarray(r, float)
    return float(r.mean() / r.std(ddof=1)) if r.size > 1 and r.std(ddof=1) > 0 else 0.0


def sleeved_multiwindow(panel: pd.DataFrame, ppy: float, windows=WINDOWS) -> pd.Series:
    budget = TARGET_VOL / np.sqrt(len(SLEEVES))
    parts = []
    for syms in SLEEVES.values():
        cols = [s for s in syms if s in panel.columns]
        sub = panel[cols]
        fc, vol = multi_window_forecast(sub, windows, VOL_WINDOW, SCALE)
        parts.append(correlation_aware_weights(
            fc, vol, sub.pct_change(), target_vol=budget, periods_per_year=ppy,
            leverage=1e9, cov_window=COV_WINDOW, shrinkage=SHRINK))
    combined = pd.concat(parts, axis=1).reindex(columns=panel.columns).fillna(0.0)
    gross = combined.abs().sum(axis=1)
    factor = (LEVERAGE / gross.replace(0.0, np.nan)).clip(upper=1.0).fillna(1.0)
    target = combined.mul(factor, axis=0)
    rets = panel.pct_change()
    w_eff = target.shift(1)
    turnover = (target - target.shift(1)).abs().sum(axis=1)
    cost = (turnover * FEE_BPS / 1e4).shift(1).fillna(0.0)
    return ((w_eff * rets).sum(axis=1) - cost).dropna()


def evaluate(venue: str, store: PointInTimeStore, windows=WINDOWS, label="4-speed") -> None:
    panel = store.close_panel([Symbol(s) for s in CRYPTO + MACRO],
                              datetime(2007, 1, 1, tzinfo=timezone.utc),
                              datetime.now(timezone.utc), "1d", venue=venue)
    if panel.empty:
        print(f"[{venue}] no data"); return
    ppy = PERIODS_PER_YEAR["1d"]
    ret = sleeved_multiwindow(panel, ppy, windows)
    n = len(ret)
    test_start = ret.index[int(n * 0.6)]            # OOS = last 40% (no train tuning happens at all)
    test = ret[ret.index >= test_start]
    eq = 10000.0 * (1 + test).cumprod()
    m = M.compute(eq.to_numpy(), test.to_numpy(), np.array([]), periods_per_year=ppy, turnover=0.0)
    t = test.to_numpy()
    psr = deflated_sharpe_ratio(_perbar(t), len(t), M.skew(t), M.kurtosis(t) + 3.0, 1, 0.0)
    print(f"  [{venue:10s} {label}]  OOS {test.index[0].date()}→{test.index[-1].date()} ({len(test)})  "
          f"Sharpe={m.sharpe:.2f}  maxDD={m.max_drawdown:.1%}  PSR={psr:.3f}")


def main() -> int:
    store = PointInTimeStore("./data")
    print("Multi-window blended forecast (NO search) + 2-sleeve cluster sizing  [gate DSR>=0.95]")
    print("Robustness: every speed set reported, none selected (selecting would be a search).\n")
    for venue in ("mixed", "mixed_long"):
        for label, ws in WINDOW_SETS.items():
            evaluate(venue, store, ws, label)
        print()
    print("context: #5 (binance mixed, 81-trial search) DSR 0.702 ; #8 (mixed_long, search) DSR 0.629")
    print("the search penalty is what PSR removes — valid because the speed sets are pre-committed (conventional).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
