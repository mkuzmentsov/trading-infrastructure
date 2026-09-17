#!/usr/bin/env python3
"""/Users/maxkuzmentsov/development/projects/my/hummingbot/hummingbot-infra/research-hype/latencytell.py
THE LATENCY TELL (PM bug #32). Degrade execution: an honest edge DECAYS, a
hindsight bug IMPROVES. Reports GROSS bps too, so the verdict isn't masked by
the fee swamping everything."""
import numpy as np, pandas as pd, sys
sys.path.insert(0,"/Users/maxkuzmentsov/development/projects/my/hummingbot/hummingbot-infra/research-hype")
from models import walk_forward, featcols
from sklearn.metrics import roc_auc_score
P="/Users/maxkuzmentsov/development/projects/my/hummingbot/hummingbot-infra/every-tick-single/data/hl-hist/panel"
TK=4.50
print(f"{'lag':>7s} {'AUC':>7s} {'gross bps/trade':>16s} {'net bps/trade':>14s} {'n':>6s}  (h=60s, LR, thr=0.40)")
for tag,lag in [("tick_hype_1s",0),("tick_hype_1s_lag500ms",500),("tick_hype_1s_lag2000ms",2000)]:
    df=pd.read_parquet(f"{P}/{tag}.parquet"); df=df[df.stale_ms<2000].reset_index(drop=True)
    feats=featcols(df); h=60
    b=df[f"fwd{h}s_mid_bps"].values; m=~np.isnan(b); sub=df[m].reset_index(drop=True)
    y=(b[m]>0).astype(int)
    p=walk_forward(sub,feats,y,sub.day.values,model="lr")
    ok=~np.isnan(p); auc=roc_auc_score(y[ok],p[ok])
    lg=sub[f"fwd{h}s_long_gross_bps"].values; sh=sub[f"fwd{h}s_short_gross_bps"].values
    thr=0.40; sig=np.where(p>=1-thr,1,np.where(p<=thr,-1,0)); sig=np.where(ok&~np.isnan(lg),sig,0)
    idx=np.flatnonzero(sig!=0); taken=[]; last=-10**9
    for i in idx:
        if i-last>=h: taken.append(i); last=i
    taken=np.array(taken,int)
    g=np.where(sig[taken]>0,lg[taken],sh[taken])
    print(f"{lag:6d}ms {auc:7.4f} {g.mean():16.3f} {g.mean()-2*TK:14.3f} {len(taken):6d}")
print("""
VERDICT RULE: gross bps must FALL as lag rises. If it rises, the signal is
reading the future and the result must be retracted, not shipped.""")
