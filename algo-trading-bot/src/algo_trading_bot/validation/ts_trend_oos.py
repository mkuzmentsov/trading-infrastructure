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

import itertools

from ..backtest import metrics as M
from ..backtest.ts_trend import run_sleeved_ts_trend_backtest, run_ts_trend_backtest
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
    sleeve_params: dict = field(default_factory=dict)  # {sleeve -> (fast,slow)} when sleeved


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

    ts = config.tstrend

    def run(fast, slow):
        return run_ts_trend_backtest(
            panel, fast=fast, slow=slow, vol_window=tr.vol_window, scale=tr.scale,
            target_vol=risk.target_annual_vol, leverage=risk.max_gross_leverage,
            fee_bps=fee_bps, rebalance=config.xsec.rebalance, periods_per_year=ppy,
            starting_cash=config.starting_cash,
            sizing=ts.sizing, cov_window=ts.cov_window, shrinkage=ts.shrinkage,
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


def run_sleeved_ts_trend_validation(
    config: BotConfig, start: datetime, end: datetime, *, train_frac: float = 0.6
) -> TSTrendOOSResult:
    """Sleeved managed-futures validation (experiment #5 promoted): select each sleeve's trend
    window, run the cluster-sized combined book, report OOS + Deflated Sharpe + PBO.

    Window selection is JOINT over the per-sleeve (fast,slow) grids when the product is small
    (<= ``max_joint_trials``), else INDEPENDENT per sleeve (each chosen on its own sub-book train
    Sharpe — fewer trials, lower overfitting). DSR/PBO are computed over the realized trial set.
    """
    from ..engine.backtest import Backtester

    ppy = PERIODS_PER_YEAR[config.bar_interval]
    tr, risk, ts = config.trend, config.risk, config.tstrend
    fee_bps = config.friction.taker_fee_bps
    sleeves = {name: [s for s in syms] for name, syms in ts.sleeves.items()}

    store = Backtester(config).store
    panel = store.close_panel([Symbol(s) for s in config.universe], start, end,
                              config.bar_interval, venue=config.data_venue)
    if panel.shape[1] < 4 or len(panel) < 200:
        raise RuntimeError(f"need >=4 symbols and >=200 bars; got {panel.shape}.")

    n = len(panel)
    split_i = int(n * train_frac)
    train_end_ts = panel.index[split_i]
    test_start_ts = panel.index[min(split_i + int(n * config.validation.embargo_pct), n - 1)]

    def book(params: dict):
        return run_sleeved_ts_trend_backtest(
            panel, sleeves=sleeves, sleeve_params=params, vol_window=tr.vol_window, scale=tr.scale,
            target_vol=risk.target_annual_vol, leverage=risk.max_gross_leverage, fee_bps=fee_bps,
            periods_per_year=ppy, cov_window=ts.cov_window, shrinkage=ts.shrinkage,
            starting_cash=config.starting_cash)

    names = list(sleeves)
    joint_size = len(_GRID) ** len(names)

    # candidate window-combos to evaluate
    if joint_size <= ts.max_joint_trials:
        combos = [dict(zip(names, combo)) for combo in itertools.product(_GRID, repeat=len(names))]
    else:
        # Independent: pick each sleeve's best (others at grid[0]), then build the trial set as a
        # local-sensitivity sweep — vary each sleeve over the grid with the OTHERS at their selected
        # best. O(K·|grid|) trials (not |grid|^K) yet still a real distribution for DSR/PBO.
        per = {}
        for name in names:
            best_w, best_s = _GRID[0], -1e9
            for w in _GRID:
                r = book({name: w, **{o: _GRID[0] for o in names if o != name}}).returns
                s = M.sharpe(r[r.index < train_end_ts].to_numpy(), ppy)
                if s > best_s:
                    best_s, best_w = s, w
            per[name] = best_w
        seen, combos = set(), []
        for name in names:
            for w in _GRID:
                params = {**per, name: w}
                key = tuple(params[n] for n in names)
                if key not in seen:
                    seen.add(key)
                    combos.append(params)

    trials, returns_by_trial = [], {}
    for params in combos:
        res = book(params)
        key = "|".join(f"{n}:{params[n][0]}/{params[n][1]}" for n in names)
        returns_by_trial[key] = res.returns
        tr_ret = res.returns[res.returns.index < train_end_ts].to_numpy()
        trials.append({"params": params, "key": key, "train_sharpe": M.sharpe(tr_ret, ppy),
                       "train_perbar": _perbar_sharpe(tr_ret)})
    best = max(trials, key=lambda t: t["train_sharpe"])

    best_res = book(best["params"])
    test_ret = best_res.returns[best_res.returns.index >= test_start_ts]
    test_eq = best_res.equity[best_res.equity.index >= test_start_ts]
    oos = M.compute(test_eq.to_numpy(), test_ret.to_numpy(), np.array([]),
                    periods_per_year=ppy, turnover=best_res.avg_turnover)

    ew = panel.pct_change().mean(axis=1)
    ew_sharpe = M.sharpe(ew[ew.index >= test_start_ts].to_numpy(), ppy)

    tr_test = test_ret.to_numpy()
    obs = _perbar_sharpe(tr_test)
    var_sharpe = float(np.var([t["train_perbar"] for t in trials], ddof=1)) if len(trials) > 1 else 0.0
    dsr = (deflated_sharpe_ratio(obs, len(tr_test), M.skew(tr_test), M.kurtosis(tr_test) + 3.0,
                                 len(trials), var_sharpe) if obs and var_sharpe > 0 else 0.0)
    pbo_res = cscv_pbo(pd.DataFrame(returns_by_trial).dropna(how="any"), n_blocks=10) \
        if len(returns_by_trial) > 1 else None

    return TSTrendOOSResult(
        best_params={"sleeves": {n: list(best["params"][n]) for n in names}},
        sleeve_params={n: best["params"][n] for n in names},
        train_sharpe=best["train_sharpe"], oos_metrics=oos,
        oos_avg_turnover=best_res.avg_turnover, equal_weight_oos_sharpe=ew_sharpe,
        deflated_sharpe=dsr, pbo=(pbo_res.pbo if pbo_res else 0.0),
        prob_oos_loss=(pbo_res.prob_oos_loss if pbo_res else 0.0),
        n_trials=len(trials), n_symbols=panel.shape[1],
        split_ts=test_start_ts.to_pydatetime(), test_bars=len(test_ret), trials=trials,
    )
