"""Experiment #14 — fractional-Kelly + compounding check for the chosen operating point.

#13 picked an operating point by drawdown tolerance (0.40/6×). #14 asks the *growth-theory* question:
where is the Kelly peak (the leverage that maximizes compounded growth), and is the chosen point on the
safe (sub-Kelly) side? Past full-Kelly, more leverage LOWERS compounded wealth (volatility drag) while
still raising drawdown — the worst place to be. Half-Kelly is the conventional prudent ceiling: ~3/4 of
the growth at ~1/2 the drawdown.

Method (empirical, honest — no closed-form normality assumption):
  - The book already compounds (equity = starting_cash · Π(1+r)). We trace realized annual vol vs CAGR by
    sweeping `target_annual_vol` with a NON-binding gross cap (cap=20×), so target_vol alone sets sizing.
  - CAGR(realized_vol) is the growth curve. Its peak = empirical full-Kelly. Half-Kelly = the realized vol
    at peak / 2. We then mark where the chosen config's realized vol falls on that curve.
  - We also report the analytic Kelly leverage k* = μ/σ² on the per-bar book returns as a cross-check.

Usage:  PYTHONPATH=src python3 scripts/kelly_compounding.py [--config configs/tstrend_multiwindow_aggr.toml]
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

# Wide target-vol ladder to trace the growth curve through and past the Kelly peak.
TARGET_VOLS = [0.10, 0.15, 0.20, 0.30, 0.40, 0.55, 0.70, 0.90, 1.10, 1.40, 1.80]
UNCAPPED = 20.0  # non-binding gross cap so target_vol alone drives sizing


def _ann_vol(r, ppy):
    return float(np.std(r, ddof=1) * np.sqrt(ppy))


def _sharpe(r, ppy):
    r = np.asarray(r, float)
    return float(r.mean() / r.std(ddof=1) * np.sqrt(ppy)) if r.size > 1 and r.std(ddof=1) > 0 else 0.0


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

    def run(tv, lev):
        return run_sleeved_ts_trend_backtest(
            panel, sleeves={k: list(v) for k, v in cfg.tstrend.sleeves.items()},
            windows=[tuple(w) for w in cfg.tstrend.windows], vol_window=cfg.trend.vol_window,
            scale=cfg.trend.scale, target_vol=tv, leverage=lev,
            fee_bps=cfg.friction.taker_fee_bps, periods_per_year=ppy,
            cov_window=cfg.tstrend.cov_window, shrinkage=cfg.tstrend.shrinkage,
            vol_overlay_window=cfg.tstrend.vol_overlay_window)

    def cagr(eq):
        eq = np.asarray(eq, float)
        return float((eq[-1] / eq[0]) ** (1.0 / years) - 1.0) if eq[0] > 0 and eq[-1] > 0 else float("nan")

    print(f"=== Kelly / compounding curve: {cfg.name} ===")
    print(f"panel {panel.shape[1]} syms  {panel.index[0].date()} → {panel.index[-1].date()}  ({years:.1f}y)")
    print(f"chosen config: target_vol {cfg.risk.target_annual_vol:.2f}  cap {cfg.risk.max_gross_leverage:.0f}×\n")

    hdr = f"{'tgtVol':>6} {'realVol':>7} {'realLev':>7} {'Sharpe':>7} {'CAGR':>8} {'maxDD':>7}"
    print(hdr); print("-" * len(hdr))
    curve = []
    for tv in TARGET_VOLS:
        res = run(tv, UNCAPPED)
        r = res.returns.to_numpy()
        rv = _ann_vol(r, ppy)
        c = cagr(res.equity.to_numpy())
        curve.append((tv, rv, res.gross_exposure, _sharpe(r, ppy), c, res.metrics.max_drawdown))
        print(f"{tv:>6.2f} {rv:>6.1%} {res.gross_exposure:>6.2f}× {curve[-1][3]:>7.2f} "
              f"{c:>7.1%} {res.metrics.max_drawdown:>7.1%}")

    # Empirical Kelly peak = the target_vol whose realized growth (CAGR) is highest.
    peak = max(curve, key=lambda x: (x[4] if x[4] == x[4] else -1e9))
    # Analytic cross-check on the chosen config's per-bar returns: k* = mean/var (in 'multiples of current').
    chosen = run(cfg.risk.target_annual_vol, cfg.risk.max_gross_leverage).returns.to_numpy()
    mu, var = chosen.mean(), chosen.var(ddof=1)
    k_star = float(mu / var) if var > 0 else float("nan")     # Kelly multiple of the CHOSEN sizing
    chosen_rv = _ann_vol(chosen, ppy)

    print(f"\nempirical Kelly PEAK (max compounded CAGR):  target_vol {peak[0]:.2f}  →  realized vol "
          f"{peak[1]:.0%}, realized lev {peak[2]:.1f}×, CAGR {peak[4]:.1%}")
    print(f"  full-Kelly ≈ realized vol {peak[1]:.0%}   half-Kelly ≈ {peak[1]/2:.0%}   "
          f"quarter-Kelly ≈ {peak[1]/4:.0%}")
    print(f"chosen config realized vol = {chosen_rv:.0%}  →  that is ~{chosen_rv/peak[1]:.2f}× of full-Kelly "
          f"({'sub-half-Kelly, safe' if chosen_rv <= peak[1]/2 else 'BETWEEN half and full Kelly' if chosen_rv < peak[1] else 'PAST full-Kelly — vol-drag zone, de-lever'})")
    print(f"analytic cross-check: Kelly multiple of the chosen sizing k* = μ/σ² = {k_star:.2f}×  "
          f"(>1 ⇒ chosen sizing is below its own Kelly; growth rises if levered toward k*)")
    print("\nread: past the peak, CAGR FALLS while drawdown keeps rising — strictly worse. Half-Kelly (the prudent")
    print("ceiling) gives ~3/4 the growth at ~1/2 the DD. Confirm the chosen point sits at/below half-Kelly.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
