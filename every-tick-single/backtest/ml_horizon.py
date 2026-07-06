#!/usr/bin/env python3
"""ST-1 extension — predict the sign of cumulative return over the NEXT H bars
from the last N bars of rich 5m data, walk-forward validated.

Motivation: the single 5m bar is a martingale (ml_outcome.py: AUC 0.53). Longer
horizons may carry trend structure, and data.binance.vision 5m klines add fields
the Polymarket feed lacks — number of trades and TAKER-BUY volume (a historical
aggressor/order-flow proxy). This tests whether direction is predictable at all
at ANY horizon with richer features.

Features per bar (last N): log intrabar return, log volume z, taker-buy ratio
(taker_buy_base/volume − 0.5 = aggressor imbalance), trade-count z, high-low
range. Target: sign of (close[t+H] − close[t]).

Data: scratchpad/binance/{coin}_5m.json = [[openT, o,h,l,c, vol, ntrades, takerbuybase], ...]

Usage: python3 ml_horizon.py <binance_dir> [N=12] [horizons=1,3,6,12,24]
Requires numpy + sklearn.
"""
from __future__ import annotations
import json, math, os, sys


def features(rows, N):
    """→ (X list, close list, ts list). Feature row at index i uses bars i-N..i-1
    (strictly past); target computed by caller from close[i-1] vs close[i-1+H]."""
    vols = [r[5] for r in rows]
    ntr = [r[6] for r in rows]
    import statistics
    lv_mean = statistics.mean(math.log(v + 1) for v in vols)
    lv_sd = statistics.pstdev(math.log(v + 1) for v in vols) or 1
    nt_mean = statistics.mean(ntr)
    nt_sd = statistics.pstdev(ntr) or 1
    X, closes, ts = [], [], []
    for i in range(N, len(rows)):
        feat = []
        for j in range(i - N, i):
            o, h, l, c, v, n, tb = rows[j][1], rows[j][2], rows[j][3], rows[j][4], rows[j][5], rows[j][6], rows[j][7]
            ret = math.log(c / o) * 100 if o > 0 and c > 0 else 0.0
            vz = (math.log(v + 1) - lv_mean) / lv_sd
            flow = (tb / v - 0.5) if v > 0 else 0.0          # taker-buy imbalance
            nz = (n - nt_mean) / nt_sd
            rng = (h - l) / o * 100 if o > 0 else 0.0
            feat += [ret, vz, flow, nz, rng]
        X.append(feat)
        closes.append(rows[i - 1][4])
        ts.append(rows[i - 1][0])
    return X, closes, ts


def evaluate(X, y, train_frac=0.7):
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.ensemble import GradientBoostingClassifier
    from sklearn.preprocessing import StandardScaler
    from sklearn.metrics import roc_auc_score
    Xa, ya = np.array(X, float), np.array(y)
    n = len(ya); cut = int(n * train_frac)
    Xtr, Xte, ytr, yte = Xa[:cut], Xa[cut:], ya[:cut], ya[cut:]
    sc = StandardScaler().fit(Xtr)
    Xtr, Xte = sc.transform(Xtr), sc.transform(Xte)
    def score(p):
        p = np.clip(p, 1e-6, 1 - 1e-6)
        brier = float(np.mean((p - yte) ** 2))
        acc = float(np.mean((p >= 0.5) == yte))
        auc = float(roc_auc_score(yte, p)) if len(set(yte)) > 1 else 0.5
        return brier, auc, acc
    out = {"n_test": int(n - cut), "test_up_rate": round(float(yte.mean()), 3)}
    for name, m in [("logreg", LogisticRegression(max_iter=1000)),
                    ("gbm", GradientBoostingClassifier(n_estimators=80, max_depth=3, learning_rate=0.05))]:
        m.fit(Xtr, ytr)
        b, a, ac = score(m.predict_proba(Xte)[:, 1])
        out[name] = {"brier": round(b, 4), "auc": round(a, 3), "acc": round(ac, 3)}
    return out


def main():
    bdir = sys.argv[1]
    N = int(sys.argv[2]) if len(sys.argv) > 2 else 12
    horizons = [int(x) for x in sys.argv[3].split(",")] if len(sys.argv) > 3 else [1, 3, 6, 12, 24]
    coins = ("btc", "eth", "sol", "xrp")
    # build per-coin features once
    percoin = {}
    for c in coins:
        rows = json.load(open(os.path.join(bdir, f"{c}_5m.json")))
        percoin[c] = (rows, *features(rows, N))
    print(f"N={N} lags, {sum(len(v[0]) for v in percoin.values())} total bars, walk-forward 70/30\n")
    print(f"{'horizon':>8} {'coin':>6} {'logreg AUC/Brier':>18} {'gbm AUC/Brier':>16} {'up-rate':>8}")
    results = {"N": N, "horizons": {}}
    for H in horizons:
        # pool all coins for a combined model too
        Xall, yall = [], []
        for c in coins:
            rows, X, closes, ts = percoin[c]
            # target: sign of close[i-1+H] − close[i-1]; drop last H
            Xc, yc = [], []
            for k in range(len(X) - H):
                fut = rows[N + k - 1 + H][4]  # close H bars ahead of feature's anchor
                yc.append(1 if fut >= closes[k] else 0)
                Xc.append(X[k])
            r = evaluate(Xc, yc)
            print(f"{H:>8} {c:>6} {r['logreg']['auc']:.3f}/{r['logreg']['brier']:.4f}   {r['gbm']['auc']:.3f}/{r['gbm']['brier']:.4f}  {r['test_up_rate']}")
            Xall += Xc; yall += yc
        rp = evaluate(Xall, yall)
        print(f"{H:>8} {'POOL':>6} {rp['logreg']['auc']:.3f}/{rp['logreg']['brier']:.4f}   {rp['gbm']['auc']:.3f}/{rp['gbm']['brier']:.4f}  {rp['test_up_rate']}\n")
        results["horizons"][H] = rp
    here = os.path.dirname(os.path.abspath(__file__))
    os.makedirs(os.path.join(here, "ml_runs"), exist_ok=True)
    json.dump(results, open(os.path.join(here, "ml_runs", f"horizon_N{N}.json"), "w"), indent=1)
    print("saved ml_runs/horizon_N%d.json" % N)


if __name__ == "__main__":
    main()
