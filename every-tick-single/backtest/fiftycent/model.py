#!/usr/bin/env python3
"""Predict 5m bar direction (close>=open) on Binance BTCUSDT, strict time-ordered
OOS. All features causal (known at bar open = prior bar close). Honest baselines +
logistic + gradient boosting. Reports accuracy vs base rate, AUC, and the win rate
of betting the predicted side at 0.50."""
import numpy as np, pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import roc_auc_score

d = pd.read_csv("data.csv")
for c in ["open", "high", "low", "close", "volume", "takerBuyBase"]:
    d[c] = d[c].astype(float)
d["ret"] = d["close"] / d["open"] - 1.0                 # bar return (this bar)
d["y"] = (d["close"] >= d["open"]).astype(int)          # target: UP
d["range"] = (d["high"] - d["low"]) / d["open"]
d["tbr"] = d["takerBuyBase"] / d["volume"].replace(0, np.nan)   # taker-buy ratio (order flow)
d["hour"] = (pd.to_datetime(d["openTime"], unit="ms").dt.hour)
d["dow"] = (pd.to_datetime(d["openTime"], unit="ms").dt.dayofweek)

# ---- causal features: everything shifted so bar t only sees <= t-1 ----
F = {}
for k in [1, 2, 3, 6, 12]:
    F[f"ret_lag{k}"] = d["ret"].shift(k)
    F[f"y_lag{k}"] = d["y"].shift(k) - 0.5
F["mom3"] = d["ret"].rolling(3).sum().shift(1)
F["mom6"] = d["ret"].rolling(6).sum().shift(1)
F["mom12"] = d["ret"].rolling(12).sum().shift(1)
F["vol6"] = d["ret"].rolling(6).std().shift(1)
F["vol12"] = d["ret"].rolling(12).std().shift(1)
F["range6"] = d["range"].rolling(6).mean().shift(1)
F["tbr1"] = d["tbr"].shift(1) - 0.5
F["tbr6"] = d["tbr"].rolling(6).mean().shift(1) - 0.5
F["volz"] = ((d["volume"] - d["volume"].rolling(48).mean()) / d["volume"].rolling(48).std()).shift(1)
F["streak"] = (d["y"].replace(0, -1).groupby((d["y"] != d["y"].shift()).cumsum()).cumcount() + 1)
F["streak"] = (F["streak"] * d["y"].replace(0, -1)).shift(1)
F["hour_sin"] = np.sin(2 * np.pi * d["hour"] / 24)
F["hour_cos"] = np.cos(2 * np.pi * d["hour"] / 24)
X = pd.DataFrame(F)
y = d["y"]

data = pd.concat([X, y.rename("y")], axis=1).dropna().reset_index(drop=True)
Xc = data.drop(columns="y"); yc = data["y"]
n = len(Xc); split = int(n * 0.8)
Xtr, Xte = Xc.iloc[:split], Xc.iloc[split:]
ytr, yte = yc.iloc[:split], yc.iloc[split:]
print(f"samples={n}  train={len(Xtr)}  test={len(Xte)}  features={Xc.shape[1]}")
print(f"base rate UP (test) = {yte.mean():.4f}  (this is the accuracy to beat)\n")

def report(name, pred, proba=None):
    acc = (pred == yte.values).mean()
    line = f"{name:26} acc={acc:.4f}"
    if proba is not None:
        try: line += f"  AUC={roc_auc_score(yte, proba):.4f}"
        except Exception: pass
    # win rate of betting predicted side at 0.50 (before fill adverse selection)
    line += f"  edge_vs_50={acc-0.5:+.4f}"
    print(line)

# ---- naive baselines ----
report("always-UP", np.ones(len(yte), int))
report("always-DOWN", np.zeros(len(yte), int))
report("momentum (=last bar)", (Xte["y_lag1"] > 0).astype(int).values)
report("reversal (!=last bar)", (Xte["y_lag1"] < 0).astype(int).values)

# ---- logistic ----
sc = StandardScaler().fit(Xtr)
lr = LogisticRegression(max_iter=1000, C=0.1).fit(sc.transform(Xtr), ytr)
p = lr.predict_proba(sc.transform(Xte))[:, 1]
report("logistic", (p >= 0.5).astype(int), p)

# ---- gradient boosting ----
gb = HistGradientBoostingClassifier(max_depth=3, learning_rate=0.03, max_iter=300,
                                    l2_regularization=1.0, min_samples_leaf=80,
                                    validation_fraction=0.15, random_state=0).fit(Xtr, ytr)
pg = gb.predict_proba(Xte)[:, 1]
report("gradient boosting", (pg >= 0.5).astype(int), pg)

# ---- does confidence help? bet only when |p-0.5| is large ----
print("\nConfidence-gated logistic (bet predicted side at 0.50 only when confident):")
for thr in (0.0, 0.02, 0.05, 0.08):
    mask = np.abs(p - 0.5) >= thr
    if mask.sum() < 20: continue
    wr = ((p[mask] >= 0.5).astype(int) == yte.values[mask]).mean()
    print(f"  |p-0.5|>={thr:.2f}  bets={mask.sum():5d} ({100*mask.mean():4.0f}%)  win={wr:.4f}  EV/bet@0.50={wr-0.5:+.4f}")
