#!/usr/bin/env python3
"""/Users/maxkuzmentsov/development/projects/my/hummingbot/hummingbot-infra/research-hype/carry.py
Robustness on the FUNDING CARRY lead, 21 months, native HL, complete hourly series.
This program's history is full of effects that were one day or one fill -- so the
question is not 'is funding positive' but 'is it positive WITHOUT its best months'."""
import numpy as np, pandas as pd
H="/Users/maxkuzmentsov/development/projects/my/hummingbot/hummingbot-infra/every-tick-single/data/hl-hist"
f=pd.read_parquet(f"{H}/funding/HYPE.parquet").sort_values("time")
f["dt"]=pd.to_datetime(f.time,unit="ms",utc=True); f["m"]=f.dt.dt.strftime("%Y-%m"); f["d"]=f.dt.dt.strftime("%Y-%m-%d")
r=f.fundingRate.values
apr=lambda x: np.mean(x)*24*365*100
print(f"hourly points {len(f):,}  {f.dt.min():%Y-%m-%d} -> {f.dt.max():%Y-%m-%d}")
print(f"P(rate>0) = {(r>0).mean()*100:.1f}%   P(at the +0.00125%/hr floor) = {np.isclose(r,1.25e-5,atol=1e-9).mean()*100:.1f}%")
print(f"mean APR {apr(r):+.2f}%   median-hour APR {np.median(r)*24*365*100:+.2f}%")
print(f"total funding collected by a continuous SHORT over the sample: {r.sum()*100:.1f}% of notional"
      f"  over {(f.dt.max()-f.dt.min()).days} days")

print("\n-- per-month APR (a short COLLECTS this) --")
g=f.groupby("m").fundingRate.agg(n="size",apr=lambda x: apr(x.values))
g["pos_share"]=f.groupby("m").fundingRate.apply(lambda x:(x>0).mean()*100)
print(g.to_string(float_format=lambda v:f"{v:8.2f}"))

print("\n-- leave-one-month-out (worst case = the month the effect depends on) --")
loo=[]
for m in sorted(f.m.unique()):
    x=f[f.m!=m].fundingRate.values; loo.append((m,apr(x)))
loo=pd.DataFrame(loo,columns=["dropped","apr_ex"]).sort_values("apr_ex")
print(f"  full-sample APR {apr(r):+.2f}%")
print(f"  worst LOO (drop {loo.iloc[0].dropped}): {loo.iloc[0].apr_ex:+.2f}%")
print(f"  best  LOO (drop {loo.iloc[-1].dropped}): {loo.iloc[-1].apr_ex:+.2f}%")
print(f"  ALL {len(loo)} leave-one-month-out values positive? {bool((loo.apr_ex>0).all())}")

print("\n-- concentration: is the carry a few spike days? --")
d=f.groupby("d").fundingRate.sum().sort_values(ascending=False)
tot=d.sum()
for k in (1,5,10,30):
    print(f"  top {k:3d} days = {d.iloc[:k].sum()/tot*100:5.1f}% of all funding collected  ({k/len(d)*100:.1f}% of days)")
print(f"  days with NEGATIVE daily funding: {(d<0).sum()} / {len(d)} ({(d<0).mean()*100:.1f}%)")
med=d.median(); print(f"  MEDIAN day = {med*100:.4f}% of notional = {med*365*100:+.1f}%/yr annualised")
print(f"  -> if you strip the top 30 days entirely, the rest still pays "
      f"{d.iloc[30:].sum()/ (len(d)-30) *365*100:+.1f}%/yr")

print("\n-- day-clustered SE on the daily funding series --")
dd=f.groupby("d").fundingRate.sum()*365*100
print(f"  mean {dd.mean():+.2f}%/yr  SE(day) {dd.std(ddof=1)/np.sqrt(len(dd)):.2f}  t={dd.mean()/(dd.std(ddof=1)/np.sqrt(len(dd))):+.1f}  n_days={len(dd)}")

print("\n-- ⚠️ the OTHER side of the trade: what a naked short pays --")
c=pd.read_parquet(f"{H}/panel/hist_HYPE_1d.parquet")
print(f"  HYPE log drift over the sample: {c.ret_bps.mean()*365/1e4*100:+.0f}%/yr")
print(f"  naked short = collect {apr(r):+.1f}%/yr funding, pay {c.ret_bps.mean()*365/1e4*100:+.0f}%/yr drift -> RUIN.")
print(f"  The carry is ONLY interesting DELTA-HEDGED (long HL spot @107 / short HL perp).")
print(f"  Spot leg depth, fees and borrow are NOT measured here -- that is the open question.")
