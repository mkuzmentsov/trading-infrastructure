"""Experiment #13 — leverage / vol-target FRONTIER for the multi-window sleeved candidate.

The candidate (`tstrend_multiwindow.toml`) has a validated edge (~Sharpe 0.85-0.9 OOS). The only
honest way to turn that into bigger *dollars* is to scale it via the two risk dials — NOT to invent
more edge. This sweep maps what each leverage setting actually buys:

    target_annual_vol  ×  max_gross_leverage (the hard gross cap)

For every (target_vol, cap) cell, on the full 2014-26 panel (every bar OOS — nothing is fit), report:
  - Sharpe                : ~flat across the grid IF leverage only scales the book (the honest test)
  - CAGR (compounded)     : the dollar-growth number
  - realized gross lev    : mean |w| actually carried (the cap often doesn't bind)
  - maxDD (full sample)   : the realized worst peak-to-trough over 12y
  - annual ruin stats     : block-bootstrapped P[a 1-yr path draws down past -50% / -80% / -100%],
                            plus the 5th-percentile annual drawdown (the "bad year" you must survive)

Decision rule (written in EXPERIMENTS.md #13): pick the leverage whose bootstrap bad-year DD matches
the user's stated drawdown tolerance — NOT the highest-CAGR cell. Higher leverage scales CAGR and DD
together until volatility drag + ruin make compounded wealth fall even as gross rises.

Usage:  PYTHONPATH=src python3 scripts/leverage_frontier.py [--config configs/tstrend_multiwindow.toml]
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

# The frontier grid (a-priori, NOT searched — this characterizes, it doesn't tune).
TARGET_VOLS = [0.15, 0.20, 0.30, 0.40, 0.60]
GROSS_CAPS = [2.0, 3.0, 4.0, 6.0]


def _sharpe(r, ppy):
    r = np.asarray(r, float)
    return float(r.mean() / r.std(ddof=1) * np.sqrt(ppy)) if r.size > 1 and r.std(ddof=1) > 0 else 0.0


def _cagr(equity):
    eq = np.asarray(equity, float)
    if eq[0] <= 0 or eq[-1] <= 0:
        return float("nan")
    # equity index already spans the full panel; annualize on calendar years
    return float((eq[-1] / eq[0]) ** (1.0 / _years) - 1.0)


def ruin_stats(r, ppy, *, horizon_years=1.0, block=21, n_boot=8000, seed=0,
               thresholds=(0.50, 0.80, 1.0)):
    """Block-bootstrap 1-year equity paths and measure their drawdown distribution.

    A path that hits a per-bar return <= -100% is liquidated (treated as full ruin). Otherwise we
    take the path's worst peak-to-trough. Returns P[maxDD breach] per threshold + the 5th-pct DD.
    """
    r = np.asarray(r, float)
    rng = np.random.default_rng(seed)
    horizon = int(ppy * horizon_years)
    n_blocks = int(np.ceil(horizon / block))
    max_start = len(r) - block
    if max_start <= 0:
        return {t: float("nan") for t in thresholds}, float("nan")
    worst = np.empty(n_boot)
    for i in range(n_boot):
        starts = rng.integers(0, max_start + 1, n_blocks)
        path = np.concatenate([r[s:s + block] for s in starts])[:horizon]
        growth = 1.0 + path
        if (growth <= 0).any():                       # a bar wiped the account → ruin
            worst[i] = -1.0
            continue
        eq = np.cumprod(growth)
        dd = (eq / np.maximum.accumulate(eq) - 1.0).min()
        worst[i] = dd
    probs = {t: float((worst <= -t).mean()) for t in thresholds}
    p5 = float(np.percentile(worst, 5))               # 5th-pct annual DD = a realistic bad year
    return probs, p5


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="configs/tstrend_multiwindow.toml")
    ap.add_argument("--n-boot", type=int, default=8000)
    args = ap.parse_args()

    cfg = BotConfig(**tomllib.load(open(args.config, "rb")))
    ppy = PERIODS_PER_YEAR[cfg.bar_interval]
    store = PointInTimeStore(cfg.data_dir)
    panel = store.close_panel([Symbol(s) for s in cfg.universe],
                              datetime(2007, 1, 1, tzinfo=timezone.utc),
                              datetime.now(timezone.utc), cfg.bar_interval, venue=cfg.data_venue)

    global _years
    span_days = (panel.index[-1] - panel.index[0]).days
    _years = span_days / 365.25

    base_tv, base_lev = cfg.risk.target_annual_vol, cfg.risk.max_gross_leverage
    print(f"=== Leverage / vol-target frontier: {cfg.name} ===")
    print(f"panel {panel.shape[1]} syms  {panel.index[0].date()} → {panel.index[-1].date()}  "
          f"({_years:.1f}y, {len(panel)} bars)   baseline cell = tv {base_tv:.2f} / cap {base_lev:.0f}×")
    print(f"windows {cfg.tstrend.windows}  vol-overlay {cfg.tstrend.vol_overlay_window}d  "
          f"fee {cfg.friction.taker_fee_bps}bps\n")

    def run(tv, lev):
        return run_sleeved_ts_trend_backtest(
            panel, sleeves={k: list(v) for k, v in cfg.tstrend.sleeves.items()},
            windows=[tuple(w) for w in cfg.tstrend.windows], vol_window=cfg.trend.vol_window,
            scale=cfg.trend.scale, target_vol=tv, leverage=lev,
            fee_bps=cfg.friction.taker_fee_bps, periods_per_year=ppy,
            cov_window=cfg.tstrend.cov_window, shrinkage=cfg.tstrend.shrinkage,
            vol_overlay_window=cfg.tstrend.vol_overlay_window)

    hdr = (f"{'tgtVol':>6} {'cap':>4} {'Sharpe':>7} {'CAGR':>8} {'realLev':>7} "
           f"{'maxDD':>7} {'badYrDD':>7} {'P<-50%':>7} {'P<-80%':>7} {'P_ruin':>7}")
    print(hdr)
    print("-" * len(hdr))
    rows = []
    for tv in TARGET_VOLS:
        for lev in GROSS_CAPS:
            res = run(tv, lev)
            r = res.returns.to_numpy()
            probs, p5 = ruin_stats(r, ppy, n_boot=args.n_boot)
            mark = "  <- baseline" if (abs(tv - base_tv) < 1e-9 and abs(lev - base_lev) < 1e-9) else ""
            row = dict(tv=tv, lev=lev, sharpe=_sharpe(r, ppy), cagr=_cagr(res.equity.to_numpy()),
                       reallev=res.gross_exposure, maxdd=res.metrics.max_drawdown,
                       badyr=p5, p50=probs[0.50], p80=probs[0.80], pruin=probs[1.0])
            rows.append(row)
            print(f"{tv:>6.2f} {lev:>3.0f}× {row['sharpe']:>7.2f} {row['cagr']:>7.1%} "
                  f"{row['reallev']:>6.2f}× {row['maxdd']:>7.1%} {p5:>7.1%} "
                  f"{probs[0.50]:>7.1%} {probs[0.80]:>7.1%} {probs[1.0]:>7.1%}{mark}")
        print()

    print("read: 'realLev' = mean gross actually carried (cap binds only when realLev≈cap). 'badYrDD' = 5th-pct")
    print("bootstrapped 1-year drawdown (the bad year you must survive). 'P_ruin' = P[a 1-yr path is liquidated].")
    print("If Sharpe is ~flat down a column, leverage is only SCALING the edge — exactly as expected; choose the")
    print("row whose badYrDD you can stomach, not the highest CAGR (volatility drag + ruin punish the top rows).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
