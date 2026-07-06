#!/usr/bin/env python3
"""Predict the outcome of the bar at offset +N (N=1..5), not just the next bar.
Maybe a farther-out individual 5m bar carries more structure (oscillation:
+1 reverts, +2 reverts the reversion, ...). Target = sign(close - open) of the
bar N ahead; features = last 12 bars' returns + RSI + %B (known now). Walk-
forward 70/30 on the 62-day set. Also reports the best directional bet's win
rate per N (tradeable since those markets exist pre-open).
Usage: python3 ml_offset.py <binance_dir>
"""
import json, math, os, sys


def feats(rows, i):
    o=[r[1] for r in rows]; c=[r[4] for r in rows]
    f=[]
    for j in range(i-12, i):
        f.append(math.log(c[j]/o[j])*100 if o[j]>0 and c[j]>0 else 0)
    # RSI14 + %B20 at i-1
    p=i-1; k=14
    g=l=0.0
    for j in range(p-k+1, p+1):
        d=c[j]-c[j-1]; g+=max(d,0); l+=max(-d,0)
    rsi=100 if l==0 else 100-100/(1+(g/k)/(l/k))
    m=sum(c[p-19:p+1])/20; sd=(sum((c[j]-m)**2 for j in range(p-19,p+1))/20)**.5 or 1e-9
    pctb=(c[p]-(m-2*sd))/(4*sd)
    return f+[rsi/100, pctb]


def main():
    bdir=sys.argv[1]
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    from sklearn.metrics import roc_auc_score
    from sklearn.ensemble import GradientBoostingClassifier
    print(f"{'offset':>7} {'logreg AUC':>11} {'gbm AUC':>9} {'Brier':>7} {'up-rate':>8} {'best-bet win%':>13}")
    for N in (1,2,3,4,5):
        X=[]; y=[]
        for c in ("btc","eth","sol","xrp"):
            rows=json.load(open(os.path.join(bdir,f"{c}_5m.json")))
            for i in range(20, len(rows)-N):
                X.append(feats(rows,i))
                tb=rows[i-1+N]  # bar N ahead of the last-closed bar
                y.append(1 if tb[4]>=tb[1] else 0)
        X=np.array(X,float); y=np.array(y); cut=int(len(y)*0.7)
        sc=StandardScaler().fit(X[:cut]); Xtr,Xte=sc.transform(X[:cut]),sc.transform(X[cut:])
        ytr,yte=y[:cut],y[cut:]
        lr=LogisticRegression(max_iter=1000).fit(Xtr,ytr)
        gb=GradientBoostingClassifier(n_estimators=80,max_depth=3,learning_rate=0.05).fit(Xtr,ytr)
        pl=np.clip(lr.predict_proba(Xte)[:,1],1e-6,1-1e-6)
        pg=np.clip(gb.predict_proba(Xte)[:,1],1e-6,1-1e-6)
        # best directional bet: follow gbm's pick, win rate
        pick=(pg>=0.5); win=(pick==(yte==1)).mean()
        print(f"{('+'+str(N)):>7} {roc_auc_score(yte,pl):>11.4f} {roc_auc_score(yte,pg):>9.4f} {np.mean((pg-yte)**2):>7.4f} {yte.mean():>8.3f} {win*100:>12.1f}%")


if __name__=="__main__":
    main()
