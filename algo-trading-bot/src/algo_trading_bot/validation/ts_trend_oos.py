"""Split-honest validation for multi-asset daily time-series trend (§4, roadmap 7b).

Same discipline as the other validators: grid-search the (fast, slow) trend windows on
the TRAIN segment only, evaluate the winner OUT-OF-SAMPLE, deflate for the trial count,
and report PBO. The diversified book should give a steadier OOS Sharpe — and, by adding
independent evidence, a higher Deflated Sharpe — than the single-asset version.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
import pandas as pd

from ..backtest import metrics as M
from ..backtest.ts_trend import run_ts_trend_backtest
from ..config import BotConfig
from ..core.types import Symbol
from ..data.bars import PERIODS_PER_YEAR
from .cpcv import cscv_pbo
from .deflated_sharpe import deflated_sharpe_ratio

# (fast, slow) day-window pairs; fast < slow.
_GRID = [(f, s) for f in (10, 20, 40) for s in (50, 100, 200) if f < s]


@dataclass
class TSTrendOOSResult:
    best_params: dict
    train_sharpe: float
    oos_metrics: M.MetricsReport
    oos_avg_turnover: float
    equal_weight_oos_sharpe: float
    deflated_sharpe: float
    pbo: float
    prob_oos_loss: float
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


def run_ts_trend_validation(
    config: BotConfig, start: datetime, end: datetime, *, train_frac: float = 0.6
) -> TSTrendOOSResult:
    from ..engine.backtest import Backtester

    ppy = PERIODS_PER_YEAR[config.bar_interval]
    tr = config.trend
    fee_bps = config.friction.taker_fee_bps
    risk = config.risk

    store = Backtester(config).store
    symbols = [Symbol(s) for s in config.universe]
    panel = store.close_panel(symbols, start, end, config.bar_interval, venue=config.data_venue)
    if panel.shape[1] < 4 or len(panel) < 200:
        raise RuntimeError(
            f"need >=4 symbols and >=200 bars; got {panel.shape[1]} symbols, {len(panel)} bars."
        )

    n = len(panel)
    split_i = int(n * train_frac)
    embargo_i = min(split_i + int(n * config.validation.embargo_pct), n - 1)
    train_end_ts = panel.index[split_i]
    test_start_ts = panel.index[embargo_i]

    def run(fast, slow):
        return run_ts_trend_backtest(
            panel, fast=fast, slow=slow, vol_window=tr.vol_window, scale=tr.scale,
            target_vol=risk.target_annual_vol, leverage=risk.max_gross_leverage,
            fee_bps=fee_bps, rebalance=config.xsec.rebalance, periods_per_year=ppy,
            starting_cash=config.starting_cash,
        )

    # 1) In-sample grid search; keep return series for the PBO matrix.
    trials, returns_by_trial = [], {}
    for fast, slow in _GRID:
        res = run(fast, slow)
        returns_by_trial[f"{fast}/{slow}"] = res.returns
        tr_ret = res.returns[res.returns.index < train_end_ts].to_numpy()
        trials.append({"fast": fast, "slow": slow, "train_sharpe": M.sharpe(tr_ret, ppy),
                       "train_perbar": _perbar_sharpe(tr_ret)})
    best = max(trials, key=lambda t: t["train_sharpe"])

    # 2) OOS evaluation of the selected windows.
    best_res = run(best["fast"], best["slow"])
    test_ret = best_res.returns[best_res.returns.index >= test_start_ts]
    test_eq = best_res.equity[best_res.equity.index >= test_start_ts]
    oos = M.compute(test_eq.to_numpy(), test_ret.to_numpy(), np.array([]),
                    periods_per_year=ppy, turnover=best_res.avg_turnover)

    # 3) Equal-weight buy-and-hold OOS benchmark.
    ew = panel.pct_change().mean(axis=1)
    ew_sharpe = M.sharpe(ew[ew.index >= test_start_ts].to_numpy(), ppy)

    # 4) Deflated Sharpe + PBO.
    tr_test = test_ret.to_numpy()
    obs = _perbar_sharpe(tr_test)
    var_sharpe = float(np.var([t["train_perbar"] for t in trials], ddof=1)) if len(trials) > 1 else 0.0
    dsr = 0.0
    if obs != 0 and var_sharpe > 0:
        dsr = deflated_sharpe_ratio(obs, len(tr_test), M.skew(tr_test),
                                    M.kurtosis(tr_test) + 3.0, len(trials), var_sharpe)
    pbo_res = cscv_pbo(pd.DataFrame(returns_by_trial).dropna(how="any"), n_blocks=10)

    return TSTrendOOSResult(
        best_params={"ema_fast": best["fast"], "ema_slow": best["slow"]},
        train_sharpe=best["train_sharpe"], oos_metrics=oos,
        oos_avg_turnover=best_res.avg_turnover, equal_weight_oos_sharpe=ew_sharpe,
        deflated_sharpe=dsr, pbo=pbo_res.pbo, prob_oos_loss=pbo_res.prob_oos_loss,
        n_trials=len(trials), n_symbols=panel.shape[1],
        split_ts=test_start_ts.to_pydatetime(), test_bars=len(test_ret), trials=trials,
    )
