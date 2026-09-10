"""mrecev -> parquet: trades + book-events (top3) ; mrec -> RES/BAR/RB."""
import sys, os, gzip, json, glob
from concurrent.futures import ProcessPoolExecutor
import pandas as pd, numpy as np

ROOT = "/Users/maxkuzmentsov/development/projects/my/hummingbot/hummingbot-infra/every-tick-single/data/mrec"
OUT  = os.environ.get('MREC_PQ', 'pq')

def do_ev(path):
    coin = os.path.basename(path).split("-")[0]
    trades, books = [], []
    with gzip.open(path, "rt") as f:
        for l in f:
            try: d = json.loads(l)
            except Exception: continue
            et = d.get("et")
            if et == "last_trade_price":
                m = d["m"]
                trades.append((coin, d.get("ws"), d.get("tok"),
                               float(m["price"]), float(m["size"]),
                               m.get("side"), int(m["timestamp"])/1000.0,
                               d["t"], m.get("transaction_hash","")))
            elif et == "book":
                m = d["m"]; b = m.get("bids") or []; a = m.get("asks") or []
                books.append((coin, d.get("ws"), d.get("tok"), d["t"],
                              int(m["timestamp"])/1000.0,
                              b[0][0] if b else np.nan, b[0][1] if b else np.nan,
                              a[0][0] if a else np.nan, a[0][1] if a else np.nan,
                              sum(x[1] for x in b), sum(x[1] for x in a), m.get("hash")))
    tr = pd.DataFrame(trades, columns=["coin","ws","tok","px","sz","side","mts","t","tx"])
    bk = pd.DataFrame(books, columns=["coin","ws","tok","t","mts","b0","b0s","a0","a0s","bsum","asum","hash"])
    return tr, bk

def do_snapmeta(path):
    """RES / BAR / RB rows from the main mrec file (cheap: skip SNAP)."""
    coin = os.path.basename(path).split("-")[0]
    res, bar, rb = [], [], []
    with gzip.open(path, "rt") as f:
        for l in f:
            if '"SNAP"' in l: continue
            try: d = json.loads(l)
            except Exception: continue
            e = d.get("ev")
            if e == "RES": res.append((coin, d["ws"], d["win"], d["t"], d.get("post_secs")))
            elif e == "BAR": bar.append((coin, d["ws"], d.get("end"), d.get("slug"), d.get("up"), d.get("down")))
            elif e == "RB": rb.append((coin, d["ws"], d["tok"], d["t"], bool(d.get("match")), d.get("tick")))
    return (pd.DataFrame(res, columns=["coin","ws","win","t","post_secs"]),
            pd.DataFrame(bar, columns=["coin","ws","end","slug","up","down"]),
            pd.DataFrame(rb,  columns=["coin","ws","tok","t","match","tick"]))

if __name__ == "__main__":
    which = sys.argv[1]
    coins = ["btc","eth","sol","xrp","bnb","doge","hype","zec"]
    if which == "ev":
        files = [p for c in coins for p in sorted(glob.glob(f"{ROOT}/{c}/{c}-mrecev-*.jsonl.gz"))]
        print(len(files), "ev files", flush=True)
        TR, BK = [], []
        with ProcessPoolExecutor(12) as ex:
            for i,(tr,bk) in enumerate(ex.map(do_ev, files, chunksize=1)):
                TR.append(tr); BK.append(bk)
                if i % 100 == 0: print(i, flush=True)
        pd.concat(TR, ignore_index=True).to_parquet(f"{OUT}/trades.parquet", index=False)
        pd.concat(BK, ignore_index=True).to_parquet(f"{OUT}/bookev.parquet", index=False)
    else:
        files = [p for c in coins for p in sorted(glob.glob(f"{ROOT}/{c}/{c}-mrec-*.jsonl.gz"))]
        print(len(files), "meta files", flush=True)
        R,B,Q = [],[],[]
        with ProcessPoolExecutor(12) as ex:
            for i,(r,b,q) in enumerate(ex.map(do_snapmeta, files, chunksize=1)):
                R.append(r); B.append(b); Q.append(q)
                if i % 100 == 0: print(i, flush=True)
        pd.concat(R, ignore_index=True).to_parquet(f"{OUT}/res.parquet", index=False)
        pd.concat(B, ignore_index=True).to_parquet(f"{OUT}/bar.parquet", index=False)
        pd.concat(Q, ignore_index=True).to_parquet(f"{OUT}/rb.parquet", index=False)
    print("done")
