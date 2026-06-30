"""Experiment #15 — drawdown-throttle overlay: does de-levering on equity drawdown buy back
leverage headroom?

A high-water-mark throttle cuts exposure as the equity curve falls from its peak — a portfolio-level
overlay on top of the chosen sizing (causal: the factor for bar t+1 is set from equity through bar t).
The real question is NOT "does it lower DD at fixed leverage" (trivially yes, by lowering exposure) but
"does it improve the DD-per-CAGR tradeoff enough that I can run HIGHER target-vol for the SAME bad-year
DD and net more growth?" If yes, the throttle raises the safe leverage ceiling.

Throttle: factor = 1 above `start` drawdown, ramps linearly to `floor` by `halt` drawdown.
Approximation: scaling net returns by the factor ≈ scaling positions (fees scale with size too; the
turnover from changing the throttle itself is a small second-order cost, noted).

Bad-year DD is block-bootstrapped on the RAW returns with the throttle applied to each resampled path,
so the tail protection is measured where it matters (the throttle should help most on bad paths).

Usage:  PYTHONPATH=src python3 scripts/dd_throttle.py [--config configs/tstrend_multiwindow_aggr.toml]
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

# Throttle parameterizations to compare (start_dd, halt_dd, floor_exposure).
THROTTLES = {
    "off":          None,
    "gentle 15→40": (0.15, 0.40, 0.25),
    "firm 10→30":   (0.10, 0.30, 0.10),
}
# Headroom test: run these target_vols WITH the firm throttle, compare to off@0.40.
HEADROOM_TVS = [0.40, 0.55, 0.70]


def throttle_path(r, params):
    """Apply a causal HWM drawdown throttle to a per-bar return series. Returns throttled series."""
    if params is None:
        return r
    start, halt, floor = params
    out = np.empty_like(r)
    eq = 1.0
    hwm = 1.0
    factor = 1.0
    for i in range(len(r)):
        out[i] = factor * r[i]                 # factor decided from equity through bar i-1 (causal)
        eq *= (1.0 + out[i])
        hwm = max(hwm, eq)
        dd = 1.0 - eq / hwm if hwm > 0 else 1.0
        if dd <= start:
            factor = 1.0
        elif dd >= halt:
            factor = floor
        else:
            factor = 1.0 - (1.0 - floor) * (dd - start) / (halt - start)
    return out


def _sharpe(r, ppy):
    r = np.asarray(r, float)
    return float(r.mean() / r.std(ddof=1) * np.sqrt(ppy)) if r.size > 1 and r.std(ddof=1) > 0 else 0.0


def _cagr(r, ppy, years):
    eq = np.cumprod(1.0 + np.asarray(r, float))
    return float(eq[-1] ** (1.0 / years) - 1.0) if eq[-1] > 0 else float("nan")


def _maxdd(r):
    eq = np.cumprod(1.0 + np.asarray(r, float))
    return float((eq / np.maximum.accumulate(eq) - 1.0).min())


def bad_year_dd(r_raw, params, ppy, *, block=21, n_boot=8000, seed=0):
    """5th-pct 1-year drawdown: bootstrap RAW blocks, apply throttle to each path, take worst DD."""
    r_raw = np.asarray(r_raw, float)
    rng = np.random.default_rng(seed)
    horizon = int(ppy)
    n_blocks = int(np.ceil(horizon / block))
    max_start = len(r_raw) - block
    worst = np.empty(n_boot)
    for i in range(n_boot):
        starts = rng.integers(0, max_start + 1, n_blocks)
        path = np.concatenate([r_raw[s:s + block] for s in starts])[:horizon]
        path = throttle_path(path, params)
        growth = 1.0 + path
        if (growth <= 0).any():
            worst[i] = -1.0
            continue
        eq = np.cumprod(growth)
        worst[i] = (eq / np.maximum.accumulate(eq) - 1.0).min()
    return float(np.percentile(worst, 5)), float((worst <= -0.80).mean())


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

    def raw_returns(tv, lev):
        res = run_sleeved_ts_trend_backtest(
            panel, sleeves={k: list(v) for k, v in cfg.tstrend.sleeves.items()},
            windows=[tuple(w) for w in cfg.tstrend.windows], vol_window=cfg.trend.vol_window,
            scale=cfg.trend.scale, target_vol=tv, leverage=lev,
            fee_bps=cfg.friction.taker_fee_bps, periods_per_year=ppy,
            cov_window=cfg.tstrend.cov_window, shrinkage=cfg.tstrend.shrinkage,
            vol_overlay_window=cfg.tstrend.vol_overlay_window)
        return res.returns.to_numpy()

    tv0, lev0 = cfg.risk.target_annual_vol, cfg.risk.max_gross_leverage
    print(f"=== Drawdown-throttle overlay: {cfg.name} ===")
    print(f"panel {panel.shape[1]} syms ({years:.1f}y)   chosen sizing tv {tv0:.2f} / cap {lev0:.0f}×\n")

    # Part A — throttle ON vs OFF at the SAME chosen sizing (does it help the tradeoff?)
    base = raw_returns(tv0, lev0)
    print("A) throttle variants at the fixed chosen sizing (tv 0.40 / 6×):")
    hdr = f"   {'throttle':>14} {'Sharpe':>7} {'CAGR':>8} {'maxDD':>7} {'badYrDD':>8} {'P<-80%':>7}"
    print(hdr); print("   " + "-" * (len(hdr) - 3))
    for name, params in THROTTLES.items():
        thr = throttle_path(base, params)
        p5, p80 = bad_year_dd(base, params, ppy)
        print(f"   {name:>14} {_sharpe(thr, ppy):>7.2f} {_cagr(thr, ppy, years):>7.1%} "
              f"{_maxdd(thr):>7.1%} {p5:>8.1%} {p80:>7.1%}")

    # Part B — headroom test: firm throttle at HIGHER target-vol vs OFF at 0.40.
    firm = THROTTLES["firm 10→30"]
    off_p5, _ = bad_year_dd(base, None, ppy)
    print(f"\nB) headroom test — can the FIRM throttle run higher leverage for the same bad-year DD?")
    print(f"   reference: throttle OFF @ tv0.40  →  bad-year DD {off_p5:.1%}, CAGR {_cagr(base, ppy, years):.1%}")
    hdr2 = f"   {'firm @ tv':>10} {'Sharpe':>7} {'CAGR':>8} {'maxDD':>7} {'badYrDD':>8}"
    print(hdr2); print("   " + "-" * (len(hdr2) - 3))
    for tv in HEADROOM_TVS:
        rr = raw_returns(tv, 10.0)            # high cap so tv drives sizing
        thr = throttle_path(rr, firm)
        p5, _ = bad_year_dd(rr, firm, ppy)
        flag = "  <= same/better bad-year than off@0.40, MORE CAGR" if (p5 >= off_p5 and _cagr(thr, ppy, years) > _cagr(base, ppy, years)) else ""
        print(f"   {tv:>9.2f} {_sharpe(thr, ppy):>7.2f} {_cagr(thr, ppy, years):>7.1%} "
              f"{_maxdd(thr):>7.1%} {p5:>8.1%}{flag}")

    print("\nread: throttle WINS iff Part B finds a higher-tv row whose bad-year DD ≤ off@0.40's but CAGR is")
    print("higher — that means the throttle bought leverage headroom. If not, it only trades CAGR for DD 1:1")
    print("(still useful for comfort, but not free headroom).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
