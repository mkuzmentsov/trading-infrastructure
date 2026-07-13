#!/usr/bin/env python3
"""Walk-forward OOS eval for the cur+2 direction models, WITH a confidence-gate
analysis: the raw all-bar accuracy is ~51%; can we reach >=52% honestly by only
betting when the model is confident? Reports OOS win-rate at several |p-0.5| gates
(and the resulting bet frequency) so we don't overfit to hit the target.

Reuses the EXACT feature spec from train_export.py."""
import json, sys
import numpy as np, pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier

H = 2
COINS = {"btc": "data.csv", "eth": "data_eth.csv", "sol": "data_sol.csv",
         "xrp": "data_xrp.csv", "doge": "data_doge.csv"}
LAGS = [1, 2, 3, 6, 12, 24]
GATES = [0.00, 0.01, 0.02, 0.03, 0.05]   # |p-0.5| thresholds

def features(d):
    d = d.copy()
    d["y"] = (d["close"] >= d["open"]).astype(int)
    d["clc"] = d["close"].pct_change()
    d["range"] = (d["high"] - d["low"]) / d["open"]
    d["tbr"] = (d["takerBuyBase"] / d["volume"].replace(0, np.nan)) - 0.5
    dt = pd.to_datetime(d["openTime"], unit="ms"); d["hour"] = dt.dt.hour
    F = {}
    for k in LAGS:
        F[f"clc{k}"] = d["clc"].shift(k); F[f"y{k}"] = d["y"].shift(k) - 0.5
    F["mom3"] = d["clc"].rolling(3).sum().shift(1); F["mom6"] = d["clc"].rolling(6).sum().shift(1)
    F["mom12"] = d["clc"].rolling(12).sum().shift(1)
    v = d["clc"].rolling(12).std().shift(1); F["vol12"] = v
    F["zmom6"] = d["clc"].rolling(6).sum().shift(1) / (v * np.sqrt(6)); F["revert"] = -d["clc"].shift(1) / v
    F["rng6"] = d["range"].rolling(6).mean().shift(1)
    F["tbr1"] = d["tbr"].shift(1); F["tbr3"] = d["tbr"].rolling(3).mean().shift(1)
    F["volz"] = ((d["volume"] - d["volume"].rolling(48).mean()) / d["volume"].rolling(48).std()).shift(1)
    F["hsin"] = np.sin(2*np.pi*d["hour"]/24); F["hcos"] = np.cos(2*np.pi*d["hour"]/24)
    return pd.DataFrame(F, index=d.index), d["y"]

def mk_model():
    return HistGradientBoostingClassifier(max_depth=3, learning_rate=0.03, max_iter=200,
        l2_regularization=2.0, min_samples_leaf=100, random_state=0)

report = {}
print(f"{'coin':>5}  {'gate':>5} {'OOS win%':>9} {'bets/day':>9} {'z':>6}")
print("-"*44)
for coin, path in COINS.items():
    d = pd.read_csv(path)
    for c in ["open","high","low","close","volume","takerBuyBase"]:
        d[c] = d[c].astype(float)
    X, y = features(d)
    yH = y.shift(-H)
    dd = pd.concat([X, yH.rename("t"),
                    pd.to_datetime(d["openTime"], unit="ms").dt.floor("D").rename("day")],
                   axis=1).dropna().reset_index(drop=True)
    feat = list(X.columns)
    days = sorted(dd["day"].unique())
    # collect OOS (prob, outcome) across walk-forward
    P, T = [], []
    for i in range(12, len(days)):
        tr = dd[dd["day"] < days[i]]; te = dd[dd["day"] == days[i]]
        if len(te) < 50: continue
        m = mk_model().fit(tr[feat], tr["t"])
        P.append(m.predict_proba(te[feat])[:,1]); T.append(te["t"].values)
    P = np.concatenate(P); T = np.concatenate(T)
    ndays = len(days) - 12
    coin_rep = {}
    for g in GATES:
        mask = np.abs(P - 0.5) >= g
        if mask.sum() < 30:
            coin_rep[f"gate{g}"] = None; continue
        pred = (P[mask] >= 0.5).astype(int)
        win = (pred == T[mask]).mean()
        nbets = mask.sum()
        z = (win - 0.5) / (np.sqrt(0.25/nbets))
        coin_rep[f"gate{g}"] = dict(win=round(float(win),4), bets_per_day=round(nbets/ndays,1),
                                     n=int(nbets), z=round(float(z),2))
        star = " <-- >=52%" if win >= 0.52 else ""
        print(f"{coin:>5}  {g:>5.2f} {100*win:>8.2f}% {nbets/ndays:>9.1f} {z:>6.2f}{star}")
    report[coin] = coin_rep
    print()
json.dump(report, open("eval_gate_report.json","w"), indent=2)
print("saved eval_gate_report.json")
