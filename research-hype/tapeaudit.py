#!/usr/bin/env python3
"""/Users/maxkuzmentsov/development/projects/my/hummingbot/hummingbot-infra/research-hype/tapeaudit.py
Honest coverage/quality audit of the HL native tick tape before anything is modelled.

CLOCKS (do not conflate — this bit me once already):
  t     = RECORDER receive time, epoch SECONDS (float)      <- the causal gate
  time  = EXCHANGE event time, epoch MILLISECONDS (int)     <- the event clock
Any feature window must be gated on t (what we could have known), never on time.
"""
import glob, datetime as dt
import pandas as pd, numpy as np
TAPE="/Users/maxkuzmentsov/development/projects/my/hummingbot/hummingbot-infra/every-tick-single/data/pq-venue/hl"
U=dt.UTC
def load(stream, cols=None):
    fs=sorted(glob.glob(f"{TAPE}/{stream}/hype-*.parquet"))
    df=pd.concat([pd.read_parquet(f, columns=cols) for f in fs], ignore_index=True)
    df["recv"]=(df["t"]*1000).round().astype("int64")      # recv ms
    return df.sort_values("recv").reset_index(drop=True)
def f(ms): return dt.datetime.fromtimestamp(ms/1000,U).strftime("%m-%d %H:%M")

print("stream          rows   first(recv UTC)  last(recv UTC)    hrs  rows/hr")
for s in ["bbo","trades","l2Book","activeAssetCtx","candle"]:
    d=load(s,["t"]); a,b=d.recv.iloc[0],d.recv.iloc[-1]; hrs=(b-a)/3.6e6
    print(f"{s:14s}{len(d):9d}  {f(a)}     {f(b)}   {hrs:6.1f} {len(d)/hrs:8.0f}")

b=load("bbo")
print("\n-- recorder latency (recv - exchange time), ms --")
for s,d in [("bbo",b),("l2Book",load("l2Book",["t","time"]))]:
    lat=d.recv-d["time"]
    print(f"  {s:8s} p1={np.percentile(lat,1):7.0f} p50={np.percentile(lat,50):6.0f} p90={np.percentile(lat,90):6.0f} p99={np.percentile(lat,99):7.0f} max={lat.max():8.0f}")

print("\n-- bbo continuity (recv clock) --")
g=np.diff(b.recv.values)/1000.
print(f"  n={len(b)} dt p50={np.percentile(g,50):.3f}s p90={np.percentile(g,90):.2f}s p99={np.percentile(g,99):.2f}s max={g.max():.0f}s")
big=np.where(g>30)[0]
print(f"  gaps >30s: {len(big)}, total {g[big].sum()/3600:.2f} h lost of {(b.recv.iloc[-1]-b.recv.iloc[0])/3.6e6:.1f} h"
      f"  => effective coverage {100*(1-g[big].sum()/((b.recv.iloc[-1]-b.recv.iloc[0])/1000)):.2f}%")
for i in big[np.argsort(-g[big])][:6]:
    print(f"    {f(b.recv.values[i])} -> {g[i]/60:6.1f} min")

print("\n-- bbo microstructure --")
sp=b.ask-b.bid; mid=(b.ask+b.bid)/2; sb=sp/mid*1e4
print(f"  crossed/locked: {(sp<=0).sum()}")
print(f"  spread bps p5={np.percentile(sb,5):.2f} p50={np.percentile(sb,50):.2f} p90={np.percentile(sb,90):.2f} p99={np.percentile(sb,99):.2f} mean={sb.mean():.3f}")
print(f"  1-tick(0.001) wide: {np.isclose(sp,0.001).mean()*100:.1f}% of quotes; mid {mid.median():.2f}")
print(f"  touch notional p50 ${(b.bidsz*b.bid).median():,.0f} bid / ${(b.asksz*b.ask).median():,.0f} ask")
print(f"  touch imbalance (bidsz-asksz)/(sum) sd={((b.bidsz-b.asksz)/(b.bidsz+b.asksz)).std():.3f}")

print("\n-- trades --")
tr=load("trades")
lat=tr.recv-tr["time"]
print(f"  side: {tr.side.value_counts().to_dict()}  (A=? B=?)")
print(f"  recv-time ms: p1={np.percentile(lat,1):.0f} p50={np.percentile(lat,50):.0f} p99={np.percentile(lat,99):.0f} max={lat.max():.0f}")
print(f"  rows with recv-time > 5s (subscribe backfill): {(lat>5000).sum()} ({(lat>5000).mean()*100:.2f}%)")
print(f"  zero-hash rows: {(tr.hash=='0x'+'0'*64).sum()} ({(tr.hash=='0x'+'0'*64).mean()*100:.1f}%)")
nz=tr[tr.hash!='0x'+'0'*64]
print(f"  non-zero hashes: {len(nz)} rows, {nz.hash.nunique()} unique -> {len(nz)/max(nz.hash.nunique(),1):.2f} fills/hash (one taker order sweeps N makers)")
dupkey=tr.duplicated(subset=["time","side","px","sz","hash"]).sum()
print(f"  exact dup rows (time,side,px,sz,hash): {dupkey} ({dupkey/len(tr)*100:.2f}%)")
span_h=(tr.recv.iloc[-1]-tr.recv.iloc[0])/3.6e6
print(f"  sz p50={tr.sz.median():.2f} p90={tr.sz.quantile(.9):.2f} max={tr.sz.max():.1f}")
print(f"  notional/hr ${(tr.px*tr.sz).sum()/span_h:,.0f}  (dedup'd: ${(nz.px*nz.sz).sum()/span_h:,.0f})")

print("\n-- activeAssetCtx --")
ac=load("activeAssetCtx")
mo=(ac['mark']-ac['oracle'])/ac['oracle']*1e4
print(f"  mark-oracle bps mean={mo.mean():.3f} sd={mo.std():.3f} p5={np.percentile(mo,5):.2f} p95={np.percentile(mo,95):.2f}")
print(f"  funding(hourly) p50={ac.funding.median():.8f} = {ac.funding.median()*24*365*100:.1f}%/yr; range {ac.funding.min()*24*365*100:.0f}..{ac.funding.max()*24*365*100:.0f}%/yr")
print(f"  oi {ac.oi.min():,.0f}..{ac.oi.max():,.0f} HYPE (${ac.oi.min()*ac['mid'].mean()/1e6:.0f}M..${ac.oi.max()*ac['mid'].mean()/1e6:.0f}M)")
print(f"  mid {ac['mid'].min():.3f}..{ac['mid'].max():.3f}  ({(ac['mid'].max()/ac['mid'].min()-1)*100:.1f}% range over the tape)")
print(f"  distinct oi values {ac.oi.nunique()}, distinct funding {ac.funding.nunique()} (update cadence)")

print("\n-- candle stream (in-progress bar snapshots) --")
cd_=load("candle")
print(f"  rows {len(cd_)}, distinct kt {cd_.kt.nunique()} -> {len(cd_)/cd_.kt.nunique():.1f} snapshots per 1m bar")
print(f"  NOTE: rows are repeated snapshots of the OPEN bar; take last-per-kt for a closed bar,")
print(f"        and gate on recv, else the bar's close is known before kT.")
