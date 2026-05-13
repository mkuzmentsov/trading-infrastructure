"""Backtest the funding-carry strategy: long Kraken spot + short Hyperliquid perp.

PnL (as a fraction of notional), per held hour: + fundingRate  (HL convention:
positive funding => longs pay shorts; we're short the perp, so we collect it).
Costs: a round-trip when we open AND later close a position — HL perp maker
in+out (~1bp each) + Kraken spot in+out (fee-free via KFEE) ≈ --rt-cost-bps.
Plus an optional basis haircut per round-trip (perp/spot can drift a few bps).

Two policies compared per coin:
  - always_hold : open at t0, never close. Earns Σ(all funding, incl. negative
    hours). Pays one round-trip. Lower bound on operational hassle.
  - threshold   : maintain a position only while a smoothed annualized funding
    estimate (trailing --smooth-hrs mean) is above --open-pct; close when it
    drops below --close-pct. Avoids negative-funding regimes; pays a round-trip
    per cycle.

Usage:
    python3 funding-carry/backtest.py
        [--coins BTC,ETH,...] [--open-pct 12] [--close-pct 3]
        [--smooth-hrs 48] [--rt-cost-bps 3] [--basis-bps 3]
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
FUNDING = REPO / "funding-carry" / "data" / "hl_funding.parquet"

HOURS_PER_YEAR = 24 * 365


def _max_drawdown(cum: np.ndarray) -> float:
    if len(cum) == 0:
        return 0.0
    peak = np.maximum.accumulate(cum)
    return float(np.max(peak - cum))


def sim_always_hold(fr: np.ndarray, rt_cost: float, basis: float) -> dict:
    pnl = fr.copy()
    # one round-trip cost charged up front
    cum = np.cumsum(pnl)
    cum = cum - (rt_cost + basis)
    total = float(cum[-1])
    n = len(fr)
    return {
        "policy": "always_hold", "total_ret": total,
        "ann_ret": total * HOURS_PER_YEAR / n,
        "n_cycles": 1, "fees_paid": rt_cost + basis, "frac_deployed": 1.0,
        "neg_hours": int((fr < 0).sum()),
        "max_dd": _max_drawdown(cum),
    }


def sim_threshold(fr: np.ndarray, open_thr: float, close_thr: float,
                  smooth_hrs: int, rt_cost: float, basis: float) -> dict:
    """open_thr/close_thr are ANNUALIZED fractions (e.g. 0.12 = 12%/yr)."""
    n = len(fr)
    # trailing-mean annualized funding estimate
    s = pd.Series(fr)
    smooth_ann = s.rolling(smooth_hrs, min_periods=max(4, smooth_hrs // 4)).mean().to_numpy() * HOURS_PER_YEAR
    smooth_ann = np.nan_to_num(smooth_ann, nan=0.0)

    in_pos = False
    cum = 0.0
    curve = np.empty(n)
    n_cycles = 0
    fees = 0.0
    held_hours = 0
    for t in range(n):
        if not in_pos and smooth_ann[t] >= open_thr:
            in_pos = True
            n_cycles += 1
            cum -= (rt_cost + basis)
            fees += (rt_cost + basis)
        if in_pos:
            cum += fr[t]
            held_hours += 1
            if smooth_ann[t] <= close_thr:
                in_pos = False
        curve[t] = cum
    total = float(cum)
    return {
        "policy": f"thr(open={open_thr*100:.0f}%,close={close_thr*100:.0f}%,sm={smooth_hrs}h)",
        "total_ret": total, "ann_ret": total * HOURS_PER_YEAR / n,
        "n_cycles": n_cycles, "fees_paid": fees,
        "frac_deployed": held_hours / n,
        "neg_hours": int(((fr < 0) & (curve != np.r_[0, curve[:-1]])).sum()),  # rough
        "max_dd": _max_drawdown(curve),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--coins", default="BTC,ETH,SOL,HYPE,DOGE,XRP,AVAX,LINK")
    ap.add_argument("--open-pct", type=float, default=12.0, help="open when smoothed annual funding >= this %%")
    ap.add_argument("--close-pct", type=float, default=3.0, help="close when smoothed annual funding <= this %%")
    ap.add_argument("--smooth-hrs", type=int, default=48)
    ap.add_argument("--rt-cost-bps", type=float, default=3.0, help="round-trip trading cost in bps (HL maker x2; Kraken free)")
    ap.add_argument("--basis-bps", type=float, default=3.0, help="extra round-trip haircut for perp/spot basis drift, bps")
    ap.add_argument("--sweep", action="store_true", help="also sweep open/close thresholds")
    args = ap.parse_args()

    df = pd.read_parquet(FUNDING)
    coins = [c.strip().upper() for c in args.coins.split(",") if c.strip()]
    rt = args.rt_cost_bps / 1e4
    basis = args.basis_bps / 1e4
    open_thr, close_thr = args.open_pct / 100.0, args.close_pct / 100.0

    span_days = (df["dt"].max() - df["dt"].min()).total_seconds() / 86400
    print(f"[backtest] span {df['dt'].min().date()} → {df['dt'].max().date()} ({span_days:.0f}d)  "
          f"rt_cost={args.rt_cost_bps}bps basis={args.basis_bps}bps  open={args.open_pct}% close={args.close_pct}% smooth={args.smooth_hrs}h")
    print(f"\n{'coin':<6} {'policy':<28} {'total%':>8} {'ann%':>7} {'cycles':>7} {'fees%':>7} {'deployed':>9} {'maxDD%':>8}")
    summary = {}
    for coin in coins:
        sub = df[df["coin"] == coin].sort_values("time")
        if len(sub) < 100:
            print(f"{coin:<6} (insufficient data)")
            continue
        fr = sub["fundingRate"].to_numpy()
        a = sim_always_hold(fr, rt, basis)
        h = sim_threshold(fr, open_thr, close_thr, args.smooth_hrs, rt, basis)
        for r in (a, h):
            print(f"{coin:<6} {r['policy']:<28} {r['total_ret']*100:>7.2f} {r['ann_ret']*100:>6.1f} "
                  f"{r['n_cycles']:>7} {r['fees_paid']*100:>6.2f} {r['frac_deployed']*100:>8.0f}% {r['max_dd']*100:>7.2f}")
        summary[coin] = (a, h)

    # combined: equal-weight a basket of the top coins by always-hold ann return
    ranked = sorted(summary.items(), key=lambda kv: -kv[1][0]["ann_ret"])
    print("\n[ranked by always-hold annualized funding]")
    for coin, (a, h) in ranked:
        print(f"  {coin:<6} always_hold ann={a['ann_ret']*100:+.1f}%  threshold ann={h['ann_ret']*100:+.1f}%  "
              f"(thr deployed {h['frac_deployed']*100:.0f}%, {h['n_cycles']} cycles)")

    if args.sweep:
        print("\n[sweep] threshold open/close on BTC+ETH avg (ann %):")
        be = [df[df.coin == c].sort_values("time")["fundingRate"].to_numpy() for c in ("BTC", "ETH")]
        print(f"  {'open%':>6} {'close%':>6} {'sm=24h':>9} {'sm=48h':>9} {'sm=96h':>9} {'sm=168h':>9}")
        for op in (6, 9, 12, 15, 20, 30):
            for cl in (0, 3, 6):
                if cl >= op:
                    continue
                row = []
                for sm in (24, 48, 96, 168):
                    rs = [sim_threshold(fr, op/100, cl/100, sm, rt, basis)["ann_ret"] for fr in be]
                    row.append(f"{np.mean(rs)*100:>8.1f}")
                print(f"  {op:>6} {cl:>6} " + " ".join(row))
        # always-hold reference
        ah = [sim_always_hold(fr, rt, basis)["ann_ret"] for fr in be]
        print(f"  always-hold BTC+ETH avg: {np.mean(ah)*100:+.1f}%/yr")


if __name__ == "__main__":
    main()
