#!/usr/bin/env python3
"""Neural-net (MLP) prediction with explicit overfit control. Predict next-bar
outcome from the 13-feature set. Time-ordered split (NO shuffle). Sweeps
architecture x L2-regularization and prints TRAIN vs TEST AUC — the train-test
gap IS the overfit measure. A model that overfits shows high train / low test.
Usage: python3 ml_nn.py <binance_dir> [offset=1]
"""
import json, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ml_predict5 import feats
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import roc_auc_score

def main():
    bdir=sys.argv[1]; N=int(sys.argv[2]) if len(sys.argv)>2 else 1
    X=[];y=[]
    for c in ("btc","eth","sol","xrp"):
        rows=json.load(open(os.path.join(bdir,f"{c}_5m.json")))
        F,idxs=feats(rows)
        for k,i in enumerate(idxs):
            if i+N<len(rows): X.append(F[k]);tb=rows[i-1+N];y.append(1 if tb[4]>=tb[1] else 0)
    X=np.array(X);y=np.array(y);cut=int(len(y)*.7)
    sc=StandardScaler().fit(X[:cut]);Xtr,Xte=sc.transform(X[:cut]),sc.transform(X[cut:])
    ytr,yte=y[:cut],y[cut:]
    print(f"offset +{N}, {len(y)} samples, time-split train {cut} / test {len(y)-cut}, base-UP {yte.mean():.3f}")
    print(f"{'arch':>12} {'alpha(L2)':>10} {'train AUC':>10} {'test AUC':>9} {'gap':>7} {'test acc':>9}")
    for arch in [(8,),(32,),(64,32),(128,64,32)]:
        for alpha in [1.0, 0.1, 0.01]:
            m=MLPClassifier(hidden_layer_sizes=arch,alpha=alpha,max_iter=300,
                            early_stopping=True,n_iter_no_change=15,random_state=0)
            m.fit(Xtr,ytr)
            ptr=m.predict_proba(Xtr)[:,1];pte=m.predict_proba(Xte)[:,1]
            atr=roc_auc_score(ytr,ptr);ate=roc_auc_score(yte,pte)
            acc=((pte>=.5)==yte).mean()
            flag=" OVERFIT" if atr-ate>0.03 else ""
            print(f"{str(arch):>12} {alpha:>10} {atr:>10.4f} {ate:>9.4f} {atr-ate:>+7.4f} {acc*100:>8.1f}%{flag}")

if __name__=="__main__": main()
