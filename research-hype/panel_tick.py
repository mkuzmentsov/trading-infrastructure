#!/usr/bin/env python3
"""
/Users/maxkuzmentsov/development/projects/my/hummingbot/hummingbot-infra/research-hype/panel_tick.py

TICK PANEL — one row per decision instant on the HL native HYPE tape.

OUT: every-tick-single/data/hl-hist/panel/tick_hype_<step>s.parquet

LEAKAGE CONTRACT (the whole point of this file):
  * Every feature at instant tau uses ONLY rows whose RECORDER RECEIVE time
    (`t`, epoch seconds) is <= tau.  We never use the exchange `time` field to
    gate, because the recorder sees an event ~368 ms (p50) after the exchange
    stamps it.  Gating on exchange time would hand the model 368 ms of future.
    This is the same bug class as PM bug #25/#43 (Chainlink future ticks).
  * `stale_ms` is published for every row.  Rows where the freshest quote is
    older than the step are NOT silently forward-filled -- filter on stale_ms.
  * Targets look FORWARD from tau and are computed from the first observation
    at recv >= tau + h.  Because entry would also be delayed, an execution-lag
    knob (`--lag-ms`) shifts the ENTRY reference forward: this is the handle for
    the latency tell (degrade lag, results must get WORSE).

ECONOMICS (from the venue agent, measured on our own userFees):
  taker 4.50 bps, maker 1.50 bps (a FEE, not a rebate), no staking/referral
  discount.  Round trips: taker/taker 9.00, mixed 6.00, maker/maker 3.00 bps.
  Spread is 0.13 bps median.  Every target is therefore ALSO published net of
  the taker round trip so nothing is ever judged on gross bps.
"""
import argparse, glob, os, datetime as dt
import numpy as np, pandas as pd, pyarrow as pa, pyarrow.parquet as pq

TAPE="/Users/maxkuzmentsov/development/projects/my/hummingbot/hummingbot-infra/every-tick-single/data/pq-venue/hl"
OUT ="/Users/maxkuzmentsov/development/projects/my/hummingbot/hummingbot-infra/every-tick-single/data/hl-hist/panel"
FEE_TAKER_BPS=4.50; FEE_MAKER_BPS=1.50
TRADE_WINS=[1,5,30,300]         # seconds
VOL_WINS  =[10,60,300,1800]     # seconds
HORIZONS  =[1,5,30,60,300]      # seconds

def load(stream, coin, cols=None):
    fs=sorted(glob.glob(f"{TAPE}/{stream}/{coin}-*.parquet"))
    if not fs: raise SystemExit(f"no files for {stream}/{coin}")
    d=pd.concat([pd.read_parquet(f,columns=cols) for f in fs],ignore_index=True)
    d["recv"]=(d["t"]*1000).round().astype("int64")
    return d.sort_values("recv",kind="mergesort").reset_index(drop=True)

def asof_idx(src_recv, grid):
    """index of last src row with recv <= tau (-1 if none)."""
    return np.searchsorted(src_recv, grid, side="right")-1

def build(coin, step_s, lag_ms):
    b=load("bbo",coin); l2=load("l2Book",coin); ac=load("activeAssetCtx",coin)
    tr=load("trades",coin).drop_duplicates(subset=["time","side","px","sz","hash"])

    t0=int(np.ceil(b.recv.iloc[0]/1000.)*1000); t1=int(np.floor(b.recv.iloc[-1]/1000.)*1000)
    grid=np.arange(t0, t1+1, step_s*1000, dtype="int64")
    P={"ts":grid}
    P["dt_utc"]=pd.to_datetime(grid,unit="ms",utc=True)
    P["day"]=np.array([d.strftime("%Y-%m-%d") for d in P["dt_utc"]])
    P["hour_utc"]=P["dt_utc"].hour.values.astype("int8")

    # ---- book (bbo) -------------------------------------------------------
    br=b.recv.values; i=asof_idx(br, grid); ok=i>=0
    i=np.clip(i,0,None)
    bid=b.bid.values[i]; ask=b.ask.values[i]; bsz=b.bidsz.values[i]; asz=b.asksz.values[i]
    P["stale_ms"]=np.where(ok, grid-br[i], -1).astype("int64")
    mid=(bid+ask)/2.0
    P["bid"],P["ask"],P["mid"]=bid,ask,mid
    P["spread_bps"]=(ask-bid)/mid*1e4
    P["microprice"]=(bid*asz+ask*bsz)/(bsz+asz)
    P["micro_dev_bps"]=(P["microprice"]-mid)/mid*1e4      # microprice tilt vs mid
    P["touch_bidsz"],P["touch_asksz"]=bsz,asz
    P["touch_imb"]=(bsz-asz)/(bsz+asz)
    P["touch_ntl_usd"]=(bsz*bid+asz*ask)

    # ---- ladder (l2Book) --------------------------------------------------
    lr=l2.recv.values; j=asof_idx(lr, grid); okj=j>=0; j=np.clip(j,0,None)
    P["l2_stale_ms"]=np.where(okj, grid-lr[j], -1).astype("int64")
    for N in (1,3,5,10):
        bd=np.zeros(len(grid)); ad=np.zeros(len(grid))
        for k in range(N):
            bd+=np.nan_to_num(l2[f"bs{k}"].values[j]*l2[f"bp{k}"].values[j])
            ad+=np.nan_to_num(l2[f"as{k}"].values[j]*l2[f"ap{k}"].values[j])
        P[f"depth{N}_bid_usd"]=bd; P[f"depth{N}_ask_usd"]=ad
        P[f"imb{N}"]=(bd-ad)/np.where(bd+ad>0,bd+ad,np.nan)
    # book slope: usd per bps of distance from mid, levels 0..9
    for side,pfx in (("bid","b"),("ask","a")):
        px=np.stack([l2[f"{pfx}p{k}"].values[j] for k in range(10)])
        sz=np.stack([l2[f"{pfx}s{k}"].values[j] for k in range(10)])
        dist=np.abs(px-mid)/mid*1e4
        num=np.nansum(sz*px,axis=0); den=np.nansum(dist*np.nan_to_num(sz*px),axis=0)
        P[f"{side}_slope_usd_per_bps"]=np.where(den>0, num**2/den, np.nan)
    P["n_orders_touch"]=np.nan_to_num(l2["bn0"].values[j])+np.nan_to_num(l2["an0"].values[j])

    # ---- trade flow -------------------------------------------------------
    trr=tr.recv.values
    sgn=np.where(tr.side.values=="B",1.0,-1.0)          # VALIDATED: B lifts the ask
    ntl=(tr.px.values*tr.sz.values)
    cum_n=np.concatenate([[0],np.cumsum(ntl)])
    cum_s=np.concatenate([[0],np.cumsum(ntl*sgn)])
    cum_c=np.arange(len(trr)+1,dtype="float64")
    cum_b=np.concatenate([[0],np.cumsum(sgn>0)])
    hi=np.searchsorted(trr,grid,side="right")
    for W in TRADE_WINS:
        lo=np.searchsorted(trr,grid-W*1000,side="right")
        v=cum_n[hi]-cum_n[lo]; s=cum_s[hi]-cum_s[lo]; c=cum_c[hi]-cum_c[lo]
        P[f"vol_{W}s_usd"]=v
        P[f"ofi_{W}s_usd"]=s                                    # signed taker notional
        P[f"ofi_{W}s_norm"]=np.where(v>0,s/v,0.0)               # -1..+1 aggressor mix
        P[f"ntrades_{W}s"]=c
        P[f"buyshare_{W}s"]=np.where(c>0,(cum_b[hi]-cum_b[lo])/np.where(c>0,c,1),0.5)
        P[f"avgtrade_{W}s_usd"]=np.where(c>0,v/np.where(c>0,c,1),0.0)
    # trade-sign autocorrelation, lag1, over trailing 300s (herfindahl-free)
    ss=np.concatenate([[0],np.cumsum(sgn)]); s2=np.concatenate([[0],np.cumsum(sgn*sgn)])
    prod=sgn[1:]*sgn[:-1]; sp=np.concatenate([[0],np.cumsum(prod)])
    lo=np.searchsorted(trr,grid-300*1000,side="right")
    n=(hi-lo).astype("float64")
    m=np.where(n>0,(ss[hi]-ss[lo])/np.where(n>0,n,1),0.0)
    var=np.where(n>1,(s2[hi]-s2[lo])/np.where(n>0,n,1)-m*m,np.nan)
    npair=np.clip(hi-1,0,None)-np.clip(lo-1,0,None)
    cov=np.where(npair>0,(sp[np.clip(hi-1,0,None)]-sp[np.clip(lo-1,0,None)])/np.where(npair>0,npair,1)-m*m,np.nan)
    P["tsign_ac1_300s"]=np.where(var>1e-9,cov/var,np.nan)

    # ---- perp context: funding / OI / mark-oracle -------------------------
    ar=ac.recv.values; k=asof_idx(ar,grid); okk=k>=0; k=np.clip(k,0,None)
    P["ctx_stale_ms"]=np.where(okk,grid-ar[k],-1).astype("int64")
    fund=ac.funding.values[k]; oi=ac.oi.values[k]
    mark=ac["mark"].values[k]; orac=ac["oracle"].values[k]; cmid=ac["mid"].values[k]
    P["funding_hr"]=fund
    P["funding_apr_pct"]=fund*24*365*100
    P["oi_hype"]=oi; P["oi_usd"]=oi*mark
    P["mark"],P["oracle"]=mark,orac
    P["mark_oracle_bps"]=(mark-orac)/orac*1e4        # the premium term that drives funding
    P["mid_oracle_bps"] =(mid-orac)/orac*1e4
    P["mark_mid_bps"]   =(mark-mid)/mid*1e4
    P["dayNtlVlm"]=ac["dayNtlVlm"].values[k]
    for W in (60,300,1800):
        kl=asof_idx(ar,grid-W*1000); good=kl>=0; kl=np.clip(kl,0,None)
        P[f"doi_{W}s_pct"]=np.where(good,(oi/ac.oi.values[kl]-1)*100,np.nan)
        P[f"dfund_{W}s"]  =np.where(good,fund-ac.funding.values[kl],np.nan)

    # ---- realised vol & past returns, from the grid mid itself ------------
    lm=np.log(mid); valid=P["stale_ms"]>=0
    for W in VOL_WINS:
        n=max(int(W/step_s),2)
        r=pd.Series(lm).diff()
        P[f"rv_{W}s_bps"]=(r.rolling(n,min_periods=max(2,n//2)).std()*1e4*np.sqrt(1)).values
    for W in (5,30,60,300,1800):
        n=int(W/step_s)
        P[f"ret_m{W}s_bps"]=(pd.Series(lm).diff(n)*1e4).values

    # ---- TARGETS (forward; entry reference shifted by lag_ms) -------------
    entry=grid+lag_ms
    ei=asof_idx(br,entry); ei_ok=ei>=0; ei=np.clip(ei,0,None)
    e_bid=b.bid.values[ei]; e_ask=b.ask.values[ei]; e_mid=(e_bid+e_ask)/2
    P["entry_lag_ms"]=lag_ms
    P["entry_mid"]=np.where(ei_ok,e_mid,np.nan)
    for h in HORIZONS:
        xi=np.searchsorted(br, entry+h*1000, side="left")     # first quote AT/AFTER
        good=xi<len(br); xi=np.clip(xi,0,len(br)-1)
        x_bid=b.bid.values[xi]; x_ask=b.ask.values[xi]; x_mid=(x_bid+x_ask)/2
        P[f"fwd{h}s_mid_bps"]=np.where(good,(x_mid/e_mid-1)*1e4,np.nan)
        # tradeable: buy the ask now, sell the bid later (and the mirror)
        P[f"fwd{h}s_long_gross_bps"] =np.where(good,(x_bid/e_ask-1)*1e4,np.nan)
        P[f"fwd{h}s_short_gross_bps"]=np.where(good,(e_bid/x_ask-1)*1e4,np.nan)
        P[f"fwd{h}s_long_net_bps"]   =P[f"fwd{h}s_long_gross_bps"] -2*FEE_TAKER_BPS
        P[f"fwd{h}s_short_net_bps"]  =P[f"fwd{h}s_short_gross_bps"]-2*FEE_TAKER_BPS
        # carry leg: funding accrued over the horizon if held (hourly rate)
        P[f"fwd{h}s_funding_bps"]=fund*(h/3600.0)*1e4

    df=pd.DataFrame(P)
    df=df[valid]                                     # drop pre-first-quote rows
    os.makedirs(OUT,exist_ok=True)
    tag=f"tick_{coin}_{step_s}s" + (f"_lag{lag_ms}ms" if lag_ms else "")
    p=f"{OUT}/{tag}.parquet"
    df.to_parquet(p,compression="zstd",index=False)
    return p, df

if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--coin",default="hype"); ap.add_argument("--step",type=int,default=1)
    ap.add_argument("--lag-ms",type=int,default=0)
    a=ap.parse_args()
    p,df=build(a.coin,a.step,a.lag_ms)
    print(f"wrote {p}")
    print(f"rows {len(df):,}  cols {len(df.columns)}  days {df.day.nunique()}  "
          f"{df.dt_utc.min()} -> {df.dt_utc.max()}")
    print(f"size {os.path.getsize(p)/1e6:.1f} MB")
    print(f"stale_ms p50={df.stale_ms.median():.0f} p99={df.stale_ms.quantile(.99):.0f} max={df.stale_ms.max():.0f}")
    print(df[["spread_bps","touch_imb","imb10","ofi_30s_norm","rv_60s_bps",
              "mark_oracle_bps","funding_apr_pct","fwd60s_mid_bps"]].describe().T.to_string())
