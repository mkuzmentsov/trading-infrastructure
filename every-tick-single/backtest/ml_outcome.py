#!/usr/bin/env python3
"""ST-1 — AI model to predict next-bar outcome, walk-forward validated.

THE test (research program ST-1): can ANY model beat a coin flip OUT OF SAMPLE?
If not, direction is unpredictable at 5m and all side-picking is retired.

Method (strict — this is the whole point):
  * Label: bar outcome UP=1 / DOWN=0.
  * Time-ordered split — train on the EARLIER bars, test on the LATER bars, never
    shuffled (shuffling leaks the future and is the classic way these look great
    in-sample and fail live). Standardize on train only.
  * Two feature sets:
      PRE-BAR  (known at bar OPEN → a true forecast): prior-bar outcomes/returns,
               trailing realized vol, hour-of-day, coin, prior early-flow.
      EARLY-BAR(known ~60s in → actionable slightly late): + first-60s cross-token
               flow imbalance + first-60s price move (the momentum feature).
  * Scored vs baselines: predict-0.5, predict-base-rate, predict-always-UP.
    Metrics: Brier (lower better; 0.25 = coin flip), AUC (0.5 = none), accuracy,
    log-loss. A model only "wins" if OOS Brier < 0.25 AND AUC > 0.5 by a margin
    that survives more data (re-run appends a RUN RECORD).

Usage: python3 ml_outcome.py <date> [<date> ...]
Requires numpy + scikit-learn (dev venv). Saves per-run JSON to ml_runs/.
"""
from __future__ import annotations
import json, math, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import experiments as X  # richer loader (prints, snaps, positions, outcome)


HIST_N = 12  # prior bars of OHLC history used by the "hist" feature set


def build_dataset(dates, root):
    """→ list of per-bar dicts sorted by time, each with features + label.
    Prior-bar features use ONLY earlier bars of the same coin (no lookahead)."""
    rows = []
    klines = {}
    for d in dates:
        dd = os.path.join(root, d)
        bars = X.load(dd)
        kl = json.load(X._open(os.path.join(dd, "klines_5m.json.gz")))
        for c, ks in kl.items():
            klines.setdefault(c, {})
            for ts, op, cl in ks:
                klines[c][ts] = (op, cl)
        for (c, cid), b in bars.items():
            if b["outcome"] not in ("UP", "DOWN") or not b["bar_ts"]:
                continue
            rows.append({"coin": c, "ts": b["bar_ts"], "bar": b,
                         "y": 1 if b["outcome"] == "UP" else 0})
    rows.sort(key=lambda r: (r["ts"], r["coin"]))
    # per-coin history for prior-bar features
    hist = {}
    coin_idx = {c: i for i, c in enumerate(("btc", "eth", "sol", "xrp"))}
    out = []
    for r in rows:
        c, ts, b = r["coin"], r["ts"], r["bar"]
        h = hist.setdefault(c, [])
        # klines-based prior returns / trailing vol (only bars strictly before ts)
        kc = klines.get(c, {})
        prev = [(t, kc[t]) for t in sorted(kc) if t < ts]
        prev_rets = [math.log(cl/op) for _, (op, cl) in prev if op > 0 and cl > 0]
        r1 = prev_rets[-1] if prev_rets else 0.0
        r3 = sum(prev_rets[-3:]) if len(prev_rets) >= 1 else 0.0
        vol = (sum(x*x for x in prev_rets[-36:]) / max(1, len(prev_rets[-36:]))) ** .5
        hour = (ts // 3600) % 24
        # prior outcomes of this coin
        y1 = h[-1] if h else 0
        y2 = h[-2] if len(h) >= 2 else 0
        # early-bar features (from THIS bar's prints/snaps, ~first 60s)
        early = [pr for pr in b["prints"] if pr[0] >= 240]
        up_v = sum(pr[3] for pr in early if pr[1] == "UP")
        dn_v = sum(pr[3] for pr in early if pr[1] == "DOWN")
        flow = (up_v - dn_v) / (up_v + dn_v) if (up_v + dn_v) else 0.0
        ss = sorted(b["snaps"], key=lambda s: -s[0])
        move = 0.0
        if len(ss) >= 2:
            open_mid = (ss[0][1] + ss[0][2]) / 2
            e = [s for s in ss if s[0] <= 240]
            if e:
                move = (e[0][1] + e[0][2]) / 2 - open_mid
        pre = [r1*100, r3*100, vol*100, math.sin(2*math.pi*hour/24),
               math.cos(2*math.pi*hour/24), coin_idx.get(c, 0), y1, y2]
        earlyf = pre + [flow, move*10]
        # HIST: pure price history — last HIST_N prior bars, NO current-bar info.
        # Per lag: intrabar log-return (close/open) and overnight gap (open vs
        # prior close), both x100. Zero-padded when history is short.
        lags = prev[-HIST_N:]   # [(ts,(open,close)), ...] ascending
        histf = []
        for j in range(HIST_N):
            idx = len(lags) - 1 - j
            if idx >= 0:
                op, cl = lags[idx][1]
                intrab = math.log(cl/op)*100 if op > 0 and cl > 0 else 0.0
                if idx - 1 >= 0:
                    prev_cl = lags[idx-1][1][1]
                    gap = math.log(op/prev_cl)*100 if op > 0 and prev_cl > 0 else 0.0
                else:
                    gap = 0.0
            else:
                intrab = gap = 0.0
            histf += [intrab, gap]
        histf += [vol*100, math.sin(2*math.pi*hour/24), math.cos(2*math.pi*hour/24),
                 coin_idx.get(c, 0)]
        out.append({"ts": ts, "coin": c, "y": r["y"], "pre": pre,
                    "early": earlyf, "hist": histf})
        h.append(r["y"])
    return out


def evaluate(rows, feat_key, train_frac=0.6):
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.ensemble import GradientBoostingClassifier
    from sklearn.preprocessing import StandardScaler
    X_all = np.array([r[feat_key] for r in rows], float)
    y = np.array([r["y"] for r in rows])
    n = len(y); cut = int(n * train_frac)
    Xtr, Xte, ytr, yte = X_all[:cut], X_all[cut:], y[:cut], y[cut:]
    sc = StandardScaler().fit(Xtr)
    Xtr, Xte = sc.transform(Xtr), sc.transform(Xte)
    res = {"n_train": int(cut), "n_test": int(n - cut),
           "test_base_up": round(float(yte.mean()), 3)}
    def score(p):
        p = np.clip(p, 1e-6, 1 - 1e-6)
        brier = float(np.mean((p - yte) ** 2))
        acc = float(np.mean((p >= 0.5) == yte))
        ll = float(-np.mean(yte*np.log(p) + (1-yte)*np.log(1-p)))
        try:
            from sklearn.metrics import roc_auc_score
            auc = float(roc_auc_score(yte, p)) if len(set(yte)) > 1 else 0.5
        except Exception:
            auc = 0.5
        return {"brier": round(brier, 4), "auc": round(auc, 3),
                "acc": round(acc, 3), "logloss": round(ll, 4)}
    res["baseline_0.5"] = score(np.full(len(yte), 0.5))
    res["baseline_baserate"] = score(np.full(len(yte), ytr.mean()))
    for name, model in [("logreg", LogisticRegression(max_iter=1000, C=1.0)),
                        ("gbm", GradientBoostingClassifier(n_estimators=60, max_depth=3, learning_rate=0.05))]:
        try:
            model.fit(Xtr, ytr)
            res[name] = score(model.predict_proba(Xte)[:, 1])
        except Exception as exc:
            res[name] = {"error": str(exc)[:60]}
    return res


def main():
    dates = sys.argv[1:]
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.join(here, "..", "tests", "data")
    rows = build_dataset(dates, root)
    print(f"dataset: {len(rows)} labeled bars, {len(dates)} days\n")
    # attribution: split early features so a priced-price-move signal can't
    # masquerade as a "model". flowonly = pre + early flow; moveonly = pre + move.
    for r in rows:
        r["flowonly"] = r["pre"] + [r["early"][8]]
        r["moveonly"] = r["pre"] + [r["early"][9]]
    out = {"dates": dates, "n": len(rows)}
    for fk in ("pre", "hist"):
        r = evaluate(rows, fk)
        out[fk] = r
        note = {"pre": "known AT OPEN (true forecast)",
                "hist": f"pure history: last {HIST_N} bars OHLC, NO current-bar info",
                "flowonly": "pre + early flow",
                "moveonly": "pre + early PRICE move (already priced)",
                "early": "pre + flow + move"}[fk]
        print(f"=== {fk.upper()} — {note} (train {r['n_train']} → test {r['n_test']}, base-UP {r['test_base_up']}) ===")
        for k in ("baseline_0.5", "baseline_baserate", "logreg", "gbm"):
            v = r[k]
            if "brier" in v:
                flag = "  <-- beats coinflip" if (v["brier"] < 0.25 and v["auc"] > 0.52) else ""
                print(f"  {k:18} Brier={v['brier']} AUC={v['auc']} acc={v['acc']} logloss={v['logloss']}{flag}")
        print()
    os.makedirs(os.path.join(here, "ml_runs"), exist_ok=True)
    tag = "_".join(dates)
    json.dump(out, open(os.path.join(here, "ml_runs", f"{tag}.json"), "w"), indent=1)
    print("saved ml_runs/" + tag + ".json")


if __name__ == "__main__":
    main()
