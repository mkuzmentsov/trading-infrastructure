"""Profit-skim vs compounding on the daily core book — the income-vs-growth tradeoff, quantified.

User's idea: at EOD, withdraw the balance above the starting base (1000→1100 → bank 100). This caps the
trading account, so it stops compounding. Question: how much growth do you give up, and how much
drawdown safety do you buy? Run it on the validated aggressive daily book (`tstrend_multiwindow_aggr`,
0.40/6x) over the full 2014-26 history.

Policies (B = starting base; same return stream, only the capital base differs — returns are scale-free):
  compound        — never withdraw (geometric growth, the wealth engine)
  skim-100%       — at EOD bank ALL of (equity − B), reset trading to B (fixed-size + dividend)
  skim-50%        — at EOD bank HALF of (equity − B) (partial compounding)
Each tracks trading_equity (at risk) + banked (withdrawn, drawdown-PROOF). Total wealth = trading + banked.
Banked is only ADDED to on up-overflows; drawdowns never claw it back.

Usage:  PYTHONPATH=src python3 scripts/profit_skim.py [--config configs/tstrend_multiwindow_aggr.toml]
"""

from __future__ import annotations

import argparse
import sys
import tomllib
from datetime import datetime, timezone

import numpy as np

from algo_trading_bot.backtest.ts_trend import run_sleeved_ts_trend_backtest
from algo_trading_bot.config import BotConfig
from algo_trading_bot.core.types import Symbol
from algo_trading_bot.data.bars import PERIODS_PER_YEAR
from algo_trading_bot.data.store import PointInTimeStore

BASE = 1000.0


def simulate(rets: np.ndarray, skim_frac: float, ppy: float, years: float) -> dict:
    """Apply daily returns to a floating trading account; at each EOD bank skim_frac of any excess
    above BASE. Returns total-wealth stats. skim_frac=0 → pure compounding."""
    trading = BASE
    banked = 0.0
    total_curve = np.empty(len(rets))
    trading_curve = np.empty(len(rets))
    for i, r in enumerate(rets):
        trading *= (1.0 + r)
        if skim_frac > 0 and trading > BASE:
            take = skim_frac * (trading - BASE)
            banked += take
            trading -= take
        total_curve[i] = trading + banked
        trading_curve[i] = trading
    total = trading + banked
    def maxdd(curve):
        return float((curve / np.maximum.accumulate(curve) - 1.0).min())
    return {
        "terminal_mult": total / BASE,
        "cagr_total": (total / BASE) ** (1.0 / years) - 1.0,
        "banked_mult": banked / BASE,
        "trading_end_mult": trading / BASE,
        "maxdd_total": maxdd(total_curve),       # what a withdrawal-aware investor actually feels
        "maxdd_trading": maxdd(trading_curve),   # the at-risk account's drawdown (same shape across policies)
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="configs/tstrend_multiwindow_aggr.toml")
    args = ap.parse_args()
    cfg = BotConfig(**tomllib.load(open(args.config, "rb")))
    ppy = PERIODS_PER_YEAR[cfg.bar_interval]
    store = PointInTimeStore(cfg.data_dir)
    panel = store.close_panel([Symbol(s) for s in cfg.universe],
                              datetime(2007, 1, 1, tzinfo=timezone.utc),
                              datetime.now(timezone.utc), cfg.bar_interval, venue=cfg.data_venue)
    years = (panel.index[-1] - panel.index[0]).days / 365.25
    res = run_sleeved_ts_trend_backtest(
        panel, sleeves={k: list(v) for k, v in cfg.tstrend.sleeves.items()},
        windows=[tuple(w) for w in cfg.tstrend.windows], vol_window=cfg.trend.vol_window,
        scale=cfg.trend.scale, target_vol=cfg.risk.target_annual_vol, leverage=cfg.risk.max_gross_leverage,
        fee_bps=cfg.friction.taker_fee_bps, periods_per_year=ppy, cov_window=cfg.tstrend.cov_window,
        shrinkage=cfg.tstrend.shrinkage, vol_overlay_window=cfg.tstrend.vol_overlay_window)
    rets = res.returns.to_numpy()

    print(f"=== Profit-skim vs compounding: {cfg.name} (0.40/6x daily book) ===")
    print(f"{len(rets)} daily bars, {years:.1f}y, base ${BASE:,.0f}\n")
    hdr = (f"{'policy':>12} {'total wealth':>13} {'CAGR(total)':>12} {'banked(safe)':>13} "
           f"{'at-risk end':>12} {'maxDD(total)':>13}")
    print(hdr); print("-" * len(hdr))
    for name, f in [("compound", 0.0), ("skim-50%", 0.5), ("skim-100%", 1.0)]:
        s = simulate(rets, f, ppy, years)
        print(f"{name:>12} {s['terminal_mult']:>11.1f}x {s['cagr_total']:>11.1%} "
              f"{s['banked_mult']:>11.1f}x {s['trading_end_mult']:>10.2f}x {s['maxdd_total']:>12.1%}")
    print(f"\n(at-risk account maxDD is the same shape for all policies: "
          f"{simulate(rets,0.0,ppy,years)['maxdd_trading']:.1%} — the strategy is identical; only the")
    print("capital base differs.) read: 'compound' wins terminal wealth massively (geometric growth), but its")
    print("TOTAL-wealth drawdown is the full strategy DD. Skim policies bank a drawdown-PROOF pile at the cost")
    print("of far lower terminal wealth — income & safety vs growth. CAGR here is full-sample-optimistic;")
    print("temper forward ~0.6-0.7x (per #11). The RANKING (compound >> skim on growth) is the durable point.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
