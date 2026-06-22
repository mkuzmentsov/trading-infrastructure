"""Forward paper-trade driver for the sleeved multi-window TSM (the validated candidate).

Two modes:
  replay  — step the paper book over stored history and check it tracks the vectorized backtest
            (backtest == paper, NFR1). A confidence test before going forward.
  step    — advance ONE bar forward: compute today's target from the latest stored panel, rebalance
            the persisted paper book, append a JSONL audit line. Designed for a daily cron (after a
            data refresh via build_mixed_universe.py).

Usage:
  PYTHONPATH=src python3 scripts/paper_trade_panel.py replay --config configs/tstrend_multiwindow.toml
  PYTHONPATH=src python3 scripts/paper_trade_panel.py step   --config configs/tstrend_multiwindow.toml --state-dir ./state/paper_mwt
"""

from __future__ import annotations

import argparse
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from algo_trading_bot.backtest import metrics as M
from algo_trading_bot.backtest.ts_trend import run_sleeved_ts_trend_backtest, sleeved_target_weights
from algo_trading_bot.config import BotConfig
from algo_trading_bot.core.types import Symbol
from algo_trading_bot.data.bars import PERIODS_PER_YEAR
from algo_trading_bot.data.store import PointInTimeStore
from algo_trading_bot.engine.panel_paper import PanelPaperBook


def _load(args):
    cfg = BotConfig(**tomllib.load(open(args.config, "rb")))
    store = PointInTimeStore(cfg.data_dir)
    panel = store.close_panel([Symbol(s) for s in cfg.universe],
                              datetime(2007, 1, 1, tzinfo=timezone.utc),
                              datetime.now(timezone.utc), cfg.bar_interval, venue=cfg.data_venue)
    return cfg, panel


def _target_weights(cfg, panel):
    return sleeved_target_weights(
        panel, sleeves={k: list(v) for k, v in cfg.tstrend.sleeves.items()},
        windows=[tuple(w) for w in cfg.tstrend.windows], vol_window=cfg.trend.vol_window,
        scale=cfg.trend.scale, target_vol=cfg.risk.target_annual_vol,
        leverage=cfg.risk.max_gross_leverage, periods_per_year=PERIODS_PER_YEAR[cfg.bar_interval],
        cov_window=cfg.tstrend.cov_window, shrinkage=cfg.tstrend.shrinkage,
        vol_overlay_window=cfg.tstrend.vol_overlay_window)


def cmd_replay(args) -> int:
    cfg, panel = _load(args)
    target = _target_weights(cfg, panel)
    active = target.index[target.abs().sum(axis=1) > 0]
    start = active[0]
    book = PanelPaperBook.new(cfg.starting_cash, cfg.friction.taker_fee_bps)
    eq_curve = {}
    for ts in panel.index[panel.index >= start]:
        prices = {s: float(p) for s, p in panel.loc[ts].items() if pd.notna(p) and p > 0}
        tw = {s: float(w) for s, w in target.loc[ts].items() if pd.notna(w)}
        rec = book.rebalance_to(tw, prices, ts.isoformat())
        eq_curve[ts] = rec["equity"]
    paper_eq = pd.Series(eq_curve)

    ppy = PERIODS_PER_YEAR[cfg.bar_interval]
    bt = run_sleeved_ts_trend_backtest(
        panel, sleeves={k: list(v) for k, v in cfg.tstrend.sleeves.items()},
        windows=[tuple(w) for w in cfg.tstrend.windows], vol_window=cfg.trend.vol_window,
        scale=cfg.trend.scale, target_vol=cfg.risk.target_annual_vol,
        leverage=cfg.risk.max_gross_leverage, fee_bps=cfg.friction.taker_fee_bps, periods_per_year=ppy,
        cov_window=cfg.tstrend.cov_window, shrinkage=cfg.tstrend.shrinkage,
        vol_overlay_window=cfg.tstrend.vol_overlay_window, starting_cash=cfg.starting_cash)

    paper_ret = paper_eq.pct_change().dropna().to_numpy()
    print(f"=== paper REPLAY vs vectorized backtest ({cfg.name}) ===")
    print(f"bars {len(paper_eq)}  {paper_eq.index[0].date()} → {paper_eq.index[-1].date()}")
    print(f"paper:     end ${paper_eq.iloc[-1]:,.0f}  Sharpe={M.sharpe(paper_ret, ppy):.2f}")
    print(f"backtest:  end ${bt.equity.iloc[-1]:,.0f}  Sharpe={bt.metrics.sharpe:.2f}")
    rel = abs(paper_eq.iloc[-1] - bt.equity.iloc[-1]) / bt.equity.iloc[-1]
    print(f"final-equity relative diff: {rel:.2%}  ({'OK — paper tracks backtest' if rel < 0.05 else 'DIVERGENCE'})")
    return 0


def cmd_step(args) -> int:
    cfg, panel = _load(args)
    target = _target_weights(cfg, panel)
    ts = panel.index[-1]
    prices = {s: float(p) for s, p in panel.loc[ts].items() if pd.notna(p) and p > 0}
    tw = {s: float(w) for s, w in target.loc[ts].items() if pd.notna(w)}

    state_dir = Path(args.state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    state_path = state_dir / "book.json"
    audit_path = state_dir / "audit.jsonl"
    book = PanelPaperBook.load(str(state_path)) if state_path.exists() \
        else PanelPaperBook.new(cfg.starting_cash, cfg.friction.taker_fee_bps)

    if book.last_ts == ts.isoformat():
        print(f"already stepped through {ts.date()} — nothing to do (idempotent)."); return 0

    rec = book.rebalance_to(tw, prices, ts.isoformat())
    book.save(str(state_path))
    with audit_path.open("a") as f:
        f.write(__import__("json").dumps(rec) + "\n")
    longs = sorted([(s, w) for s, w in tw.items() if w > 0.001], key=lambda x: -x[1])[:5]
    shorts = sorted([(s, w) for s, w in tw.items() if w < -0.001], key=lambda x: x[1])[:5]
    print(f"=== paper STEP {ts.date()} ({cfg.name}) ===")
    print(f"equity ${rec['equity']:,.2f}  gross_lev {rec['gross_lev']}  turnover {rec['turnover']}  "
          f"fees ${rec['fees']}  trades {rec['n_trades']}")
    print(f"top longs:  " + ", ".join(f"{s} {w:+.2f}" for s, w in longs))
    print(f"top shorts: " + ", ".join(f"{s} {w:+.2f}" for s, w in shorts))
    print(f"state -> {state_path}  audit -> {audit_path}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("replay", "step"):
        p = sub.add_parser(name)
        p.add_argument("--config", default="configs/tstrend_multiwindow.toml")
        p.add_argument("--state-dir", default="./state/paper_mwt")
    args = ap.parse_args()
    return cmd_replay(args) if args.cmd == "replay" else cmd_step(args)


if __name__ == "__main__":
    sys.exit(main())
