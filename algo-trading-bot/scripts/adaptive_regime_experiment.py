"""Experiments #22 + #23 — does 'adjust the math to the current regime, online' beat the static book?

Two adaptive mechanisms, each compared against the SAME static multiwindow candidate, on the same
12-year walk-forward (every bar OOS, nothing fit). Verdict by the project's gold-standard metrics:
full-sample Sharpe + PSR, walk-forward %-positive / worst block, block-bootstrap Sharpe CI, maxDD.

  #22 TREND-QUALITY GATE (a-priori): scale each asset's forecast by its Kaufman efficiency-ratio weight
      (chop → downweight), reusing the EXACT engine soft gate that lifted btc_1d OOS 0.62→0.78 (#2):
      ER window 20, thresholds 0.15/0.45. Pre-committed, no search. Built into `sleeved_target_weights`
      behind `er_window`.

  #23 ADAPTIVE KELLY LEVERAGE (online): scale the whole book each bar by a multiplier derived from its
      OWN trailing realized Sharpe — lever up when it's working, down when not. A causal return-series
      overlay (same method as the #15 DD-throttle). A-priori params: trailing window 126d, target Sharpe
      1.0, multiplier clipped [0, 2] (so realized leverage swings around the static base, never beyond
      2× it). This is the literal "adjust while running" — and the one the project's history (#2 hysteresis,
      #15 throttle) predicts will overfit/lag.

Usage:  PYTHONPATH=src python3 scripts/adaptive_regime_experiment.py
"""

from __future__ import annotations

import sys
import tomllib
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from algo_trading_bot.backtest import metrics as M
from algo_trading_bot.backtest.ts_trend import run_sleeved_ts_trend_backtest
from algo_trading_bot.config import BotConfig
from algo_trading_bot.core.types import Symbol
from algo_trading_bot.data.bars import PERIODS_PER_YEAR
from algo_trading_bot.data.store import PointInTimeStore
from algo_trading_bot.validation.deflated_sharpe import deflated_sharpe_ratio
from algo_trading_bot.validation.stats import block_bootstrap_sharpe
from algo_trading_bot.validation.walk_forward import WalkForward, WalkForwardConfig

# #23 adaptive-leverage params (a-priori, not searched)
ADAPT_WINDOW = 126
ADAPT_TARGET_SHARPE = 1.0
ADAPT_CLIP = (0.0, 2.0)


def _sharpe(r, ppy):
    r = np.asarray(r, float)
    return float(r.mean() / r.std(ddof=1) * np.sqrt(ppy)) if r.size > 1 and r.std(ddof=1) > 0 else 0.0


def adaptive_leverage_overlay(ret: pd.Series, ppy: float) -> pd.Series:
    """Scale each bar by a causal multiplier from the book's trailing realized Sharpe (#23)."""
    mu = ret.rolling(ADAPT_WINDOW).mean()
    sd = ret.rolling(ADAPT_WINDOW).std(ddof=1)
    tr_sharpe = (mu / sd.replace(0.0, np.nan) * np.sqrt(ppy)).fillna(0.0)
    mult = (tr_sharpe / ADAPT_TARGET_SHARPE).clip(*ADAPT_CLIP)
    return ret * mult.shift(1).fillna(1.0)                      # decided at t-1, applied to bar t


def metrics(ret: pd.Series, ppy: float) -> dict:
    r = ret.to_numpy()
    perbar = r.mean() / r.std(ddof=1)
    psr = deflated_sharpe_ratio(perbar, len(r), M.skew(r), M.kurtosis(r) + 3.0, 1, 0.0)
    wf = WalkForward(WalkForwardConfig(train_window=timedelta(days=365 * 3),
                                       test_window=timedelta(days=182), retrain_every=timedelta(days=182)))
    blocks = wf.run(ret, fit_fn=lambda s, e: None,
                    eval_fn=lambda _, ts, te: ret[(ret.index >= ts) & (ret.index < te)])
    sh = np.array([_sharpe(b.result, ppy) for b in blocks if len(b.result) > 20])
    bs = block_bootstrap_sharpe(r, ppy, block=21, n_boot=3000, seed=0)
    eq = (1.0 + ret).cumprod().to_numpy()
    mdd, _ = M.max_drawdown(eq)
    return {"sharpe": _sharpe(r, ppy), "psr": psr, "wf_med": float(np.median(sh)),
            "wf_pos": float(100 * (sh > 0).mean()), "wf_worst": float(sh.min()),
            "ci_lo": bs["ci_low"], "ci_hi": bs["ci_high"], "maxdd": mdd}


def main() -> int:
    cfg = BotConfig(**tomllib.load(open("configs/tstrend_multiwindow.toml", "rb")))
    ppy = PERIODS_PER_YEAR[cfg.bar_interval]
    store = PointInTimeStore(cfg.data_dir)
    panel = store.close_panel([Symbol(s) for s in cfg.universe],
                              datetime(2007, 1, 1, tzinfo=timezone.utc),
                              datetime.now(timezone.utc), cfg.bar_interval, venue=cfg.data_venue)

    def run(er_window=0):
        return run_sleeved_ts_trend_backtest(
            panel, sleeves={k: list(v) for k, v in cfg.tstrend.sleeves.items()},
            windows=[tuple(w) for w in cfg.tstrend.windows], vol_window=cfg.trend.vol_window,
            scale=cfg.trend.scale, target_vol=cfg.risk.target_annual_vol,
            leverage=cfg.risk.max_gross_leverage, fee_bps=cfg.friction.taker_fee_bps,
            periods_per_year=ppy, cov_window=cfg.tstrend.cov_window, shrinkage=cfg.tstrend.shrinkage,
            vol_overlay_window=cfg.tstrend.vol_overlay_window, er_window=er_window).returns

    base = run(er_window=0)
    variants = {
        "baseline (static)":      metrics(base, ppy),
        "#22 trend-quality gate": metrics(run(er_window=20), ppy),
        "#23 adaptive leverage":  metrics(adaptive_leverage_overlay(base, ppy), ppy),
    }

    print(f"=== Adaptive-regime experiments vs static candidate ({len(panel)} bars, all OOS) ===\n")
    hdr = (f"{'variant':>24} {'Sharpe':>7} {'PSR':>6} {'WF med':>7} {'WF %+':>6} {'WF worst':>9} "
           f"{'boot CI':>15} {'maxDD':>7}")
    print(hdr); print("-" * len(hdr))
    for name, m in variants.items():
        print(f"{name:>24} {m['sharpe']:>7.2f} {m['psr']:>6.3f} {m['wf_med']:>+7.2f} {m['wf_pos']:>5.0f}% "
              f"{m['wf_worst']:>+9.2f} {'['+format(m['ci_lo'],'.2f')+', '+format(m['ci_hi'],'.2f')+']':>15} "
              f"{m['maxdd']:>7.1%}")
    print("\nread: a regime adaptation EARNS its keep only if it lifts WF %-positive / worst-block / CI-lower")
    print("WITHOUT cutting full-sample Sharpe — i.e. it must help the chop years (2023, the −1.05 block) on net.")
    print("Per the project's history (#2 hysteresis, #15 throttle), expect adaptive leverage to lag; the")
    print("a-priori ER gate is the one with prior OOS evidence.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
