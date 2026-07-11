#!/usr/bin/env python3
"""Try hard for >=55% daily OOS on 5m direction: rich features, walk-forward
(retrain each day on all prior data), per-day win rate, and a permutation null
so we know whether any good day is signal or luck."""
import numpy as np, pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier

d = pd.read_csv("data.csv")
for c in ["open", "high", "low", "close", "volume", "takerBuyBase"]:
    d[c] = d[c].astype(float)
d["ret"] = d["close"] / d["open"] - 1.0
d["y"] = (d["close"] >= d["open"]).astype(int)
d["clc"] = d["close"].pct_change()                       # close-to-close return
d["range"] = (d["high"] - d["low"]) / d["open"]
d["body"] = (d["close"] - d["open"]) / d["open"]
d["tbr"] = (d["takerBuyBase"] / d["volume"].replace(0, np.nan)) - 0.5
d["dt"] = pd.to_datetime(d["openTime"], unit="ms")
d["day"] = d["dt"].dt.floor("D")
d["hour"] = d["dt"].dt.hour

F = {}
for k in [1, 2, 3, 6, 12, 24]:
    F[f"clc{k}"] = d["clc"].shift(k)
    F[f"y{k}"] = d["y"].shift(k) - 0.5
# momentum, vol-normalized momentum, acceleration, mean-reversion
F["mom3"] = d["clc"].rolling(3).sum().shift(1)
F["mom6"] = d["clc"].rolling(6).sum().shift(1)
F["mom12"] = d["clc"].rolling(12).sum().shift(1)
vol12 = d["clc"].rolling(12).std().shift(1)
F["vol12"] = vol12
F["zmom6"] = (d["clc"].rolling(6).sum().shift(1)) / (vol12 * np.sqrt(6))
F["accel"] = (d["clc"].rolling(3).sum() - d["clc"].shift(3).rolling(3).sum()).shift(1)
F["revert"] = (-d["clc"].shift(1) / vol12)               # big last move -> reversion?
F["rng6"] = d["range"].rolling(6).mean().shift(1)
F["rng_exp"] = (d["range"].shift(1) / d["range"].rolling(12).mean().shift(1))
F["tbr1"] = d["tbr"].shift(1)
F["tbr3"] = d["tbr"].rolling(3).mean().shift(1)
F["volz"] = ((d["volume"] - d["volume"].rolling(48).mean()) / d["volume"].rolling(48).std()).shift(1)
F["hsin"] = np.sin(2*np.pi*d["hour"]/24); F["hcos"] = np.cos(2*np.pi*d["hour"]/24)
X = pd.DataFrame(F, index=d.index)

d2 = pd.concat([X, d[["y", "day"]]], axis=1).dropna().reset_index(drop=True)
days = sorted(d2["day"].unique())
WARM = 12                                                 # first 12 days = initial train
feat = list(X.columns)

# carry OHLC through for the fill-conditional analysis
d2 = pd.concat([d2, d.loc[d2.index if False else None, :]], axis=0) if False else d2
ohlc = d[["open", "high", "low", "close"]].reindex(
    pd.concat([X, d[["y", "day"]]], axis=1).dropna().index).reset_index(drop=True)

daily = []
allp = []   # (p, y, open, low, high, close)
for i in range(WARM, len(days)):
    trm = d2["day"] < days[i]; tem = d2["day"] == days[i]
    tr, te = d2[trm], d2[tem]
    if len(te) < 50: continue
    gb = HistGradientBoostingClassifier(max_depth=3, learning_rate=0.03, max_iter=250,
            l2_regularization=2.0, min_samples_leaf=100, random_state=0)
    gb.fit(tr[feat], tr["y"])
    p = gb.predict_proba(te[feat])[:, 1]
    acc = ((p >= 0.5).astype(int) == te["y"].values).mean()
    daily.append((days[i], len(te), acc))
    o = ohlc[tem.values]
    for pi, yi, oo, lo, hi, cc in zip(p, te["y"].values, o["open"], o["low"], o["high"], o["close"]):
        allp.append((pi, yi, oo, lo, hi, cc))

accs = np.array([a for _, _, a in daily])
print(f"walk-forward OOS: {len(daily)} days, retrained daily on all prior data")
print(f"mean daily acc = {accs.mean():.4f}   std = {accs.std():.4f}")
print(f"days >= 55%: {(accs>=0.55).sum()}/{len(accs)}   days <= 45%: {(accs<=0.45).sum()}/{len(accs)}")
print(f"best day {accs.max():.3f}   worst day {accs.min():.3f}")

# null: if every bar were a fair coin, what daily-acc spread appears by luck?
rng = np.random.default_rng(0)
sizes = np.array([n for _, n, _ in daily])
null_ge55 = []
for _ in range(2000):
    sim = np.array([rng.binomial(n, 0.5)/n for n in sizes])
    null_ge55.append((sim >= 0.55).mean())
null_ge55 = np.array(null_ge55)
print(f"\nNULL (fair coin): expected fraction of days >=55% = {null_ge55.mean():.3f} "
      f"(so ~{null_ge55.mean()*len(accs):.0f} of {len(accs)} days by pure luck)")
print(f"our fraction of days >=55% = {(accs>=0.55).mean():.3f}")
z = (accs.mean() - 0.5) / (accs.std()/np.sqrt(len(accs)))
print(f"is mean daily acc > 0.50?  z = {z:+.2f}  ({'significant' if abs(z)>2 else 'NOT significant'})")
print("\n'>=55% every day' would need the mean well above 0.55 with tiny variance — "
      "here it's ~0.515 with the exact spread a coin flip produces.")

# ---- is there a tradeable high-confidence subset? ----
A = np.array(allp)
p, y, o, lo, hi, cc = A[:,0], A[:,1], A[:,2], A[:,3], A[:,4], A[:,5]
pred_up = p >= 0.5
print("\nConfidence gating (all OOS bars pooled): bet predicted side at 0.50")
for thr in (0.0, 0.02, 0.04, 0.06, 0.08):
    m = np.abs(p-0.5) >= thr
    if m.sum() < 50: continue
    wr = ((pred_up[m].astype(int)) == y[m]).mean()
    print(f"  |p-0.5|>={thr:.2f}  bets={m.sum():6d} ({100*m.mean():3.0f}%)  win={wr:.4f}  EV@0.50={wr-0.5:+.4f}")

# ---- fill-conditional: a 0.50 resting bid on the predicted side fills only when
#      price crosses to that side (moves AGAINST the prediction). Win rate there? ----
# predict UP -> rest UP -> fills iff low<open. predict DOWN -> rest DOWN -> fills iff high>open.
fill = np.where(pred_up, lo < o, hi > o)
win = np.where(pred_up, cc >= o, cc < o)
print("\nFill-conditional (resting 0.50 bid on predicted side, hold to resolution):")
print(f"  unconditional win = {win.mean():.4f}")
print(f"  win | filled@0.50 = {win[fill].mean():.4f}   (fills={fill.mean()*100:.0f}% of bets)")
print("  (adverse selection: the bid only fills when price moves against your call)")
