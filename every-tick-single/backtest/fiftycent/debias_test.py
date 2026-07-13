#!/usr/bin/env python3
"""Test the debias fix: the models bet one side almost always because p_up rides a
spurious in-sample base-rate offset (eth center 0.495, sol 0.523). Compare, walk-
forward OOS:
  RAW      : bet UP iff p>=0.50               (current bot rule)
  DEBIASED : bet UP iff p>=mu, mu=train-set mean pred  (threshold at model center)
Report win rate AND the DOWN/UP split for each, at conviction gates on |p-center|."""
import numpy as np, pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from train_export import features, mk_model  # reuse EXACT training spec

H = 2
COINS = {"eth": "data_eth.csv", "sol": "data_sol.csv", "xrp": "data_xrp.csv",
         "btc": "data.csv", "doge": "data_doge.csv"}
GATES = [0.00, 0.02, 0.03]

for coin, path in COINS.items():
    d = pd.read_csv(path)
    for c in ["open","high","low","close","volume","takerBuyBase"]: d[c]=d[c].astype(float)
    X, y = features(d)
    yH = y.shift(-H)
    dd = pd.concat([X, yH.rename("t"),
                    pd.to_datetime(d["openTime"],unit="ms").dt.floor("D").rename("day")],
                   axis=1).dropna().reset_index(drop=True)
    feat = list(X.columns); days = sorted(dd["day"].unique())
    P, T, MU = [], [], []
    for i in range(12, len(days)):
        tr = dd[dd["day"]<days[i]]; te = dd[dd["day"]==days[i]]
        if len(te)<50: continue
        m = mk_model().fit(tr[feat], tr["t"])
        mu = m.predict_proba(tr[feat])[:,1].mean()      # model center from TRAIN only (causal)
        P.append(m.predict_proba(te[feat])[:,1]); T.append(te["t"].values)
        MU.append(np.full(len(te), mu))
    P=np.concatenate(P); T=np.concatenate(T); MU=np.concatenate(MU)
    ndays = len(P)/288
    print(f"\n=== {coin.upper()}  (p_up center≈{P.mean():.3f}) ===")
    print(f"{'rule':>9} {'gate':>5} {'win%':>7} {'bets/d':>7} {'UP%':>5} {'DOWN%':>6}")
    for label, thr in [("RAW", np.full_like(P,0.5)), ("DEBIAS", MU)]:
        for g in GATES:
            mask = np.abs(P-thr) >= g
            if mask.sum()<30: continue
            pred = (P[mask] >= thr[mask]).astype(int)       # 1=UP
            win = (pred==T[mask]).mean()
            up = pred.mean()*100
            print(f"{label:>9} {g:>5.2f} {100*win:>6.2f}% {mask.sum()/ndays:>7.1f} {up:>4.0f}% {100-up:>5.0f}%"
                  + (" <52%+" if win>=0.52 else ""))
