#!/usr/bin/env python3
"""/Users/maxkuzmentsov/development/projects/my/hummingbot/hummingbot-infra/research-hype/ceiling.py
THE CEILING TEST. Before any model: what would a PERFECT oracle earn, net of the
real HL fee (taker 4.50 bps/side, maker 1.50 bps/side, no discounts)?
If clairvoyance doesn't clear the fee, no model can, and the program is over."""
import pandas as pd, numpy as np
P="/Users/maxkuzmentsov/development/projects/my/hummingbot/hummingbot-infra/research-hype/../every-tick-single/data/hl-hist/panel/tick_hype_1s.parquet"
d=pd.read_parquet(P)
d=d[d.stale_ms<2000]
TK,MK=4.50,1.50
print(f"n={len(d):,} rows, {d.day.nunique()} days, fresh quotes only (stale<2s)\n")
print(f"{'h':>5s} {'sd(mid) bps':>11s} {'E|mid| bps':>10s} | {'ORACLE taker/taker':>18s} {'mixed':>8s} {'maker/maker':>11s} | {'P(|mv|>9bps)':>12s} {'coin-flip net':>13s}")
for h in [1,5,30,60,300]:
    lg=d[f"fwd{h}s_long_gross_bps"].values; sh=d[f"fwd{h}s_short_gross_bps"].values
    m=d[f"fwd{h}s_mid_bps"].values
    ok=~np.isnan(lg)&~np.isnan(sh)&~np.isnan(m); lg,sh,m=lg[ok],sh[ok],m[ok]
    row=[]
    for rt in (2*TK, TK+MK, 2*MK):
        best=np.maximum(np.maximum(lg,sh)-rt, 0.0)     # perfect oracle, may abstain
        row.append(best.mean())
    flip=(np.where(np.random.default_rng(0).random(len(lg))<0.5,lg,sh)-2*TK).mean()
    print(f"{h:4d}s {m.std():11.2f} {np.abs(m).mean():10.2f} | {row[0]:18.3f} {row[1]:8.3f} {row[2]:11.3f} | {np.mean(np.abs(m)>9)*100:11.1f}% {flip:13.2f}")
print("""
READ: 'ORACLE' = mean bps per round trip for a trader who KNOWS the sign in advance
and only trades when it pays. It is an upper bound no model can reach. Compare it
to the transaction cost it already has deducted.""")

print("\n-- how much of the oracle's money is in how few instants? --")
h=60; lg=d[f"fwd{h}s_long_gross_bps"].values; sh=d[f"fwd{h}s_short_gross_bps"].values
best=np.maximum(np.maximum(lg,sh)-2*TK,0.0); best=best[~np.isnan(best)]
s=np.sort(best)[::-1]; tot=s.sum()
for q in (0.001,0.01,0.05,0.10,0.25):
    k=int(len(s)*q); print(f"  top {q*100:5.1f}% of instants = {s[:k].sum()/tot*100:5.1f}% of the oracle's gross")
print(f"  instants where the oracle trades at all: {np.mean(best>0)*100:.1f}%")

print("\n-- per-day stability of the 60s oracle (taker/taker) --")
d2=d.dropna(subset=["fwd60s_long_gross_bps","fwd60s_short_gross_bps"]).copy()
d2["orc"]=np.maximum(np.maximum(d2.fwd60s_long_gross_bps,d2.fwd60s_short_gross_bps)-2*TK,0)
g=d2.groupby("day").orc.agg(["mean","count"])
print(g.to_string())
