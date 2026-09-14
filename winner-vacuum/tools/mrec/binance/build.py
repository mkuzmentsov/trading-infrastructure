"""Research panel over the window where Binance exists (brec live 2026-09-13 17:40 UTC).
Per (coin, bar, tl): the LIVE Chainlink estimator, the unobserved tail it is guessing,
and the Binance deviation at that instant."""
import os, sys, gzip, json, glob, time
from concurrent.futures import ProcessPoolExecutor
import pandas as pd, numpy as np

ROOT = "/Users/maxkuzmentsov/development/projects/my/hummingbot/hummingbot-infra/every-tick-single/data/mrec"
VEN  = "/Users/maxkuzmentsov/development/projects/my/hummingbot/hummingbot-infra/every-tick-single/data/pq-venue/bin/bookTicker"
COINS = ["btc","eth","sol","xrp","bnb","doge"]          # hype has no Binance spot; zec is not traded
HOURS = [h for h in (["20260913-%02d"%i for i in range(14,24)] + ["20260914-%02d"%i for i in range(0,20)])]

def scan(path):
    """one pass: continuous chainlink ticks (all roles) + RES + the cur-role book."""
    coin = os.path.basename(path).split("-")[0]
    cl, res, cur = {}, [], []
    with gzip.open(path, "rt") as f:
        for l in f:
            if '"RES"' in l:
                d = json.loads(l)
                if d.get("ev") == "RES": res.append((coin, d["ws"], d["win"]))
                continue
            if '"SNAP"' not in l: continue
            try: d = json.loads(l)
            except Exception: continue
            c, ts = d.get("cl"), d.get("cl_ts")
            if c is not None and ts is not None: cl.setdefault(int(ts), float(c))
            if d.get("role") != "cur": continue
            tl = d.get("tl")
            if tl is None or not (0 <= tl <= 70): continue      # only the settlement window
            cur.append((coin, d["ws"], d["t"], tl, d.get("cl_ts"),
                        d.get("ua"), d.get("ub"), d.get("da"), d.get("db"),
                        d.get("uas"), d.get("das"), d.get("spot")))
    return coin, cl, res, cur

if __name__ == "__main__":
    files = [f"{ROOT}/{c}/{c}-mrec-{h}.jsonl.gz" for c in COINS for h in HOURS]
    files = [f for f in files if os.path.exists(f)]
    print(len(files), "mrec files", flush=True)
    CL = {c: {} for c in COINS}; RES = []; CUR = []
    with ProcessPoolExecutor(10) as ex:
        for i, (coin, cl, res, cur) in enumerate(ex.map(scan, files, chunksize=1)):
            CL[coin].update(cl); RES += res; CUR += cur
            if i % 30 == 0: print(" ", i, flush=True)
    cl = pd.concat([pd.DataFrame({"coin": c, "cl_ts": list(v), "cl": list(v.values())})
                    for c, v in CL.items() if v], ignore_index=True)
    cl.to_parquet("pq/cl.parquet", index=False)
    pd.DataFrame(RES, columns=["coin","ws","win"]).drop_duplicates().to_parquet("pq/res.parquet", index=False)
    cu = pd.DataFrame(CUR, columns=["coin","ws","t","tl","cl_ts","ua","ub","da","db","uas","das","spot"])
    for k in ("ua","ub","da","db","uas","das","spot","cl_ts"): cu[k] = pd.to_numeric(cu[k], errors="coerce")
    cu.to_parquet("pq/snapcur.parquet", index=False)
    print("cl", len(cl), "res", len(RES), "cur", len(cu), flush=True)

    B = []
    for c in COINS:
        fs = sorted(glob.glob(f"{VEN}/{c}-*.parquet"))
        fs = [f for f in fs if any(h in f for h in HOURS)]
        if not fs: print("no binance for", c); continue
        d = pd.concat([pd.read_parquet(f, columns=["t","bid","ask"]) for f in fs], ignore_index=True)
        d["mid"] = (d.bid + d.ask) / 2
        d = d[["t","mid"]].sort_values("t")
        d.insert(0, "coin", c); B.append(d)
        print(" binance", c, len(d), flush=True)
    pd.concat(B, ignore_index=True).to_parquet("pq/bin.parquet", index=False)
    print("done")
