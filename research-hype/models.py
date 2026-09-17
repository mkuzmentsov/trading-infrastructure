#!/usr/bin/env python3
"""
/Users/maxkuzmentsov/development/projects/my/hummingbot/hummingbot-infra/research-hype/models.py

DIRECTIONAL CONTROL on the HYPE tick panel. Expected to fail; run honestly anyway.

Design (all of it non-negotiable per the program's methodology):
  * Split by DAY, forward in time, expanding window. Never random rows -- the
    1-second grid makes ~60 consecutive rows near-duplicates of one another.
  * Effective n is the number of NON-OVERLAPPING horizons, not the row count.
    With h=60s on a 1s grid, 360k rows carry ~6.0k independent observations.
  * Every score is printed beside TWO placebos through the identical pipeline:
      - label shuffle (targets permuted within day, features untouched)
      - side flip    (sign of the target flipped)
  * Headline is NET BPS against the real fee, never AUC.
  * Config count is tracked and the best result is deflated for selection.

Usage: python3 models.py [--horizons 60,300] [--panel <path>]
"""
import argparse, itertools, json, os, sys
import numpy as np, pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.preprocessing import StandardScaler

PANEL="/Users/maxkuzmentsov/development/projects/my/hummingbot/hummingbot-infra/every-tick-single/data/hl-hist/panel/tick_hype_1s.parquet"
TK=4.50            # taker bps per side  (venue agent, measured on our userFees)
RT=2*TK            # taker round trip

DROP_PREFIX=("fwd","ts","dt_utc","day","entry_","bid","ask","mid","microprice",
             "mark","oracle","oi_hype","oi_usd","dayNtlVlm","stale","l2_stale","ctx_stale")
def featcols(df):
    return [c for c in df.columns
            if not c.startswith(DROP_PREFIX) and df[c].dtype.kind=="f" and df[c].notna().any()]

def walk_forward(df, feats, y, groups, model="gb", min_train_days=2):
    """Expanding-window, day-forward. Returns OOS prob vector (nan before first test day)."""
    days=sorted(df.day.unique()); p=np.full(len(df), np.nan)
    for i in range(min_train_days, len(days)):
        tr=df.day.isin(days[:i]).values; te=(df.day==days[i]).values
        Xtr,ytr=df.loc[tr,feats].values, y[tr]
        Xte=df.loc[te,feats].values
        if len(np.unique(ytr))<2: continue
        if model=="gb":
            m=HistGradientBoostingClassifier(max_iter=150,max_depth=4,learning_rate=0.06,
                                             l2_regularization=1.0,min_samples_leaf=200,
                                             random_state=0)
            m.fit(Xtr,ytr); p[te]=m.predict_proba(Xte)[:,1]
        else:
            sc=StandardScaler().fit(np.nan_to_num(Xtr))
            m=LogisticRegression(max_iter=400,C=0.1)
            m.fit(sc.transform(np.nan_to_num(Xtr)),ytr)
            p[te]=m.predict_proba(sc.transform(np.nan_to_num(Xte)))[:,1]
    return p

def economics(df,h,p,thr):
    """Trade when the model is confident; charge the real fee. Non-overlapping only."""
    ok=~np.isnan(p)
    lg=df[f"fwd{h}s_long_gross_bps"].values; sh=df[f"fwd{h}s_short_gross_bps"].values
    ok&=~np.isnan(lg)&~np.isnan(sh)
    sig=np.where(p>=1-thr,1,np.where(p<=thr,-1,0)); sig=np.where(ok,sig,0)
    # enforce non-overlap: once we trade at i, block the next h seconds
    idx=np.flatnonzero(sig!=0); taken=[]; last=-10**9
    for i in idx:
        if i-last>=h: taken.append(i); last=i
    taken=np.array(taken,dtype=int)
    if len(taken)==0: return 0,np.nan,np.nan,np.nan
    g=np.where(sig[taken]>0, lg[taken], sh[taken])
    net=g-RT
    days=df.day.values[taken]
    # day-clustered SE
    dm=pd.Series(net).groupby(pd.Series(days)).mean()
    se=dm.std(ddof=1)/np.sqrt(len(dm)) if len(dm)>1 else np.nan
    return len(taken), net.mean(), se, (net.mean()/se if se and se>0 else np.nan)

def run(panel, horizons, thr_list, models):
    df=pd.read_parquet(panel)
    df=df[df.stale_ms<2000].reset_index(drop=True)
    feats=featcols(df)
    print(f"panel {os.path.basename(panel)}  rows {len(df):,}  feats {len(feats)}  days {df.day.nunique()}")
    print(f"NOTE effective n per horizon = rows/h (non-overlapping):",
          {h:int(len(df)/h) for h in horizons})
    rng=np.random.default_rng(7); cfgs=0; results=[]
    for h,mdl in itertools.product(horizons,models):
        base=df[f"fwd{h}s_mid_bps"].values
        m=~np.isnan(base); sub=df[m].reset_index(drop=True); b=base[m]
        y=(b>0).astype(int)
        variants={"REAL":y,
                  "PLACEBO-shuffle":pd.Series(y).groupby(sub.day).transform(
                      lambda s: rng.permutation(s.values)).values,
                  "PLACEBO-flip":1-y}
        for name,yy in variants.items():
            p=walk_forward(sub,feats,yy,sub.day.values,model=mdl)
            ok=~np.isnan(p)
            auc=roc_auc_score(yy[ok],p[ok]) if ok.sum()>100 and len(np.unique(yy[ok]))>1 else np.nan
            for thr in thr_list:
                cfgs+=1
                n,mu,se,t=economics(sub,h,p if name!="PLACEBO-flip" else 1-p,thr)
                results.append(dict(h=h,model=mdl,variant=name,thr=thr,auc=auc,
                                    n=n,net_bps=mu,se=se,t=t))
                print(f"  h={h:4d}s {mdl:4s} {name:16s} thr={thr:.2f} AUC={auc:.4f} "
                      f"n={n:5d} net={mu:+7.3f} bps  SE(day)={se if se==se else float('nan'):6.3f}  t={t:+5.2f}",flush=True)
    R=pd.DataFrame(results)
    print(f"\nCONFIGS TRIED: {cfgs}")
    real=R[R.variant=="REAL"].dropna(subset=["t"])
    if len(real):
        best=real.loc[real.t.idxmax()]
        from math import erfc,sqrt
        p_raw=0.5*erfc(best.t/sqrt(2))
        print(f"BEST REAL cell: h={best.h}s {best.model} thr={best.thr} net={best.net_bps:+.3f} bps t={best.t:+.2f}")
        print(f"  raw one-sided p={p_raw:.4f}   Bonferroni over {cfgs} cells -> p={min(1,p_raw*cfgs):.3f}")
        pl=R[R.variant!="REAL"].dropna(subset=["t"])
        if len(pl):
            print(f"  PLACEBO best t in the SAME pipeline: {pl.t.max():+.2f}  (n placebo cells {len(pl)})")
            print("  -> a real result must beat its own placebo, not zero.")
    R.to_csv("/Users/maxkuzmentsov/development/projects/my/hummingbot/hummingbot-infra/research-hype/models_results.csv",index=False)
    return R

if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--panel",default=PANEL)
    ap.add_argument("--horizons",default="60,300")
    ap.add_argument("--thr",default="0.50,0.40,0.30")
    ap.add_argument("--models",default="gb,lr")
    a=ap.parse_args()
    run(a.panel,[int(x) for x in a.horizons.split(",")],
        [float(x) for x in a.thr.split(",")], a.models.split(","))
