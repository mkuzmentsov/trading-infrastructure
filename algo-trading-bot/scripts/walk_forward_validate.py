"""Out-of-research validation of the multi-window sleeved candidate (experiment #11).

The formal gate "APPROVED" (#10) relies on the n_trials=1 framing. This harness stress-tests the
candidate with methods that make NO by-hand parameter choices and don't depend on one arbitrary
60/40 split:

  1. FULL-SAMPLE significance — since the windows are pre-committed (no fit), the entire 2014–2026
     history is out-of-sample. Report Sharpe + PSR over all bars.
  2. WALK-FORWARD (no refit) — score the fixed strategy on every sequential OOS block (roadmap §4.5
     harness). Exposes whether the edge holds across regimes or lives in one favorable window.
  3. PER-YEAR breakdown — same question, calendar view.
  4. BLOCK-BOOTSTRAP Sharpe CI — an honest confidence interval, not a point (roadmap §5b).

Usage:  PYTHONPATH=src python3 scripts/walk_forward_validate.py [--config configs/tstrend_multiwindow.toml]
"""

from __future__ import annotations

import argparse
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


def _sharpe(r, ppy):
    r = np.asarray(r, float)
    return float(r.mean() / r.std(ddof=1) * np.sqrt(ppy)) if r.size > 1 and r.std(ddof=1) > 0 else 0.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="configs/tstrend_multiwindow.toml")
    args = ap.parse_args()

    cfg = BotConfig(**tomllib.load(open(args.config, "rb")))
    ppy = PERIODS_PER_YEAR[cfg.bar_interval]
    store = PointInTimeStore(cfg.data_dir)
    panel = store.close_panel([Symbol(s) for s in cfg.universe],
                              datetime(2007, 1, 1, tzinfo=timezone.utc),
                              datetime.now(timezone.utc), cfg.bar_interval, venue=cfg.data_venue)

    res = run_sleeved_ts_trend_backtest(
        panel, sleeves={k: list(v) for k, v in cfg.tstrend.sleeves.items()},
        windows=[tuple(w) for w in cfg.tstrend.windows], vol_window=cfg.trend.vol_window,
        scale=cfg.trend.scale, target_vol=cfg.risk.target_annual_vol,
        leverage=cfg.risk.max_gross_leverage, fee_bps=cfg.friction.taker_fee_bps,
        periods_per_year=ppy, cov_window=cfg.tstrend.cov_window, shrinkage=cfg.tstrend.shrinkage,
        vol_overlay_window=cfg.tstrend.vol_overlay_window)
    ret = res.returns

    print(f"=== Walk-forward validation: {cfg.name} ===")
    print(f"panel {panel.shape[1]} syms, {len(ret)} bars  {ret.index[0].date()} → {ret.index[-1].date()}  "
          f"(windows {cfg.tstrend.windows}, vol-overlay {cfg.tstrend.vol_overlay_window}d)")

    # 1) full-sample significance (whole history is OOS — nothing was fit)
    r = ret.to_numpy()
    perbar = r.mean() / r.std(ddof=1)
    psr_full = deflated_sharpe_ratio(perbar, len(r), M.skew(r), M.kurtosis(r) + 3.0, 1, 0.0)
    print(f"\n[1] FULL SAMPLE (all bars OOS, no fit):  Sharpe={_sharpe(r, ppy):.2f}  PSR={psr_full:.3f}")

    # 2) walk-forward (no refit): score the fixed strategy on each sequential OOS block
    wf = WalkForward(WalkForwardConfig(train_window=timedelta(days=365 * 3),
                                       test_window=timedelta(days=182), retrain_every=timedelta(days=182)))
    blocks = wf.run(ret, fit_fn=lambda s, e: None,
                    eval_fn=lambda _, ts, te: ret[(ret.index >= ts) & (ret.index < te)])
    block_sh = [(_sharpe(b.result, ppy), b.test_start.date(), b.test_end.date())
                for b in blocks if len(b.result) > 20]
    sh = np.array([s for s, *_ in block_sh])
    print(f"\n[2] WALK-FORWARD (no refit, 6-mo OOS blocks): {len(sh)} blocks")
    print(f"    Sharpe median={np.median(sh):+.2f}  mean={sh.mean():+.2f}  "
          f"min={sh.min():+.2f}  max={sh.max():+.2f}  %positive={100*(sh > 0).mean():.0f}%")
    worst = min(block_sh)[0:3]
    print(f"    worst block: Sharpe {worst[0]:+.2f}  ({worst[1]} → {worst[2]})")

    # 3) per-calendar-year Sharpe
    print("\n[3] PER-YEAR Sharpe:")
    by_year = ret.groupby(ret.index.year)
    cells = [f"{y}:{_sharpe(g.to_numpy(), ppy):+.2f}" for y, g in by_year]
    for i in range(0, len(cells), 6):
        print("    " + "  ".join(cells[i:i + 6]))

    # 4) block-bootstrap Sharpe CI
    bs = block_bootstrap_sharpe(r, ppy, block=21, n_boot=3000, seed=0)
    print(f"\n[4] BLOCK-BOOTSTRAP Sharpe (21-day blocks, 3000 resamples):")
    print(f"    point={bs['sharpe']:.2f}  90% CI [{bs['ci_low']:.2f}, {bs['ci_high']:.2f}]  "
          f"P(Sharpe>0)={bs['p_positive']:.3f}")

    print(f"\nmaxDD (full)={res.metrics.max_drawdown:.1%}")
    print("\nhonest read: full-sample PSR + bootstrap CI + per-block/year stability assess whether the")
    print("edge survives WITHOUT the single-split or n_trials=1 framing. The −25% bear DD remains.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
