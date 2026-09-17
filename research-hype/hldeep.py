#!/usr/bin/env python3
"""
/Users/maxkuzmentsov/development/projects/my/hummingbot/hummingbot-infra/research-hype/hldeep.py

Deep candle backfill for Hyperliquid, working around a MEASURED API pathology.

THE PATHOLOGY (probe evidence in DATA.md):
  `candleSnapshot` returns SPURIOUS EMPTY responses, non-monotonically in the
  request-range width.  e.g. HYPE 2h starting 2025-06-01 returned
      1d:12  2d:24  4d:48  8d:96  16d:192  32d:0  64d:83  128d:851  256d:2387
  A single pass therefore UNDER-reads history and looks like a hard retention
  wall when it is not.  Fix: walk backward in SMALL windows and retry each
  empty window several times, with a couple of alternate widths, before
  believing "no data".  Union everything; dedupe on open time.

  (1m / 5m are empty at EVERY width in old months -> that wall is real.)

Usage: python3 hldeep.py --coins HYPE --intervals 1h,2h,4h --win-days 12
"""
import argparse, datetime as dt, json, os, time, urllib.request
import pyarrow as pa, pyarrow.parquet as pq

URL="https://api.hyperliquid.xyz/info"
OUT="/Users/maxkuzmentsov/development/projects/my/hummingbot/hummingbot-infra/every-tick-single/data/hl-hist"
LISTING=1733270400000
D=86400_000
IV_MS={"1m":60_000,"5m":300_000,"15m":900_000,"30m":1_800_000,"1h":3_600_000,
       "2h":7_200_000,"4h":14_400_000,"8h":28_800_000,"12h":43_200_000,"1d":86_400_000}

def post(p, tries=4):
    for i in range(tries):
        try:
            r=urllib.request.Request(URL,data=json.dumps(p).encode(),headers={"Content-Type":"application/json"})
            return json.load(urllib.request.urlopen(r,timeout=45))
        except Exception:
            time.sleep(1.0+i)
    return None

def snap(coin, iv, a, b):
    return post({"type":"candleSnapshot","req":{"coin":coin,"interval":iv,"startTime":int(a),"endTime":int(b)}})

def deep(coin, iv, win_days, empty_retries=3):
    """Walk backward from now to listing in win_days windows; retry empties."""
    now=int(time.time()*1000); W=win_days*D
    got={}; b=now; empty_windows=0
    while b > LISTING:
        a=max(LISTING, b-W)
        rows=None
        # attempt: nominal width, then half, then double — the pathology is width-dependent
        for width in (W, W//2, W*2):
            for k in range(empty_retries):
                d=snap(coin, iv, max(LISTING, b-width), b)
                if d: rows=d; break
                time.sleep(0.25)
            if rows: break
        if rows:
            for r in rows: got[r["t"]]=r
            empty_windows=0
        else:
            empty_windows+=1
            if empty_windows>=6:      # 6 consecutive genuinely-empty windows = real wall
                break
        b=a; time.sleep(0.08)
    return [got[k] for k in sorted(got)]

def write(coin, iv, rows):
    if not rows: return 0,None,None
    os.makedirs(f"{OUT}/candles",exist_ok=True)
    safe=coin.replace("/","_").replace("@","at")
    t=pa.table({"t":pa.array([r["t"] for r in rows],pa.int64()),
                "kT":pa.array([r["T"] for r in rows],pa.int64()),
                "o":pa.array([float(r["o"]) for r in rows],pa.float64()),
                "h":pa.array([float(r["h"]) for r in rows],pa.float64()),
                "l":pa.array([float(r["l"]) for r in rows],pa.float64()),
                "c":pa.array([float(r["c"]) for r in rows],pa.float64()),
                "v":pa.array([float(r["v"]) for r in rows],pa.float64()),
                "n":pa.array([int(r["n"]) for r in rows],pa.int64())})
    pq.write_table(t,f"{OUT}/candles/{safe}-{iv}.parquet",compression="zstd")
    return len(rows), rows[0]["t"], rows[-1]["t"]

def f(x): return dt.datetime.fromtimestamp(x/1000,dt.UTC).strftime("%Y-%m-%d %H:%M") if x else "-"

if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--coins",default="HYPE"); ap.add_argument("--intervals",default="1h,2h,4h")
    ap.add_argument("--win-days",type=int,default=12)
    a=ap.parse_args()
    for c in a.coins.split(","):
        for iv in a.intervals.split(","):
            wd={"1m":2,"5m":8,"15m":20,"30m":40,"1h":12,"2h":24,"4h":60,"1d":200}.get(iv,a.win_days)
            rows=deep(c,iv,wd)
            n,x,y=write(c,iv,rows)
            exp=int((y-x)/IV_MS[iv])+1 if n else 0
            print(f"{c:8s} {iv:3s} {n:7d} rows  {f(x)} -> {f(y)}   completeness {100*n/max(exp,1):.1f}%",flush=True)
