#!/usr/bin/env python3
"""TA-1..4 — predict next 5m outcome from TECHNICAL INDICATORS + candle statistics
computed STRICTLY from prior bars (no lookahead), then test placing at 50c/49c/etc.

Indicators (all through bar i-1, predicting bar i): RSI(14), Bollinger %B(20),
MACD histogram(12,26,9), Stochastic %K(14), ATR(14)/close, ROC(6), close vs SMA20
/SMA50, up/down streak length, and last-bar candle anatomy (body, upper/lower wick
fractions, range). Walk-forward 70/30. Then a PLACEMENT test: on the model's
confident predictions, is the realized win rate high enough to beat a bid at P
(need realized > P)?

Data: scratchpad/binance/{coin}_5m.json = [[t,o,h,l,c,vol,ntr,takerbuy], ...]
Usage: python3 ml_technical.py <binance_dir>
"""
from __future__ import annotations
import json, math, os, sys


def indicators(rows):
    """Return list of feature vectors and labels; feature at i uses bars <= i-1,
    label is outcome of bar i (close_i >= open_i)."""
    o = [r[1] for r in rows]; h = [r[2] for r in rows]
    l = [r[3] for r in rows]; c = [r[4] for r in rows]
    n = len(rows)

    def sma(arr, k, i):
        return sum(arr[i-k+1:i+1]) / k if i >= k-1 else arr[i]

    def ema_series(arr, k):
        e = [arr[0]]; a = 2/(k+1)
        for x in arr[1:]:
            e.append(a*x + (1-a)*e[-1])
        return e
    ema12 = ema_series(c, 12); ema26 = ema_series(c, 26)
    macd = [ema12[i]-ema26[i] for i in range(n)]
    signal = ema_series(macd, 9)

    def rsi(i, k=14):
        if i < k:
            return 50.0
        gains = losses = 0.0
        for j in range(i-k+1, i+1):
            d = c[j]-c[j-1]
            gains += max(d, 0); losses += max(-d, 0)
        if losses == 0:
            return 100.0
        rs = (gains/k)/(losses/k)
        return 100 - 100/(1+rs)

    def atr(i, k=14):
        if i < k:
            return (h[i]-l[i])
        s = 0.0
        for j in range(i-k+1, i+1):
            s += max(h[j]-l[j], abs(h[j]-c[j-1]), abs(l[j]-c[j-1]))
        return s/k

    X, y = [], []
    for i in range(60, n):     # need history for SMA50 etc
        p = i-1                # last CLOSED bar
        # bollinger %B(20)
        m = sma(c, 20, p)
        var = sum((c[j]-m)**2 for j in range(p-19, p+1))/20
        sd = var**.5 or 1e-9
        pctb = (c[p]-(m-2*sd))/(4*sd)
        # stochastic %K(14)
        lo = min(l[p-13:p+1]); hi = max(h[p-13:p+1])
        stoch = (c[p]-lo)/(hi-lo) if hi > lo else 0.5
        # streak
        streak = 0
        for j in range(p, 0, -1):
            up = c[j] >= o[j]
            if j == p:
                cur = up; streak = 1
            elif (c[j] >= o[j]) == cur:
                streak += 1
            else:
                break
        streak = streak if cur else -streak
        # candle anatomy of last bar
        rng = h[p]-l[p] or 1e-9
        body = (c[p]-o[p])/rng
        uwick = (h[p]-max(o[p], c[p]))/rng
        lwick = (min(o[p], c[p])-l[p])/rng
        feat = [
            rsi(p)/100, pctb, macd[p]-signal[p], stoch,
            atr(p)/c[p]*100 if c[p] else 0,
            (c[p]/c[p-6]-1)*100 if p >= 6 and c[p-6] else 0,   # ROC6
            (c[p]/sma(c, 20, p)-1)*100, (c[p]/sma(c, 50, p)-1)*100,
            streak, body, uwick, lwick,
        ]
        X.append(feat)
        y.append(1 if c[i] >= o[i] else 0)
    return X, y


def main():
    bdir = sys.argv[1]
    coins = ("btc", "eth", "sol", "xrp")
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.ensemble import GradientBoostingClassifier
    from sklearn.preprocessing import StandardScaler
    from sklearn.metrics import roc_auc_score
    Xall, yall = [], []
    for c in coins:
        rows = json.load(open(os.path.join(bdir, f"{c}_5m.json")))
        X, y = indicators(rows)
        Xall += X; yall += y
    Xa, ya = np.array(Xall, float), np.array(yall)
    cut = int(len(ya)*0.7)
    sc = StandardScaler().fit(Xa[:cut])
    Xtr, Xte = sc.transform(Xa[:cut]), sc.transform(Xa[cut:])
    ytr, yte = ya[:cut], ya[cut:]
    print(f"TA model — {len(ya)} bars, 12 indicators, walk-forward 70/30")
    print(f"test base-UP rate = {yte.mean():.4f}\n")
    models = {}
    for nm, m in [("logreg", LogisticRegression(max_iter=1000)),
                  ("gbm", GradientBoostingClassifier(n_estimators=100, max_depth=3, learning_rate=0.05))]:
        m.fit(Xtr, ytr); p = np.clip(m.predict_proba(Xte)[:, 1], 1e-6, 1-1e-6)
        auc = roc_auc_score(yte, p); brier = np.mean((p-yte)**2)
        print(f"{nm:8} AUC={auc:.4f} Brier={brier:.4f} acc={np.mean((p>=0.5)==yte):.4f}")
        models[nm] = p
    # PLACEMENT test: on the GBM's confident predictions, realized win rate vs P.
    p = models["gbm"]
    print("\nPLACEMENT — bet the model's predicted side; realized win rate must beat P:")
    print(f"{'conf band':>16} {'n':>6} {'pred-side win%':>14}  vs 0.50 vs 0.49 vs 0.48")
    for lo, hi in [(0.5, 0.52), (0.52, 0.55), (0.55, 0.60), (0.60, 1.0)]:
        # predicted side = UP if p>=0.5 else DOWN; confidence = |p-0.5| mapped
        mask = (np.abs(p-0.5) >= (lo-0.5)) & (np.abs(p-0.5) < (hi-0.5))
        if mask.sum() < 20:
            continue
        pred_up = p[mask] >= 0.5
        win = (pred_up == (yte[mask] == 1)).mean()
        marks = "  ".join("Y" if win > b else "n" for b in (0.50, 0.49, 0.48))
        print(f"{f'|p-.5| {lo}-{hi}':>16} {int(mask.sum()):6} {win*100:13.1f}%  {marks}")
    print("\n(Y at 0.49 means: model-picked side wins >49% → a bid at 49c on that side is +EV\n"
          " on OUTCOME, before adverse-selection on the fill. The fill reality (fill_study.py)\n"
          " subtracts ~4pp, so realized needs a wide margin over P.)")


if __name__ == "__main__":
    main()
