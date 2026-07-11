#!/usr/bin/env python3
"""Train + freeze per-coin cur+2 direction models for the model service.
Walk-forward validates (OOS acc), then fits a FINAL model on all data and pickles
it with the exact feature spec so the service computes features identically."""
import json, pickle, sys, pathlib
import numpy as np, pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier

H = 2
COINS = {"btc": "data.csv", "eth": "data_eth.csv", "sol": "data_sol.csv", "xrp": "data_xrp.csv"}
OUTDIR = pathlib.Path("models"); OUTDIR.mkdir(exist_ok=True)

# feature spec — MUST match the service's live feature computation exactly
LAGS = [1, 2, 3, 6, 12, 24]

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
for coin, path in COINS.items():
    d = pd.read_csv(path)
    for c in ["open","high","low","close","volume","takerBuyBase"]:
        d[c] = d[c].astype(float)
    X, y = features(d)
    yH = y.shift(-H)
    dd = pd.concat([X, yH.rename("t"), pd.to_datetime(d["openTime"], unit="ms").dt.floor("D").rename("day")], axis=1).dropna().reset_index(drop=True)
    feat = list(X.columns)
    # walk-forward OOS
    days = sorted(dd["day"].unique()); acc = []
    for i in range(12, len(days)):
        tr = dd[dd["day"] < days[i]]; te = dd[dd["day"] == days[i]]
        if len(te) < 50: continue
        m = mk_model().fit(tr[feat], tr["t"])
        acc.append(((m.predict_proba(te[feat])[:,1] >= 0.5).astype(int) == te["t"].values).mean())
    acc = np.array(acc); z = (acc.mean()-0.5)/(acc.std()/np.sqrt(len(acc)))
    # final model on ALL data
    final = mk_model().fit(dd[feat], dd["t"])
    with open(OUTDIR / f"{coin}_cur{H}.pkl", "wb") as f:
        pickle.dump({"model": final, "features": feat, "lags": LAGS, "horizon": H}, f)
    report[coin] = {"oos_acc": round(float(acc.mean()),4), "z": round(float(z),2), "days>=55%": int((acc>=0.55).sum()), "n_days": len(acc)}
    print(f"{coin.upper():4} cur+{H}  OOS acc={acc.mean():.4f}  z={z:+.2f}  days>=55%={int((acc>=0.55).sum())}/{len(acc)}  -> models/{coin}_cur{H}.pkl")

json.dump(report, open(OUTDIR/"report.json","w"), indent=2)
print("\nfrozen models + report.json written to models/")
