#!/usr/bin/env python3
"""
/Users/maxkuzmentsov/development/projects/my/hummingbot/hummingbot-infra/research-hype/panel_bybit.py

PROXY HISTORY PANEL — HYPE at MINUTE resolution for the full 21 months, sourced
from Bybit HYPEUSDT linear perp, because Hyperliquid keeps only ~5,000 candles
per interval (1m => 3.5 days). See DATA.md §2 and §3.

⚠️ THIS IS NOT HYPERLIQUID.
   * Different instrument, different book, different fee schedule.
   * HL is HYPE's home venue and almost certainly the price leader.
   * Use for REGIME / VOLATILITY / SEASONALITY / capacity context and for
     building nulls. Do NOT quote a PnL from it as if it were HL.
   * NEVER join it row-wise to the HL tick panel, and NEVER compare price
     LEVELS across the two venues -- difference each against itself first.
     (Chainlink/Binance sat 4.71 bps apart and that killed a real signal once.)

OUT: every-tick-single/data/hl-hist/panel/bybit_HYPEUSDT_<iv>.parquet
"""
import argparse, os, numpy as np, pandas as pd
B="/Users/maxkuzmentsov/development/projects/my/hummingbot/hummingbot-infra/every-tick-single/data/hl-hist/bybit"
OUT="/Users/maxkuzmentsov/development/projects/my/hummingbot/hummingbot-infra/every-tick-single/data/hl-hist/panel"
BAR_MIN={"1":1,"5":5,"15":15,"60":60,"240":240,"D":1440}

def build(sym,iv):
    c=pd.read_parquet(f"{B}/kline/{sym}-{iv}.parquet").sort_values("t").reset_index(drop=True)
    c["dt_utc"]=pd.to_datetime(c.t,unit="ms",utc=True)
    bm=BAR_MIN[iv]; bars_per_day=1440/bm
    # gap flag: the tape is NOT contiguous early on (thin listing days)
    c["gap_bars"]=(c.t.diff()/ (bm*60000)).fillna(1).round().astype(int)-1
    lc=np.log(c.c.values)
    c["ret_bps"]=np.concatenate([[np.nan],np.diff(lc)])*1e4
    mu=np.nanmean(c.ret_bps); c["retdd_bps"]=c.ret_bps-mu; c["drift_bps_per_bar"]=mu
    for k in (5,15,60,240,1440):
        n=max(int(round(k/bm)),1)
        c[f"ret_{k}m_bps"]=(pd.Series(lc).diff(n)*1e4).values
    for k in (60,1440,10080):
        n=max(int(round(k/bm)),3)
        c[f"rv_{k}m_bps"]=pd.Series(c.ret_bps).rolling(n,min_periods=n//2).std().values
    c["parkinson_bps"]=np.log(c.h/c.l)/(2*np.sqrt(np.log(2)))*1e4
    c["hl_range_bps"]=(c.h/c.l-1)*1e4
    c["co_bps"]=(c.c/c.o-1)*1e4
    c["vol_usd"]=c.turnover
    wv=max(int(bars_per_day),20)          # at iv=D bars_per_day==1; a 1-bar window is meaningless
    c["dvol_z"]=(c.vol_usd-c.vol_usd.rolling(wv,min_periods=max(2,wv//3)).mean())/ \
                 c.vol_usd.rolling(wv,min_periods=max(2,wv//3)).std()
    c["hour_utc"]=c.dt_utc.dt.hour.astype("int8"); c["dow"]=c.dt_utc.dt.dayofweek.astype("int8")
    c["day"]=c.dt_utc.dt.strftime("%Y-%m-%d"); c["month"]=c.dt_utc.dt.strftime("%Y-%m")
    for k in (5,60,1440):
        n=max(int(round(k/bm)),1)
        c[f"fwd_{k}m_bps"]=(pd.Series(lc).shift(-n)-pd.Series(lc)).values*1e4
        c[f"fwd_{k}m_dd_bps"]=c[f"fwd_{k}m_bps"]-mu*n
    fp=f"{B}/funding/{sym}.parquet"
    if os.path.exists(fp):
        f=pd.read_parquet(fp).sort_values("time")
        c["funding_rate_last"]=pd.merge_asof(c[["t"]],f.rename(columns={"time":"t"}),on="t",direction="backward").fundingRate.values
    op=f"{B}/oi/{sym}-1h.parquet"
    if os.path.exists(op):
        o=pd.read_parquet(op).sort_values("time")
        c["oi_last"]=pd.merge_asof(c[["t"]],o.rename(columns={"time":"t"}),on="t",direction="backward").openInterest.values
        c["doi_1d_pct"]=c.oi_last.pct_change(max(int(bars_per_day),1))*100
    os.makedirs(OUT,exist_ok=True)
    p=f"{OUT}/bybit_{sym}_{iv}.parquet"; c.to_parquet(p,compression="zstd",index=False)
    return p,c,mu

if __name__=="__main__":
    ap=argparse.ArgumentParser(); ap.add_argument("--sym",default="HYPEUSDT"); ap.add_argument("--ivs",default="1,5,60,D")
    a=ap.parse_args()
    for iv in a.ivs.split(","):
        try: p,c,mu=build(a.sym,iv)
        except FileNotFoundError: print(f"{a.sym} {iv}: not backfilled yet"); continue
        print(f"{a.sym} {iv:>3s} -> {os.path.basename(p)}  rows {len(c):,}  cols {len(c.columns)}  "
              f"{c.dt_utc.min():%Y-%m-%d} -> {c.dt_utc.max():%Y-%m-%d}")
        exp=int((c.t.iloc[-1]-c.t.iloc[0])/(BAR_MIN[iv]*60000))+1
        print(f"      completeness {100*len(c)/exp:.1f}%  missing bars {exp-len(c):,}  "
              f"(thin tape at listing; `gap_bars` flags each hole)")
        print(f"      drift {mu:+.3f} bps/bar = {mu*(525600/BAR_MIN[iv])/1e4*100:+.0f} %/yr  "
              f"ann vol {c.ret_bps.std()/1e4*np.sqrt(525600/BAR_MIN[iv])*100:.0f}%")
