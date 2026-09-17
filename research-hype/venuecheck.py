#!/usr/bin/env python3
"""/Users/maxkuzmentsov/development/projects/my/hummingbot/hummingbot-infra/research-hype/venuecheck.py
Is the Bybit tape a usable PROXY for HL? Compare the two venues ON RETURNS ONLY.
Comparing LEVELS across venues is the mistake that killed a real signal once
(Chainlink sat 4.71 bps below Binance); this script exists to not repeat it."""
import numpy as np, pandas as pd
H="/Users/maxkuzmentsov/development/projects/my/hummingbot/hummingbot-infra/every-tick-single/data/hl-hist"
hl=pd.read_parquet(f"{H}/candles/HYPE-1m.parquet")[["t","c"]].rename(columns={"c":"hl"})
by=pd.read_parquet(f"{H}/bybit/kline/HYPEUSDT-1.parquet")[["t","c"]].rename(columns={"c":"by"})
d=hl.merge(by,on="t").sort_values("t"); d["dt"]=pd.to_datetime(d.t,unit="ms",utc=True)
print(f"overlapping 1m bars: {len(d):,}   {d.dt.min():%Y-%m-%d %H:%M} -> {d.dt.max():%Y-%m-%d %H:%M}")
lvl=(d.by/d.hl-1)*1e4
print(f"\nLEVEL difference (Bybit vs HL): mean {lvl.mean():+.2f} bps  sd {lvl.std():.2f}  "
      f"p5 {lvl.quantile(.05):+.1f} p95 {lvl.quantile(.95):+.1f}")
print(f"  -> a persistent {lvl.mean():+.2f} bps offset. THIS IS WHY YOU NEVER COMPARE LEVELS.")
rh=np.log(d.hl).diff(); rb=np.log(d.by).diff()
m=rh.notna()&rb.notna()
print(f"\nRETURN comparison (the correct one): corr(1m log returns) = {np.corrcoef(rh[m],rb[m])[0,1]:.4f}")
print(f"  sd HL {rh[m].std()*1e4:.2f} bps   sd Bybit {rb[m].std()*1e4:.2f} bps   ratio {rb[m].std()/rh[m].std():.3f}")
for lag in (-3,-2,-1,0,1,2,3):
    c=np.corrcoef(rh[m].values, np.roll(rb[m].values,lag))[0,1]
    print(f"    corr(HL_t, Bybit_t{lag:+d}) = {c:+.4f}" + ("   <- contemporaneous" if lag==0 else ""))
print("""
  A lag whose correlation EXCEEDS the contemporaneous one would indicate one venue
  leads the other at minute resolution. At 1m bars this is far too coarse to resolve a
  sub-second lead -- read it only as 'the two tapes describe the same asset'.""")
