#!/usr/bin/env python3
"""
/Users/maxkuzmentsov/development/projects/my/hummingbot/hummingbot-infra/research-hype/panel_hist.py

HISTORY PANEL — HYPE from listing (2024-12-05) on its OWN venue (Hyperliquid),
at the only resolutions HL actually retains that far back: 4h and 1d.
Funding is hourly and complete from listing (15,634 points).

⚠️ THIS PANEL IS NOT JOINABLE TO THE TICK PANEL. Different resolution, different
   era, different feature set. Keep them apart (the brief's rule, and correct).

⚠️ DRIFT. HYPE went ~$10 -> ~$88 across this sample: +187 %/yr, ONE regime, one
   asset. Any long-biased backtest inherits that as fake alpha. Every return
   column is published twice:
       ret_*        raw
       retdd_*      de-drifted (full-sample mean log-return removed per bar)
   `retdd_` is IN-SAMPLE de-meaned and therefore itself slightly look-ahead --
   it is for DESCRIPTION and for null-building, never for a PnL claim. For an
   honest backtest use ret_* and carry an explicit long/short-neutral or
   market-neutral construction instead.

OUT: every-tick-single/data/hl-hist/panel/hist_<coin>_<iv>.parquet
"""
import argparse, os, numpy as np, pandas as pd

H="/Users/maxkuzmentsov/development/projects/my/hummingbot/hummingbot-infra/every-tick-single/data/hl-hist"
OUT=f"{H}/panel"
BAR_H={"1d":24.0,"4h":4.0,"2h":2.0,"1h":1.0,"30m":0.5,"15m":0.25,"5m":1/12,"1m":1/60}

def build(coin, iv, refs=("BTC","ETH","SOL")):
    c=pd.read_parquet(f"{H}/candles/{coin}-{iv}.parquet").sort_values("t").reset_index(drop=True)
    c["dt_utc"]=pd.to_datetime(c.t,unit="ms",utc=True)
    bar_h=BAR_H[iv]
    # --- price / return block ------------------------------------------
    lc=np.log(c.c.values)
    c["ret_bps"]=np.concatenate([[np.nan],np.diff(lc)])*1e4
    mu=np.nanmean(c.ret_bps)
    c["retdd_bps"]=c.ret_bps-mu
    c["drift_removed_bps_per_bar"]=mu
    for k in (2,6,24,72,168):
        n=max(int(round(k/bar_h)),1)
        c[f"ret_{k}h_bps"]=(pd.Series(lc).diff(n)*1e4).values
        c[f"retdd_{k}h_bps"]=c[f"ret_{k}h_bps"]-mu*n
    # --- realised vol / range ------------------------------------------
    for k in (24,168,720):
        n=max(int(round(k/bar_h)),3)
        c[f"rv_{k}h_bps"]=(pd.Series(c.ret_bps).rolling(n,min_periods=n//2).std()).values
    c["parkinson_bps"]=(np.log(c.h/c.l)/(2*np.sqrt(np.log(2)))*1e4)
    c["hl_range_bps"]=(c.h/c.l-1)*1e4
    c["co_bps"]=(c.c/c.o-1)*1e4
    c["gap_bps"]=(c.o/c.c.shift(1)-1)*1e4
    c["vol_usd"]=c.v*c.c
    c["avg_trade_usd"]=np.where(c.n>0,c.vol_usd/c.n.replace(0,np.nan),np.nan)
    c["dvol_z"]=(c.vol_usd-c.vol_usd.rolling(30,min_periods=10).mean())/c.vol_usd.rolling(30,min_periods=10).std()

    # --- funding block (hourly -> aggregated to the bar, CAUSAL) --------
    fp=f"{H}/funding/{coin}.parquet"
    if os.path.exists(fp):
        f=pd.read_parquet(fp).sort_values("time")
        f["dt"]=pd.to_datetime(f.time,unit="ms",utc=True)
        fs=f.set_index("dt")
        # funding PAID over the bar just ended: sum of hourly rates inside [t, t+bar)
        # integer-ms bucketing (IntervalIndex chokes on ms-vs-us datetime subtypes)
        edges=c.t.values.astype("int64"); barms=int(bar_h*3600_000)
        pos=np.searchsorted(edges, f.time.values, side="right")-1
        inside=(pos>=0)&(f.time.values < edges[np.clip(pos,0,None)]+barms)
        agg=pd.DataFrame({"pos":pos,"r":f.fundingRate.values,"p":f.premium.values})[inside]
        agg=agg.groupby("pos").agg(fund_bar_sum=("r","sum"),fund_bar_mean=("r","mean"),
                                   prem_bar_mean=("p","mean"),fund_n=("r","size"))
        c=c.join(agg)
        c["funding_bar_bps"]=c.fund_bar_sum*1e4          # cost of being long over the bar
        c["funding_apr_pct"]=c.fund_bar_mean*24*365*100
        c["premium_bps"]=c.prem_bar_mean*1e4
        for k in (24,168,720):
            n=max(int(round(k/bar_h)),3)
            c[f"funding_apr_ma{k}h"]=c.funding_apr_pct.rolling(n,min_periods=n//2).mean()
        # the carry thesis, stated as a column: short earns funding, pays the move
        c["short_carry_bar_bps"]=c.funding_bar_bps - c.ret_bps
    # --- cross-sectional reference (each venue vs ITSELF: returns only) --
    for r in refs:
        p=f"{H}/candles/{r}-{iv}.parquet"
        if not os.path.exists(p): continue
        q=pd.read_parquet(p)[["t","c"]].rename(columns={"c":f"{r}_c"})
        c=c.merge(q,on="t",how="left")
        c[f"ret_{r}_bps"]=(np.log(c[f"{r}_c"]).diff()*1e4)
        n=max(int(round(168/bar_h)),5)
        c[f"beta_{r}_168h"]=(pd.Series(c.ret_bps).rolling(n,min_periods=n//2)
                             .cov(pd.Series(c[f"ret_{r}_bps"]))/
                             pd.Series(c[f"ret_{r}_bps"]).rolling(n,min_periods=n//2).var())
        c[f"resid_{r}_bps"]=c.ret_bps-c[f"beta_{r}_168h"].shift(1)*c[f"ret_{r}_bps"]
    # --- forward targets ------------------------------------------------
    for k in (4,24,168):
        n=max(int(round(k/bar_h)),1)
        c[f"fwd_{k}h_bps"]=(pd.Series(lc).shift(-n)-pd.Series(lc)).values*1e4
        c[f"fwd_{k}h_dd_bps"]=c[f"fwd_{k}h_bps"]-mu*n
        if "funding_bar_bps" in c:
            c[f"fwd_{k}h_fund_bps"]=c.funding_bar_bps.shift(-n).rolling(n,min_periods=1).sum().values
    c["day"]=c.dt_utc.dt.strftime("%Y-%m-%d"); c["month"]=c.dt_utc.dt.strftime("%Y-%m")
    os.makedirs(OUT,exist_ok=True)
    p=f"{OUT}/hist_{coin}_{iv}.parquet"; c.to_parquet(p,compression="zstd",index=False)
    return p,c,mu

if __name__=="__main__":
    ap=argparse.ArgumentParser(); ap.add_argument("--coin",default="HYPE"); ap.add_argument("--ivs",default="1d,4h")
    a=ap.parse_args()
    for iv in a.ivs.split(","):
        p,c,mu=build(a.coin,iv)
        print(f"\n== {a.coin} {iv} -> {p}")
        print(f"   rows {len(c)}  {c.dt_utc.min():%Y-%m-%d} -> {c.dt_utc.max():%Y-%m-%d}  cols {len(c.columns)}")
        print(f"   drift removed: {mu:.2f} bps/bar = {mu*(365*24/BAR_H[iv])/1e4*100:.0f} %/yr")
        if "funding_apr_pct" in c:
            f=c.funding_apr_pct.dropna()
            print(f"   funding APR: mean {f.mean():.2f}%  median {f.median():.2f}%  P(>0) {(f>0).mean()*100:.1f}%  min {f.min():.0f}% max {f.max():.0f}%")
            print(f"   funding coverage: {c.fund_n.sum():.0f} hourly points over {len(c)} bars")
        print(f"   ret_bps sd {c.ret_bps.std():.0f}  ann vol {c.ret_bps.std()/1e4*np.sqrt(365*24/BAR_H[iv])*100:.0f}%")
