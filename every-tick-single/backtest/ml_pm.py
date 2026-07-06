#!/usr/bin/env python3
"""Test prediction on POLYMARKET microstructure (not Binance klines): order-flow
imbalance, book imbalance, in-bar price path, logged p_up, prior outcomes — the
features the PM feed has that klines don't. Predict THIS bar (from early features
= momentum/priced check) and NEXT bar (genuine forecast). Walk-forward, GBM+MLP,
train-vs-test AUC (overfit control).
Usage: python3 ml_pm.py   (uses every-tick-single/tests/data/*)
"""
import json, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import experiments as X
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import roc_auc_score

def build():
    root=os.path.join(os.path.dirname(os.path.abspath(__file__)),"..","tests","data")
    dates=sorted(d for d in os.listdir(root) if d.startswith("2026-07-0"))
    rows=[]
    for d in dates:
        dd=os.path.join(root,d)
        if not os.path.isdir(dd): continue
        for (c,cid),b in X.load(dd).items():
            if b["outcome"] not in ("UP","DOWN") or not b["bar_ts"]: continue
            pr=b["prints"]; ss=sorted(b["snaps"],key=lambda s:-s[0])
            e=[p for p in pr if p[0]>=240]  # first 60s
            euv=sum(p[3] for p in e if p[1]=="UP"); edv=sum(p[3] for p in e if p[1]=="DOWN")
            eflow=(euv-edv)/(euv+edv) if (euv+edv) else 0
            auv=sum(p[3] for p in pr if p[1]=="UP"); adv=sum(p[3] for p in pr if p[1]=="DOWN")
            aflow=(auv-adv)/(auv+adv) if (auv+adv) else 0
            bimb=0;nb=0
            for s in ss:
                bs=s[1]+s[3]-(s[2]+s[4])  # (up_bid+dn_bid)-(up_ask+dn_ask) rough
                bimb+=bs;nb+=1
            bimb=bimb/nb if nb else 0
            mv=0
            if len(ss)>=2:
                om=(ss[0][1]+ss[0][2])/2; le=[s for s in ss if s[0]<=240]
                if le: mv=(le[0][1]+le[0][2])/2-om
            rows.append({"c":c,"ts":b["bar_ts"],"y":1 if b["outcome"]=="UP" else 0,
                         "f":[eflow,aflow,bimb,mv*10,(b.get("p_up") or 0.5)]})
    rows.sort(key=lambda r:(r["ts"],r["c"]))
    # attach prior outcome + next outcome per coin
    hist={};nexts={}
    seq={}
    for r in rows: seq.setdefault(r["c"],[]).append(r)
    for c,rs in seq.items():
        for i,r in enumerate(rs):
            r["f"]=r["f"]+[rs[i-1]["y"] if i>0 else 0, rs[i-2]["y"] if i>1 else 0]
            r["ynext"]=rs[i+1]["y"] if i+1<len(rs) else None
    return rows

def evalset(rows,target):
    data=[(r["f"],r[target]) for r in rows if r.get(target) is not None]
    Xa=np.array([d[0] for d in data]);y=np.array([d[1] for d in data]);cut=int(len(y)*.7)
    if cut<50: return
    sc=StandardScaler().fit(Xa[:cut]);Xtr,Xte=sc.transform(Xa[:cut]),sc.transform(Xa[cut:]);ytr,yte=y[:cut],y[cut:]
    out=[]
    for nm,m in [("gbm",GradientBoostingClassifier(n_estimators=80,max_depth=3,learning_rate=0.05)),
                 ("mlp",MLPClassifier(hidden_layer_sizes=(32,),alpha=1.0,max_iter=300,early_stopping=True,random_state=0))]:
        m.fit(Xtr,ytr);ptr=m.predict_proba(Xtr)[:,1];pte=m.predict_proba(Xte)[:,1]
        out.append(f"{nm} train {roc_auc_score(ytr,ptr):.3f} test {roc_auc_score(yte,pte):.3f} gap {roc_auc_score(ytr,ptr)-roc_auc_score(yte,pte):+.3f} acc {((pte>=.5)==yte).mean()*100:.1f}%")
    return len(y),cut,out

def main():
    rows=build()
    print(f"PM bars with features: {len(rows)}  (features: earlyflow, allflow, book-imb, 60s-move, p_up, prev1, prev2)\n")
    for tgt,lbl in [("y","THIS bar (early feats -> same-bar outcome; momentum/priced)"),
                    ("ynext","NEXT bar (genuine forecast)")]:
        r=evalset(rows,tgt)
        if r:
            n,cut,out=r
            print(f"{lbl}\n  n={n} train {cut}/test {n-cut}")
            for o in out: print("   ",o)
            print()

if __name__=="__main__": main()
