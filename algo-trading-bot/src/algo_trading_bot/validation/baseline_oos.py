"""Split-honest validation for the rule-based baseline (§4, lightweight path).

The full §4 machinery (purged CV, CPCV, PBO) is aimed at *fitted ML models*. The
Tier-1 trend baseline has only a few hyperparameters, so its honest-validation needs
are narrower but non-negotiable:

1. **Tune in-sample only.** Grid-search the trend params on the TRAIN segment and
   pick the best by Sharpe. Touching the test set during selection is leakage (§4.4).
2. **Embargo the boundary.** Drop a gap between train and test so the test segment's
   feature warmup cannot peek at train (§4.1).
3. **Report OOS, after costs.** The number that matters is the TEST-segment Sharpe of
   the in-sample-selected config — never the train number.
4. **Deflate for trials.** With N grid points, the best train Sharpe is upward-biased;
   the Deflated Sharpe Ratio (§4.3) penalizes for N and for return non-normality.

This is deliberately modest. It exercises the real DSR + gate machinery end-to-end
so the ML phase plugs into a working harness rather than a stub.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
import pandas as pd

from ..backtest import metrics as M
from ..config import BotConfig, TrendConfig
from ..data.bars import PERIODS_PER_YEAR
from .deflated_sharpe import deflated_sharpe_ratio

# Default tuning grid. fast < slow always holds for these values.
_FAST = (10, 20, 40)
_SLOW = (60, 120, 240)


@dataclass
class Trial:
    params: dict
    train_sharpe: float
    train_sharpe_perbar: float


@dataclass
class OOSResult:
    best_params: dict
    train_sharpe: float            # in-sample Sharpe of the selected config (annualized)
    oos_metrics: M.MetricsReport   # TEST-segment metrics of the selected config
    default_oos_sharpe: float      # TEST Sharpe of the config's *untuned* params, for contrast
    buy_hold_oos_sharpe: float     # TEST Sharpe of buy-and-hold (context, not the gate)
    deflated_sharpe: float         # DSR probability for the OOS result
    n_trials: int
    split_ts: datetime
    test_bars: int
    trials: list[Trial] = field(default_factory=list)


def _perbar_sharpe(returns: np.ndarray) -> float:
    r = np.asarray(returns, dtype=float)
    if r.size < 2 or r.std(ddof=1) == 0:
        return 0.0
    return float(r.mean() / r.std(ddof=1))


def _grid(base: TrendConfig) -> list[TrendConfig]:
    return [
        TrendConfig(ema_fast=f, ema_slow=s, vol_window=base.vol_window, scale=base.scale)
        for f in _FAST
        for s in _SLOW
        if f < s
    ]


def run_oos_validation(
    config: BotConfig,
    start: datetime,
    end: datetime,
    train_frac: float = 0.6,
    embargo_frac: float | None = None,
) -> OOSResult:
    """Grid-search trend params in-sample, evaluate the winner out-of-sample."""
    from ..engine.backtest import Backtester  # local import avoids a cycle

    ppy = PERIODS_PER_YEAR[config.bar_interval]
    embargo_frac = embargo_frac if embargo_frac is not None else config.validation.embargo_pct

    bt = Backtester(config)
    bars = bt.load_bars(start, end)
    if len(bars) < 500:
        raise RuntimeError(f"only {len(bars)} bars — fetch more history before validating")

    # Time split with an embargo gap between train and test.
    ts = [b.ts for b in bars]
    n = len(ts)
    split_i = int(n * train_frac)
    embargo_i = min(split_i + int(n * embargo_frac), n - 1)
    train_end_ts = pd.Timestamp(ts[split_i])
    test_start_ts = pd.Timestamp(ts[embargo_i])

    def segment(returns: pd.Series, lo=None, hi=None) -> pd.Series:
        idx = returns.index
        mask = pd.Series(True, index=idx)
        if lo is not None:
            mask &= idx >= lo
        if hi is not None:
            mask &= idx < hi
        return returns[mask.to_numpy()]

    # 1) In-sample grid search.
    grid = _grid(config.trend)
    trials: list[Trial] = []
    for variant in grid:
        cfg_v = config.model_copy(update={"trend": variant})
        res = Backtester(cfg_v).run(start, end, bars=bars)
        tr = segment(res.returns, hi=train_end_ts).to_numpy()
        trials.append(
            Trial(
                params={"ema_fast": variant.ema_fast, "ema_slow": variant.ema_slow},
                train_sharpe=M.sharpe(tr, ppy),
                train_sharpe_perbar=_perbar_sharpe(tr),
            )
        )

    best_i = int(np.argmax([t.train_sharpe for t in trials]))
    best = trials[best_i]
    best_variant = grid[best_i]

    # 2) Out-of-sample evaluation of the selected config.
    best_res = Backtester(config.model_copy(update={"trend": best_variant})).run(start, end, bars=bars)
    test_ret = segment(best_res.returns, lo=test_start_ts)
    test_eq = best_res.equity[best_res.equity.index >= test_start_ts]
    test_trades = best_res.trades
    if not test_trades.empty:
        test_trades = test_trades[pd.to_datetime(test_trades["ts"]) >= test_start_ts]
    trade_pnls = test_trades["realized"].to_numpy() if not test_trades.empty else np.array([])
    oos_metrics = M.compute(test_eq.to_numpy(), test_ret.to_numpy(), trade_pnls, periods_per_year=ppy)

    # 3) Contrast: untuned default params, OOS.
    default_res = Backtester(config).run(start, end, bars=bars)
    default_oos_sharpe = M.sharpe(segment(default_res.returns, lo=test_start_ts).to_numpy(), ppy)

    # 4) Buy-and-hold OOS (context).
    closes = pd.Series([b.close for b in bars], index=pd.to_datetime(ts))
    bh = closes[closes.index >= test_start_ts].pct_change().dropna()
    buy_hold_oos = M.sharpe(bh.to_numpy(), ppy)

    # 5) Deflated Sharpe for the OOS result, penalizing for the grid size.
    tr_test = test_ret.to_numpy()
    obs_perbar = _perbar_sharpe(tr_test)
    var_sharpe = float(np.var([t.train_sharpe_perbar for t in trials], ddof=1)) if len(trials) > 1 else 0.0
    dsr = 0.0
    if obs_perbar != 0 and var_sharpe > 0:
        dsr = deflated_sharpe_ratio(
            observed_sharpe=obs_perbar,
            n_obs=len(tr_test),
            skew=M.skew(tr_test),
            kurtosis=M.kurtosis(tr_test) + 3.0,  # DSR wants non-excess kurtosis
            n_trials=len(grid),
            var_sharpe=var_sharpe,
        )

    return OOSResult(
        best_params=best.params,
        train_sharpe=best.train_sharpe,
        oos_metrics=oos_metrics,
        default_oos_sharpe=default_oos_sharpe,
        buy_hold_oos_sharpe=buy_hold_oos,
        deflated_sharpe=dsr,
        n_trials=len(grid),
        split_ts=test_start_ts.to_pydatetime(),
        test_bars=len(test_ret),
        trials=trials,
    )
