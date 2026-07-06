#!/usr/bin/env python3
"""Feature ablation on next-bar forecast: single-feature AUC, leave-one-out, and
forward greedy selection. Logistic (no overfit on 13 feats / 50k samples),
time-split. Shows which features move the test AUC.
Usage: python3 ml_ablation.py <binance_dir> [offset=1]
"""
import json, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ml_predict5 import feats
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import roc_auc_score

NAMES=["rsi","pctB","macd","stoch","atr","roc6","sma20d","sma50d","volz","takerflow","streak","body","intrabar_ret"]

def load(bdir,N):
    X=[];y=[]
    for c in ("btc","eth","sol","xrp"):
        rows=json.load(open(os.path.join(bdir,f"{c}_5m.json")));F,idx=feats(rows)
        for k,i in enumerate(idx):
            if i+N<len(rows): X.append(F[k]);tb=rows[i-1+N];y.append(1 if tb[4]>=tb[1] else 0)
    return np.array(X),np.array(y)

def auc(X,y,cols):
    cut=int(len(y)*.7);Xc=X[:,cols]
    sc=StandardScaler().fit(Xc[:cut])
    m=LogisticRegression(max_iter=1000,C=0.5).fit(sc.transform(Xc[:cut]),y[:cut])
    return roc_auc_score(y[cut:],m.predict_proba(sc.transform(Xc[cut:]))[:,1])

def main():
    bdir=sys.argv[1];N=int(sys.argv[2]) if len(sys.argv)>2 else 1
    X,y=load(bdir,N)
    full=auc(X,y,list(range(len(NAMES))))
    print(f"offset +{N}, {len(y)} samples. FULL-set test AUC = {full:.4f}\n")
    print("SINGLE feature (alone):")
    singles=sorted(((auc(X,y,[i]),NAMES[i]) for i in range(len(NAMES))),reverse=True)
    for a,nm in singles: print(f"  {nm:12} {a:.4f}")
    print("\nLEAVE-ONE-OUT (full minus feature -> AUC; lower delta = feature helped more):")
    loo=sorted(((full-auc(X,y,[j for j in range(len(NAMES)) if j!=i]),NAMES[i]) for i in range(len(NAMES))),reverse=True)
    for delta,nm in loo: print(f"  drop {nm:12} delta {delta:+.4f}")
    print("\nFORWARD greedy selection:")
    chosen=[];rem=list(range(len(NAMES)))
    for _ in range(6):
        best=None
        for i in rem:
            a=auc(X,y,chosen+[i])
            if best is None or a>best[0]: best=(a,i)
        chosen.append(best[1]);rem.remove(best[1])
        print(f"  + {NAMES[best[1]]:12} -> {best[0]:.4f}")

if __name__=="__main__": main()
