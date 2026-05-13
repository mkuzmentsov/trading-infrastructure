"""Funding-carry backtest v2: real basis P&L + liquidation stress.

v1 ('hold, don't time' won) assumed a flat 3bps basis haircut and ignored
liquidation. v2 uses:
  - HL `premium` field (perp-vs-index basis, already fetched) for the REAL
    basis P&L on entry/exit, and the worst-case if you're forced to unwind at
    a bad basis moment.
  - HL 1h candles to measure the largest up-moves over rebalance-sized windows
    (1h / 6h / 24h) per coin → at what leverage would a single such move
    liquidate the HL short.

Net realistic always-hold return per coin ≈ Σ(funding) − round-trip fees
− (premium_close − premium_open). If you pick your exit (close when the basis
is favourable), the basis term ≈ 0+; if forced, up to the worst-case shown.

Usage: python3 funding-carry/backtest_v2.py [--coins ...] [--rt-bps 3]
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
FUNDING = REPO / "funding-carry" / "data" / "hl_funding.parquet"
CANDLES = REPO / "funding-carry" / "data" / "hl_candles_1h.parquet"
HRS_YR = 24 * 365

# HL maintenance-margin estimates (fraction of notional). Majors get high max
# leverage ⇒ low maintenance; alts lower. Rough, conservative-ish.
MAINT = {"BTC": 0.01, "ETH": 0.01, "SOL": 0.025, "HYPE": 0.05, "DOGE": 0.05,
         "XRP": 0.05, "AVAX": 0.05, "LINK": 0.05}
DEFAULT_MAINT = 0.05


def max_up_move(close: np.ndarray, high: np.ndarray, window_h: int) -> float:
    """Largest (high over next `window_h` hours) / (close now) − 1, across all t.

    This is how much a short loses, worst case, if it can't rebalance for
    `window_h` hours after entering at `close`.
    """
    n = len(close)
    worst = 0.0
    for t in range(n - 1):
        end = min(n, t + window_h + 1)
        peak = high[t + 1:end].max() if end > t + 1 else close[t]
        worst = max(worst, peak / close[t] - 1.0)
    return worst


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--coins", default="BTC,ETH,SOL,HYPE,DOGE,XRP,AVAX,LINK")
    ap.add_argument("--rt-bps", type=float, default=3.0, help="HL maker round-trip, bps (Kraken leg free via KFEE)")
    args = ap.parse_args()
    coins = [c.strip().upper() for c in args.coins.split(",") if c.strip()]
    rt = args.rt_bps / 1e4

    fund = pd.read_parquet(FUNDING)
    cdl = pd.read_parquet(CANDLES)
    span_d = (fund["dt"].max() - fund["dt"].min()).total_seconds() / 86400
    print(f"[v2] span {fund['dt'].min().date()} → {fund['dt'].max().date()} ({span_d:.0f}d)  rt={args.rt_bps}bps\n")

    # --- 1. realistic always-hold return + basis ---
    print("=== Always-hold: realistic net return & basis risk ===")
    print(f"{'coin':<6} {'Σfunding%':>10} {'fees%':>6} {'basis(o→c)%':>12} {'net%/yr':>9}  "
          f"{'premium mean/min/max bps':>26}  {'forced-unwind worst%':>21}")
    rows = {}
    for c in coins:
        fs = fund[fund.coin == c].sort_values("time")
        if len(fs) < 100:
            continue
        fr = fs["fundingRate"].to_numpy()
        prem = fs["premium"].to_numpy()
        n = len(fr)
        sigma_funding = float(fr.sum())
        # open at t0, close at t_last → basis P&L = prem[0] - prem[-1]
        basis_pl = float(prem[0] - prem[-1])
        net = sigma_funding - rt - basis_pl  # note: basis_pl could be + or -
        ann = net * HRS_YR / n
        # forced unwind: opened at the median premium, forced to close at the worst-for-short premium (max)
        forced_worst = float(np.median(prem) - prem.max())  # negative = loss
        rows[c] = {"ann": ann, "sigma": sigma_funding, "basis": basis_pl,
                   "prem_mean": prem.mean(), "prem_min": prem.min(), "prem_max": prem.max(),
                   "forced_worst": forced_worst, "fr": fr, "n": n}
        print(f"{c:<6} {sigma_funding*100:>9.2f} {rt*100:>5.2f} {basis_pl*100:>11.3f} {ann*100:>8.1f}  "
              f"{prem.mean()*1e4:>+8.1f}/{prem.min()*1e4:>+7.1f}/{prem.max()*1e4:>+7.1f}  "
              f"{forced_worst*100:>20.2f}")

    # --- 2. liquidation stress: largest up-moves over rebalance windows ---
    print("\n=== Liquidation stress: largest up-move over a rebalance window, vs leverage ===")
    print("(a short loses `move%` of notional; margin = 1/L of notional; liq when loss ≳ 1/L − maint)")
    print(f"{'coin':<6} {'max+1h%':>8} {'max+6h%':>8} {'max+24h%':>9} {'maint%':>7}  "
          f"{'liq-move @L=2':>13} {'@L=3':>8} {'@L=5':>8}  {'safe @L (24h rebal)':>20}")
    for c in coins:
        cs = cdl[cdl.coin == c].sort_values("time")
        if len(cs) < 100:
            continue
        close = cs["close"].to_numpy(); high = cs["high"].to_numpy()
        m1 = max_up_move(close, high, 1)
        m6 = max_up_move(close, high, 6)
        m24 = max_up_move(close, high, 24)
        maint = MAINT.get(c, DEFAULT_MAINT)
        liq = {L: 1.0 / L - maint for L in (2, 3, 5)}
        # highest L that survives a 24h-window worst move
        safe_L = 0
        for L in (2, 3, 5, 10, 20):
            if (1.0 / L - maint) > m24:
                safe_L = L
        print(f"{c:<6} {m1*100:>7.1f} {m6*100:>7.1f} {m24*100:>8.1f} {maint*100:>6.1f}  "
              f"{liq[2]*100:>12.0f} {liq[3]*100:>7.0f} {liq[5]*100:>7.0f}  "
              f"{('L='+str(safe_L)) if safe_L else 'NONE — even L=2 risky':>20}")

    # --- 3. basket view ---
    print("\n=== Basket (equal-weight) realistic net ann return ===")
    for sel in (["BTC", "ETH"], ["BTC", "ETH", "HYPE", "LINK"], coins):
        present = [c for c in sel if c in rows]
        if not present:
            continue
        ann = np.mean([rows[c]["ann"] for c in present])
        print(f"  {'+'.join(present):<40} → {ann*100:+.1f}%/yr  (worst single-coin forced-unwind: "
              f"{min(rows[c]['forced_worst'] for c in present)*100:.2f}%)")

    print("\nNotes:")
    print(" - 'basis(o→c)%' uses open at first hour, close at last — over 360d it's ~0 (premium mean-reverts).")
    print(" - 'forced-unwind worst%' = loss if you opened at the median premium and were FORCED to close at the")
    print("   worst-for-a-short premium spike in the window. This is the realistic tail when you can't pick your exit.")
    print(" - Liquidation: with a tight (e.g. minutely) rebalance loop the relevant window is ~1h, not 24h —")
    print("   24h is the worst case if the rebalancer/exchange is DOWN for a day. Build with low L + kill switch anyway.")
    print(" - Premium ≈ (HL perp − HL index)/index. Real Kraken-spot basis ≈ this ± a couple bps. Good enough for sizing.")


if __name__ == "__main__":
    main()
