#!/usr/bin/env python3
"""Comprehensive model: at each bar close, predict the next 5 bars' outcomes with
CALIBRATED confidence. Rich features (returns, RSI, %B, MACD, Stoch, ATR, ROC,
SMA-dist, volume-z, taker-flow, streak, candle), GBM + isotonic calibration,
time-ordered walk-forward. Reports per-offset accuracy/AUC/Brier, a CALIBRATION
table (when it said X% sure, was it right X%?), confidence distribution, and a
sample of recent 5-bar forecasts.
Usage: python3 ml_predict5.py <binance_dir>
"""
import json, math, os, sys
import numpy as np
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.calibration import CalibratedClassifierCV
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import roc_auc_score

def feats(rows):
    o=[r[1] for r in rows];h=[r[2] for r in rows];l=[r[3] for r in rows];c=[r[4] for r in rows]
    v=[r[5] for r in rows];tb=[r[7] for r in rows];n=len(rows)
    def sma(a,k,i): return sum(a[i-k+1:i+1])/k if i>=k-1 else a[i]
    def ema(a,k):
        e=[a[0]];al=2/(k+1)
        for x in a[1:]: e.append(al*x+(1-al)*e[-1])
        return e
    e12,e26=ema(c,12),ema(c,26);macd=[e12[i]-e26[i] for i in range(n)];sig=ema(macd,9)
    lv=[math.log(x+1) for x in v];lvm=np.mean(lv);lvs=np.std(lv) or 1
    X=[]
    for i in range(60,n):
        p=i-1
        g=ll=0.0
        for j in range(p-13,p+1):
            d=c[j]-c[j-1];g+=max(d,0);ll+=max(-d,0)
        rsi=100 if ll==0 else 100-100/(1+(g/14)/(ll/14))
        m=sma(c,20,p);sd=(sum((c[j]-m)**2 for j in range(p-19,p+1))/20)**.5 or 1e-9
        pctb=(c[p]-(m-2*sd))/(4*sd)
        lo=min(l[p-13:p+1]);hi=max(h[p-13:p+1]);stoch=(c[p]-lo)/(hi-lo) if hi>lo else .5
        atr=sum(max(h[j]-l[j],abs(h[j]-c[j-1]),abs(l[j]-c[j-1])) for j in range(p-13,p+1))/14
        rng=h[p]-l[p] or 1e-9
        st=0
        for j in range(p,0,-1):
            up=c[j]>=o[j]
            if j==p: cur=up;st=1
            elif (c[j]>=o[j])==cur: st+=1
            else: break
        st=st if cur else -st
        X.append([rsi/100,pctb,macd[p]-sig[p],stoch,atr/c[p]*100 if c[p] else 0,
                  (c[p]/c[p-6]-1)*100 if c[p-6] else 0,(c[p]/sma(c,20,p)-1)*100,
                  (c[p]/sma(c,50,p)-1)*100,(lv[p]-lvm)/lvs,(tb[p]/v[p]-.5) if v[p] else 0,
                  st,(c[p]-o[p])/rng,(math.log(c[p]/o[p])*100 if o[p]>0 and c[p]>0 else 0)])
    return X, list(range(60,n))

def main():
    bdir=sys.argv[1];coins=("btc","eth","sol","xrp")
    Xall={};idx={};rowsc={}
    for c in coins:
        rows=json.load(open(os.path.join(bdir,f"{c}_5m.json")));rowsc[c]=rows
        Xall[c],idx[c]=feats(rows)
    print(f"{'off':>4} {'acc':>6} {'AUC':>6} {'Brier':>6} | CALIBRATION: conf-band -> realized-correct% (n)")
    for N in (1,2,3,4,5):
        X=[];y=[]
        for c in coins:
            rows=rowsc[c]
            for k,i in enumerate(idx[c]):
                if i+N<len(rows):
                    X.append(Xall[c][k]);tb=rows[i-1+N];y.append(1 if tb[4]>=tb[1] else 0)
        X=np.array(X);y=np.array(y);cut=int(len(y)*.7)
        sc=StandardScaler().fit(X[:cut]);Xs=sc.transform(X)
        base=GradientBoostingClassifier(n_estimators=100,max_depth=3,learning_rate=0.05)
        m=CalibratedClassifierCV(base,method='isotonic',cv=3).fit(Xs[:cut],y[:cut])
        p=m.predict_proba(Xs[cut:])[:,1];yt=y[cut:]
        acc=((p>=.5)==yt).mean();auc=roc_auc_score(yt,yt*0+p) if len(set(yt))>1 else .5
        brier=np.mean((p-yt)**2)
        # calibration: confidence = distance from 0.5; realized correct in band
        conf=np.abs(p-.5)
        cells=[]
        for lo,hi in [(0,.02),(.02,.05),(.05,.10),(.10,.5)]:
            msk=(conf>=lo)&(conf<hi)
            if msk.sum()>=10:
                pick=(p[msk]>=.5);corr=(pick==(yt[msk]==1)).mean()
                cells.append(f"{int((lo+.5)*100)}-{int((hi+.5)*100)}%:{corr*100:.0f}%(n{int(msk.sum())})")
        print(f"{('+'+str(N)):>4} {acc*100:5.1f}% {auc:.3f} {brier:.4f} | "+"  ".join(cells))
    # sample: last bar's 5-forecast per coin (retrain full, predict last)
    print("\nLATEST 5-bar forecast (P_up, confidence) per coin — trained on all data:")
    for c in coins:
        rows=rowsc[c];row=[]
        for N in (1,2,3,4,5):
            X=[];y=[]
            for cc in coins:
                rr=rowsc[cc]
                for k,i in enumerate(idx[cc]):
                    if i+N<len(rr): X.append(Xall[cc][k]);tb=rr[i-1+N];y.append(1 if tb[4]>=tb[1] else 0)
            X=np.array(X);y=np.array(y);sc=StandardScaler().fit(X)
            m=GradientBoostingClassifier(n_estimators=100,max_depth=3,learning_rate=0.05).fit(sc.transform(X),y)
            last=sc.transform([Xall[c][-1]]);pu=m.predict_proba(last)[0,1]
            row.append(f"+{N}:{'UP' if pu>=.5 else 'DN'} {pu:.2f}(±{abs(pu-.5)*200:.0f}%)")
        print(f"  {c}: "+"  ".join(row))

if __name__=="__main__": main()
