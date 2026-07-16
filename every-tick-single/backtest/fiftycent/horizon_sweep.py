#!/usr/bin/env python3
"""Directional OOS accuracy of the cur2 model at horizons cur+0..7.
Walk-forward daily retrain. Measures PREDICTION accuracy only (not fills)."""
import sys, numpy as np, pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier

FILES = {"btc":"data.csv","doge":"data_doge.csv","eth":"data_eth.csv",
         "sol":"data_sol.csv","xrp":"data_xrp.csv"}
HMAX = int(sys.argv[1]) if len(sys.argv)>1 else 7
ONLY = sys.argv[2].split(",") if len(sys.argv)>2 else list(FILES)

def feats(d):
    d["y"]=(d["close"]>=d["open"]).astype(int)
    d["clc"]=d["close"].pct_change()
    d["range"]=(d["high"]-d["low"])/d["open"]
    d["tbr"]=(d["takerBuyBase"]/d["volume"].replace(0,np.nan))-0.5
    d["dt"]=pd.to_datetime(d["openTime"],unit="ms");d["day"]=d["dt"].dt.floor("D");d["hour"]=d["dt"].dt.hour
    F={}
    for k in [1,2,3,6,12,24]:
        F[f"clc{k}"]=d["clc"].shift(k);F[f"y{k}"]=d["y"].shift(k)-0.5
    F["mom3"]=d["clc"].rolling(3).sum().shift(1);F["mom6"]=d["clc"].rolling(6).sum().shift(1)
    F["mom12"]=d["clc"].rolling(12).sum().shift(1)
    v=d["clc"].rolling(12).std().shift(1);F["vol12"]=v
    F["zmom6"]=d["clc"].rolling(6).sum().shift(1)/(v*np.sqrt(6));F["revert"]=-d["clc"].shift(1)/v
    F["rng6"]=d["range"].rolling(6).mean().shift(1)
    F["tbr1"]=d["tbr"].shift(1);F["tbr3"]=d["tbr"].rolling(3).mean().shift(1)
    F["volz"]=((d["volume"]-d["volume"].rolling(48).mean())/d["volume"].rolling(48).std()).shift(1)
    F["hsin"]=np.sin(2*np.pi*d["hour"]/24);F["hcos"]=np.cos(2*np.pi*d["hour"]/24)
    return pd.DataFrame(F,index=d.index)

def mk(): return HistGradientBoostingClassifier(max_depth=3,learning_rate=0.03,max_iter=200,
        l2_regularization=2.0,min_samples_leaf=100,random_state=0)

print(f"{'coin':>4} {'H':>3} {'OOSacc':>7} {'std':>5} {'z':>6} {'d>=55%':>7}  conv|p-.5|>.02")
for coin in ONLY:
    d=pd.read_csv(FILES[coin])
    for c in ["open","high","low","close","volume","takerBuyBase"]: d[c]=d[c].astype(float)
    X=feats(d);feat=list(X.columns)
    # subsample walk-forward every 3rd day to keep runtime sane; still OOS
    for H in range(0,HMAX+1):
        yH=d["y"].shift(-H)
        dd=pd.concat([X,yH.rename("t"),d["day"]],axis=1).dropna().reset_index(drop=True)
        days=sorted(dd["day"].unique())
        acc=[];conv_hit=[];conv_n=0
        for i in range(12,len(days),3):
            tr=dd[dd["day"]<days[i]];te=dd[dd["day"]==days[i]]
            if len(te)<50: continue
            m=mk().fit(tr[feat],tr["t"])
            p=m.predict_proba(te[feat])[:,1]
            pred=(p>=0.5).astype(int);tru=te["t"].values
            acc.append((pred==tru).mean())
            mask=np.abs(p-0.5)>0.02
            if mask.sum(): conv_hit.append((pred[mask]==tru[mask]).mean());conv_n+=mask.sum()
        a=np.array(acc);z=(a.mean()-0.5)/(a.std()/np.sqrt(len(a))) if len(a)>1 else 0
        cv=np.mean(conv_hit) if conv_hit else float("nan")
        print(f"{coin:>4} +{H:<2} {a.mean():>7.4f} {a.std():>5.3f} {z:>+6.2f} {(a>=0.55).sum():>3}/{len(a):<3} {cv:>6.3f} (n={conv_n})")
