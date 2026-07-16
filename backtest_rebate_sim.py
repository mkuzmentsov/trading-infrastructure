#!/usr/bin/env python3
"""Passive ~50c every-bar rebate-harvester simulation, per coin.

UpDown 5m market: UP wins if close>=open. UP token ~ P(close>=open), ~0.50 at open.
A passive 0.50 BUY on UP fills iff the underlying dips below open intrabar (low<open)
-> UP token touches <=0.50 and our rest is lifted. It WINS iff close>=open.
Symmetric for DOWN (fills iff high>open, wins iff close<open).

This exposes adverse selection: does a filled 0.50 rest win >=50% of the time?
Rebate model: HL/PM maker rebate ~= 0.20 * 0.07 * p*(1-p) per share; at p=0.5 -> 0.0035 (0.35c).
"""
import sys, numpy as np, pandas as pd

FILES={"btc":"every-tick-single/backtest/fiftycent/data.csv",
       "eth":"every-tick-single/backtest/fiftycent/data_eth.csv",
       "sol":"every-tick-single/backtest/fiftycent/data_sol.csv",
       "xrp":"every-tick-single/backtest/fiftycent/data_xrp.csv",
       "doge":"every-tick-single/backtest/fiftycent/data_doge.csv",
       "bnb":"every-tick-single/backtest/fiftycent/data_bnb.csv"}
REBATE=0.20*0.07*0.25   # per-share maker rebate at p=0.5 ~ 0.0035
SH=10                    # 10 shares = $5 at 0.50

def load(p):
    d=pd.read_csv(p)
    for c in ["open","high","low","close"]: d[c]=d[c].astype(float)
    return d

print(f"REBATE/share={REBATE:.4f} ($ per 10-share fill = {REBATE*SH:.4f})\n")
print(f"{'coin':>5} {'bars':>7} | {'UPfill%':>7} {'UPwin%':>7} | {'DNfill%':>7} {'DNwin%':>7} | {'2side filledWin%':>16} {'net$/bar(2side)':>16}")
for coin,p in FILES.items():
    try: d=load(p)
    except Exception as e: print(coin,"load err",e); continue
    o,h,l,c=d["open"],d["high"],d["low"],d["close"]
    up_win=(c>=o)
    up_fill=(l<o)      # UP 0.50 rest fills when underlying dips below open
    dn_fill=(h>o)      # DOWN 0.50 rest fills when underlying pops above open
    dn_win=(c<o)
    n=len(d)
    upf=up_fill.mean(); upw=(up_win[up_fill]).mean()
    dnf=dn_fill.mean(); dnw=(dn_win[dn_fill]).mean()
    # two-sided: each bar we may fill UP and/or DOWN. Count each fill as a bet.
    # filled bets outcomes:
    up_bets=up_fill.sum(); up_wins=(up_win&up_fill).sum()
    dn_bets=dn_fill.sum(); dn_wins=(dn_win&dn_fill).sum()
    tot_bets=up_bets+dn_bets; tot_wins=up_wins+dn_wins
    fw=tot_wins/tot_bets
    # net $ per bar for two-sided passive 0.50: each win +$5+rebate, each loss -$5+rebate (10sh)
    # PnL per filled bet = 10*((1 if win else 0) - 0.50) + rebate*10
    pnl_up = 10*((up_win&up_fill).astype(float)-0.50) + REBATE*SH*up_fill.astype(float)
    pnl_dn = 10*((dn_win&dn_fill).astype(float)-0.50) + REBATE*SH*dn_fill.astype(float)
    net_per_bar=(pnl_up.sum()+pnl_dn.sum())/n
    print(f"{coin:>5} {n:>7} | {100*upf:>6.1f}% {100*upw:>6.1f}% | {100*dnf:>6.1f}% {100*dnw:>6.1f}% | {100*fw:>15.1f}% {net_per_bar:>16.4f}")

print("\n--- interpretation guide ---")
print("filledWin% < 50% => adverse selection confirmed; rebate (0.035$/fill) cannot cover a 5$ wrong bet.")
print("net$/bar negative => passive 50c two-sided rebate harvest is -EV on that coin.")
PY