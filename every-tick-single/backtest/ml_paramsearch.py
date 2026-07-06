#!/usr/bin/env python3
"""Indicator + parameter + timeframe search. Sweeps many indicators across
lookback periods (period P bars = P*5min timeframe), scores each as a single
feature by walk-forward next-bar AUC. Ranks all; then combines the top-K.
NOTE: periods are in 5m BARS (sma50 = 50 bars = ~4h, not 50 days).
Usage: python3 ml_paramsearch.py <binance_dir> [offset=1]
"""
import json, os, sys, math
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import roc_auc_score

def series(bdir):
    S={}
    for c in ("btc","eth","sol","xrp"):
        rows=json.load(open(os.path.join(bdir,f"{c}_5m.json")))
        S[c]=(np.array([r[1] for r in rows]),np.array([r[2] for r in rows]),
              np.array([r[3] for r in rows]),np.array([r[4] for r in rows]),
              np.array([r[5] for r in rows]))
    return S

def sma(a,k): 
    out=np.full(len(a),np.nan)
    cs=np.cumsum(np.insert(a,0,0))
    out[k-1:]=(cs[k:]-cs[:-k])/k
    return out
def ema(a,k):
    al=2/(k+1);e=np.empty(len(a));e[0]=a[0]
    for i in range(1,len(a)): e[i]=al*a[i]+(1-al)*e[i-1]
    return e
def rsi(c,k):
    d=np.diff(c,prepend=c[0]);g=np.where(d>0,d,0);l=np.where(d<0,-d,0)
    ag=sma(g,k);al=sma(l,k);rs=ag/np.where(al==0,1e-9,al)
    return 100-100/(1+rs)
def pctb(c,k):
    m=sma(c,k);sd=np.array([c[max(0,i-k+1):i+1].std() or 1e-9 for i in range(len(c))])
    return (c-(m-2*sd))/(4*sd)
def stoch(h,l,c,k):
    out=np.full(len(c),0.5)
    for i in range(k,len(c)):
        lo=l[i-k+1:i+1].min();hi=h[i-k+1:i+1].max();out[i]=(c[i]-lo)/(hi-lo) if hi>lo else .5
    return out

# indicator builders: name -> fn(o,h,l,c,v,P) -> feature array (value at bar i uses <= i)
INDS={
 "smaDist": lambda o,h,l,c,v,P:(c/sma(c,P)-1)*100,
 "emaDist": lambda o,h,l,c,v,P:(c/ema(c,P)-1)*100,
 "rsi":     lambda o,h,l,c,v,P:rsi(c,P)/100,
 "pctB":    lambda o,h,l,c,v,P:pctb(c,P),
 "roc":     lambda o,h,l,c,v,P:np.concatenate([np.zeros(P),(c[P:]/c[:-P]-1)*100]),
 "stoch":   lambda o,h,l,c,v,P:stoch(h,l,c,P),
 "cumret":  lambda o,h,l,c,v,P:np.concatenate([np.zeros(P),(c[P:]/c[:-P]-1)*100]),  # ~roc
}
PERIODS=[3,5,10,20,50,100,200]

def col(S,fn,P,N):
    X=[];y=[]
    for c,(o,h,l,cl,v) in S.items():
        f=fn(o,h,l,cl,v,P)
        for i in range(210,len(cl)-N):
            if np.isfinite(f[i-1]):
                X.append(f[i-1]);tb=i-1+N;y.append(1 if cl[tb]>=o[tb] else 0)
    return np.array(X).reshape(-1,1),np.array(y)

def auc1(X,y):
    cut=int(len(y)*.7);sc=StandardScaler().fit(X[:cut])
    m=LogisticRegression(max_iter=500).fit(sc.transform(X[:cut]),y[:cut])
    return roc_auc_score(y[cut:],m.predict_proba(sc.transform(X[cut:]))[:,1])

def main():
    bdir=sys.argv[1];N=int(sys.argv[2]) if len(sys.argv)>2 else 1
    S=series(bdir)
    res=[]
    for nm,fn in INDS.items():
        for P in PERIODS:
            try:
                X,y=col(S,fn,P,N);res.append((auc1(X,y),f"{nm}({P})"))
            except Exception: pass
    res.sort(reverse=True)
    print(f"offset +{N} — single-indicator test AUC, ranked (period = 5m bars):")
    for a,nm in res[:18]: print(f"  {nm:14} {a:.4f}")
    print(f"  ... worst: {res[-1][1]} {res[-1][0]:.4f}")

if __name__=="__main__": main()
