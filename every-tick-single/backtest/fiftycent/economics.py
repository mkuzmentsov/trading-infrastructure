#!/usr/bin/env python3
"""The 50c two-sided rebate strategy economics on a month of Binance 5m bars.

Rest 0.50 BUY on BOTH up & down each bar, hold to resolution:
  both fill  -> own up+down @0.50 = $1.00 cost, $1.00 payout = breakeven + 2x rebate
  one fills  -> own the LOSING side @0.50 = -$0.50 + 1x rebate   (single-fill drag)

Fill proxy from OHLC: a token's 0.50 bid fills iff BTC crosses to that token's
side of the open. up fills iff low < open (BTC dipped below open);
down fills iff high > open. single-fill (monotonic bar) = only one crosses.
Rebate/share = feeRate * p*(1-p); at p=0.50 -> 0.0175 (fee-equiv) or *0.20 (real).
"""
import numpy as np, pandas as pd

d = pd.read_csv("data.csv")
for c in ["open", "high", "low", "close"]:
    d[c] = d[c].astype(float)

up_fill = d["low"] < d["open"]     # BTC went below open -> up token <=0.50
dn_fill = d["high"] > d["open"]    # BTC went above open -> down token <=0.50
both = up_fill & dn_fill
single = up_fill ^ dn_fill
outcome_up = d["close"] >= d["open"]

n = len(d)
f_both, f_single = both.mean(), single.mean()
print(f"bars: {n}   ({n/288:.1f} days of 5m bars)")
print(f"both-fill (locked breakeven pair): {100*f_both:.1f}%")
print(f"single-fill (monotonic bar):       {100*f_single:.1f}%")

# single-fill always lands on the losing side — verify
sc = single
lose = sc & (((up_fill & ~dn_fill) & ~outcome_up) | ((dn_fill & ~up_fill) & outcome_up))
print(f"  of single-fills, fraction on the LOSING side: {100*lose[sc].mean():.1f}% "
      f"(n={sc.sum()})  <- these lose $0.50\n")

print(f"{'rebate/share':>14} {'EV/bar (1-share quotes)':>24} {'per day (288 bars)':>20} {'verdict':>10}")
for label, r in [("fee-equiv 0.0175", 0.0175), ("real 20%  0.0035", 0.0035)]:
    ev = f_both * (2 * r) + f_single * (-0.50 + r)
    print(f"{label:>16} {ev:>+22.4f}   {ev*288:>+18.2f}   {'+EV' if ev>0 else 'LOSES':>10}")

r_be = 2 * (f_single) / (2 * f_both + f_single) * 0.5  # solve both*2r+single*(r-0.5)=0
# both*2r + single*r - single*0.5 = 0 -> r(2both+single)=0.5 single
r_be = 0.5 * f_single / (2 * f_both + f_single)
print(f"\nbreakeven rebate/share = {r_be:.4f}  (need this much just to not lose)")
print(f"  fee-equiv rebate {0.0175:.4f} is {'ABOVE' if 0.0175>r_be else 'below'} breakeven; "
      f"real 20% rebate {0.0035:.4f} is {'above' if 0.0035>r_be else 'BELOW'} breakeven")

# how much would we need to cut single-fills (skip trending bars) to break even at real rebate?
r = 0.0035
# EV = (1-f)*2r + f*(r-0.5) >= 0  ->  f <= 2r/(0.5+r)
f_max = 2 * r / (0.5 + r)
print(f"\nTo break even at the real 0.0035 rebate, single-fill rate must be <= {100*f_max:.1f}% "
      f"(currently {100*f_single:.1f}%). Requires skipping ~{100*(1-f_max/f_single):.0f}% of trending bars,")
print("which needs predicting direction/trend — and the OOS model just showed that's a coin flip.")
