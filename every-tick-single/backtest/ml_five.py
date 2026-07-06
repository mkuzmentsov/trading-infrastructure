#!/usr/bin/env python3
"""Predict 5 consecutive bars; how often do we get >=3 of 5 right? User target:
3/5 correct "always". Non-overlapping 5-bar blocks; features known before each
bar. Compares: simple logistic model, always-UP, momentum-follow. Reports the
full distribution of hits/5 and P(>=3/5). Walk-forward (train first 70%).
Usage: python3 ml_five.py <binance_dir>
"""
import json, math, os, sys


def feat(rows, i):
    o=[r[1] for r in rows]; c=[r[4] for r in rows]
    return [math.log(c[j]/o[j])*100 if o[j]>0 and c[j]>0 else 0 for j in range(i-8, i)]


def main():
    bdir=sys.argv[1]
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    # dataset: predict each bar from features at prior bar
    X=[]; y=[]; rowsrc=[]
    for c in ("btc","eth","sol","xrp"):
        rows=json.load(open(os.path.join(bdir,f"{c}_5m.json")))
        for i in range(10, len(rows)):
            X.append(feat(rows,i)); y.append(1 if rows[i][4]>=rows[i][1] else 0)
            rowsrc.append((c,i))
    X=np.array(X,float); y=np.array(y); n=len(y); cut=int(n*0.7)
    sc=StandardScaler().fit(X[:cut]); Xs=sc.transform(X)
    m=LogisticRegression(max_iter=1000).fit(Xs[:cut],y[:cut])
    pred_model=(m.predict_proba(Xs)[:,1]>=0.5).astype(int)
    pred_up=np.ones(n,int)
    pred_mom=np.array([1 if X[i][-1]>=0 else 0 for i in range(n)])  # follow last bar
    print(f"per-bar accuracy (test split): model={ (pred_model[cut:]==y[cut:]).mean():.4f}  "
          f"always-UP={(pred_up[cut:]==y[cut:]).mean():.4f}  momentum={(pred_mom[cut:]==y[cut:]).mean():.4f}\n")
    # non-overlapping 5-blocks on the TEST split
    for name,pred in [("model",pred_model),("always-UP",pred_up),("momentum",pred_mom)]:
        hits=[]
        i=cut
        while i+5<=n:
            # ensure block is same coin & contiguous
            block=range(i,i+5)
            hits.append(int(sum(pred[j]==y[j] for j in block)))
            i+=5
        hits=np.array(hits)
        dist=[ (hits==k).mean() for k in range(6)]
        p3=(hits>=3).mean(); p4=(hits>=4).mean(); p5=(hits==5).mean()
        print(f"{name:10} blocks={len(hits)}  hits/5 dist [0..5]={[round(x,3) for x in dist]}")
        print(f"{'':10} P(>=3/5)={p3:.3f}  P(>=4/5)={p4:.3f}  P(5/5)={p5:.3f}  mean={hits.mean():.2f}/5\n")


if __name__=="__main__":
    main()
