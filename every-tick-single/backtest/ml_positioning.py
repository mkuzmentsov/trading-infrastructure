#!/usr/bin/env python3
"""Does POSITIONING data (not price) predict 5m direction? The efficiency wall so
far only proves price-derived info is priced. Futures positioning is a different
information set: long/short account ratios, top-trader position ratio, futures
taker buy/sell ratio, open interest — the classic CTA/sentiment inputs.

Features per bar (last N), price + positioning merged by 5m timestamp:
  price:  log return, volume-z, taker-buy(spot) imbalance, range
  posn:   global L/S ratio + Δ, top-trader L/S ratio + Δ, futures taker ratio,
          OI level-z + Δ (OI rising with price = new longs; falling = covering)
Also runs POSN-ONLY to isolate whether positioning adds anything over price.
Target: sign of return H bars ahead. Walk-forward 70/30, vs coin-flip.

Data: scratchpad/binance/{coin}_5m.json  +  {coin}_pos.json (5m positioning).
Usage: python3 ml_positioning.py <binance_dir> [N=6] [H=1]
"""
from __future__ import annotations
import json, math, os, sys, statistics

COINS = ("btc", "eth", "sol", "xrp")


def build(coin, bdir, N, H):
    rows = json.load(open(os.path.join(bdir, f"{coin}_5m.json")))
    pos = json.load(open(os.path.join(bdir, f"{coin}_pos.json")))  # {ts_str: {...}}
    vols = [r[5] for r in rows]
    lv_m = statistics.mean(math.log(v+1) for v in vols); lv_s = statistics.pstdev(math.log(v+1) for v in vols) or 1
    ois = [pos[k]["oi"] for k in pos if "oi" in pos[k]]
    oi_m = statistics.mean(ois) if ois else 0; oi_s = statistics.pstdev(ois) or 1 if ois else 1
    Xp, Xa, y = [], [], []
    for i in range(N, len(rows) - H):
        anchor_ts = rows[i-1][0]
        # require positioning present for the anchor + lags
        pl = [pos.get(str(rows[j][0])) for j in range(i-N, i)]
        if any(p is None or "gls" not in p or "oi" not in p for p in pl):
            continue
        pfeat, allfeat = [], []
        for k, j in enumerate(range(i-N, i)):
            o,h,l,c,v = rows[j][1],rows[j][2],rows[j][3],rows[j][4],rows[j][5]
            tb = rows[j][7]
            ret = math.log(c/o)*100 if o>0 and c>0 else 0
            vz = (math.log(v+1)-lv_m)/lv_s
            sflow = (tb/v-0.5) if v>0 else 0
            rng = (h-l)/o*100 if o>0 else 0
            price_f = [ret, vz, sflow, rng]
            p = pl[k]; pprev = pl[k-1] if k>0 else p
            gls, tls, tk = p["gls"], p.get("tls",1), p.get("taker",1)
            doi = (p["oi"]-pprev["oi"])/pprev["oi"]*100 if pprev.get("oi") else 0
            dgls = gls - pprev["gls"] if pprev.get("gls") else 0
            oiz = (p["oi"]-oi_m)/oi_s
            posn_f = [gls, dgls, tls, tk, oiz, doi]
            pfeat += posn_f
            allfeat += price_f + posn_f
        Xp.append(pfeat); Xa.append(allfeat)
        y.append(1 if rows[i-1+H][4] >= rows[i-1][4] else 0)
    return Xp, Xa, y


def evaluate(X, y, frac=0.7):
    import numpy as np
    from sklearn.ensemble import GradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    from sklearn.metrics import roc_auc_score
    Xa, ya = np.array(X, float), np.array(y); n=len(ya); cut=int(n*frac)
    if cut < 50 or n-cut < 50 or len(set(ya[cut:])) < 2:
        return None
    sc = StandardScaler().fit(Xa[:cut])
    Xtr, Xte = sc.transform(Xa[:cut]), sc.transform(Xa[cut:])
    ytr, yte = ya[:cut], ya[cut:]
    r = {"n_test": int(n-cut)}
    for nm, m in [("logreg", LogisticRegression(max_iter=1000)),
                  ("gbm", GradientBoostingClassifier(n_estimators=80, max_depth=3, learning_rate=0.05))]:
        m.fit(Xtr, ytr); p = np.clip(m.predict_proba(Xte)[:,1], 1e-6, 1-1e-6)
        r[nm] = {"auc": round(float(roc_auc_score(yte,p)),3), "brier": round(float(np.mean((p-yte)**2)),4)}
    return r


def main():
    bdir = sys.argv[1]
    N = int(sys.argv[2]) if len(sys.argv)>2 else 6
    H = int(sys.argv[3]) if len(sys.argv)>3 else 1
    coins = [c for c in COINS if os.path.exists(os.path.join(bdir, f"{c}_pos.json"))]
    print(f"positioning experiment  N={N} lags  H={H} bars ahead  coins={coins}\n")
    print(f"{'coin':>6} {'POSN-only AUC':>26} {'PRICE+POSN AUC':>26}")
    Pp, Pa, Y = [], [], []
    for c in coins:
        Xp, Xa, y = build(c, bdir, N, H)
        rp = evaluate(Xp, y); ra = evaluate(Xa, y)
        Pp += Xp; Pa += Xa; Y += y
        pf = f"lr {rp['logreg']['auc']} gbm {rp['gbm']['auc']}" if rp else "-"
        af = f"lr {ra['logreg']['auc']} gbm {ra['gbm']['auc']}" if ra else "-"
        print(f"{c:>6} {pf:>26} {af:>26}  (n{len(y)})")
    rp, ra = evaluate(Pp, Y), evaluate(Pa, Y)
    print(f"{'POOL':>6} {f'''lr {rp['logreg']['auc']} gbm {rp['gbm']['auc']}''':>26} {f'''lr {ra['logreg']['auc']} gbm {ra['gbm']['auc']}''':>26}  (n{len(Y)})")
    here = os.path.dirname(os.path.abspath(__file__))
    os.makedirs(os.path.join(here,"ml_runs"), exist_ok=True)
    json.dump({"N":N,"H":H,"posn_only":rp,"price_posn":ra},
              open(os.path.join(here,"ml_runs",f"positioning_N{N}_H{H}.json"),"w"), indent=1)
    print("\nsaved ml_runs/positioning_N%d_H%d.json" % (N,H))


if __name__ == "__main__":
    main()
