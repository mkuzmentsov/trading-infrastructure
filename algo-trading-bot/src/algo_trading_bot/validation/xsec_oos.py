"""Split-honest validation for cross-sectional momentum (§4 lightweight path).

Same discipline as the trend baseline: grid-search the momentum lookback on the TRAIN
segment only, evaluate the winner OUT-OF-SAMPLE, deflate the Sharpe for the number of
trials, and compare against equal-weight buy-and-hold (the long-only crypto benchmark).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
import pandas as pd

from ..backtest import metrics as M
from ..backtest.panel import run_panel_backtest
from ..config import BotConfig
from ..core.types import Symbol
from ..data.bars import PERIODS_PER_YEAR
from .deflated_sharpe import deflated_sharpe_ratio

_LOOKBACKS = (14, 30, 60, 90)


@dataclass
class XSecOOSResult:
    best_lookback: int
    train_sharpe: float
    oos_metrics: M.MetricsReport
    oos_avg_turnover: float
    equal_weight_oos_sharpe: float
    deflated_sharpe: float
    n_trials: int
    n_symbols: int
    split_ts: datetime
    test_bars: int
    trials: list = field(default_factory=list)


def _perbar_sharpe(r: np.ndarray) -> float:
    r = np.asarray(r, dtype=float)
    if r.size < 2 or r.std(ddof=1) == 0:
        return 0.0
    return float(r.mean() / r.std(ddof=1))


def run_xsec_validation(
    config: BotConfig,
    start: datetime,
    end: datetime,
    *,
    train_frac: float = 0.6,
) -> XSecOOSResult:
    """Grid-search the momentum lookback in-sample; evaluate the winner OOS."""
    from ..engine.backtest import Backtester  # store access

    ppy = PERIODS_PER_YEAR[config.bar_interval]
    xs = config.xsec
    fee_bps = config.friction.taker_fee_bps

    store = Backtester(config).store
    symbols = [Symbol(s) for s in config.universe]
    panel = store.close_panel(symbols, start, end, config.bar_interval, venue=config.data_venue)
    if panel.shape[1] < 4 or len(panel) < 200:
        raise RuntimeError(
            f"need >=4 symbols and >=200 bars; got {panel.shape[1]} symbols, {len(panel)} bars. "
            f"Run `atb fetch` for the universe."
        )

    n = len(panel)
    split_i = int(n * train_frac)
    embargo_i = min(split_i + int(n * config.validation.embargo_pct), n - 1)
    train_end_ts = panel.index[split_i]
    test_start_ts = panel.index[embargo_i]

    def run(lookback: int):
        return run_panel_backtest(
            panel, lookback=lookback, skip=xs.skip, top_frac=xs.top_frac,
            rebalance=xs.rebalance, leverage=xs.leverage, fee_bps=fee_bps,
            periods_per_year=ppy, starting_cash=config.starting_cash,
        )

    # 1) In-sample grid search over lookback.
    trials = []
    for lb in _LOOKBACKS:
        res = run(lb)
        tr = res.returns[res.returns.index < train_end_ts].to_numpy()
        trials.append({"lookback": lb, "train_sharpe": M.sharpe(tr, ppy),
                       "train_perbar": _perbar_sharpe(tr)})
    best = max(trials, key=lambda t: t["train_sharpe"])

    # 2) OOS evaluation of the selected lookback.
    best_res = run(best["lookback"])
    test_ret = best_res.returns[best_res.returns.index >= test_start_ts]
    test_eq = best_res.equity[best_res.equity.index >= test_start_ts]
    oos_metrics = M.compute(test_eq.to_numpy(), test_ret.to_numpy(), np.array([]),
                            periods_per_year=ppy, turnover=best_res.avg_turnover)

    # 3) Equal-weight buy-and-hold OOS (long-only crypto benchmark).
    ew = panel.pct_change().mean(axis=1)
    ew_oos = ew[ew.index >= test_start_ts].to_numpy()
    ew_sharpe = M.sharpe(ew_oos, ppy)

    # 4) Deflated Sharpe for the OOS result, penalizing for the lookback grid.
    tr_test = test_ret.to_numpy()
    obs = _perbar_sharpe(tr_test)
    var_sharpe = float(np.var([t["train_perbar"] for t in trials], ddof=1)) if len(trials) > 1 else 0.0
    dsr = 0.0
    if obs != 0 and var_sharpe > 0:
        dsr = deflated_sharpe_ratio(obs, len(tr_test), M.skew(tr_test),
                                    M.kurtosis(tr_test) + 3.0, len(trials), var_sharpe)

    return XSecOOSResult(
        best_lookback=best["lookback"],
        train_sharpe=best["train_sharpe"],
        oos_metrics=oos_metrics,
        oos_avg_turnover=best_res.avg_turnover,
        equal_weight_oos_sharpe=ew_sharpe,
        deflated_sharpe=dsr,
        n_trials=len(trials),
        n_symbols=panel.shape[1],
        split_ts=test_start_ts.to_pydatetime(),
        test_bars=len(test_ret),
        trials=trials,
    )
