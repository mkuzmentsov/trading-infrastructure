#!/usr/bin/env python3
"""
/Users/maxkuzmentsov/development/projects/my/hummingbot/hummingbot-infra/research-hype/hlhist.py

Backfill everything the Hyperliquid info API serves historically, to parquet.

  OUT: /Users/maxkuzmentsov/development/projects/my/hummingbot/hummingbot-infra/every-tick-single/data/hl-hist/
       candles/<coin>-<interval>.parquet     t,kT,o,h,l,c,v,n   (t = open ms, UTC)
       funding/<coin>.parquet                time,fundingRate,premium

HARD FACT discovered by probe (research-hype/probe_retention.txt):
  candleSnapshot retention is a ROLLING 5000 CANDLES PER INTERVAL, not a time
  window and not full history.  1m => ~3.5 days.  Only 4h/1d/1w reach listing.
  There is NO 22-month 1-minute HL history.  Do not plan around one.

Usage:  python3 hlhist.py [--coins HYPE,BTC,...] [--intervals 1m,5m,...]
"""
import argparse, datetime as dt, json, os, sys, time, urllib.request
import pyarrow as pa, pyarrow.parquet as pq

URL = "https://api.hyperliquid.xyz/info"
OUT = "/Users/maxkuzmentsov/development/projects/my/hummingbot/hummingbot-infra/every-tick-single/data/hl-hist"
LISTING = 1733270400000            # 2024-12-04, before HYPE's first candle
CAP = 5000                          # server-side row cap per candleSnapshot
FCAP = 500                          # server-side row cap per fundingHistory

def post(payload, tries=6):
    last = None
    for i in range(tries):
        try:
            r = urllib.request.Request(URL, data=json.dumps(payload).encode(),
                                       headers={"Content-Type": "application/json"})
            return json.load(urllib.request.urlopen(r, timeout=45))
        except Exception as e:
            last = e; time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"info API failed after {tries}: {last} :: {payload}")

IV_MS = {"1m":60_000,"3m":180_000,"5m":300_000,"15m":900_000,"30m":1_800_000,
         "1h":3_600_000,"2h":7_200_000,"4h":14_400_000,"8h":28_800_000,
         "12h":43_200_000,"1d":86_400_000,"3d":259_200_000,"1w":604_800_000}

def fetch_candles(coin, iv):
    """Walk forward from listing in <=CAP-candle chunks. Returns sorted unique rows."""
    step = IV_MS[iv] * (CAP - 5)
    now = int(time.time() * 1000)
    t, seen, out = LISTING, set(), []
    empty_run = 0
    while t < now:
        d = post({"type":"candleSnapshot","req":{"coin":coin,"interval":iv,
                                                 "startTime":t,"endTime":min(t+step, now)}})
        if d:
            empty_run = 0
            for r in d:
                if r["t"] in seen: continue
                seen.add(r["t"]); out.append(r)
            # server truncates to the LAST CAP rows of the range; if we got a full
            # page, resume from the last row we actually received, not t+step.
            if len(d) >= CAP - 5:
                t = max(t + IV_MS[iv], d[-1]["t"] + IV_MS[iv]); continue
        else:
            empty_run += 1
        t += step
    out.sort(key=lambda r: r["t"])
    return out

def write_candles(coin, iv, rows):
    if not rows: return 0, None, None
    tbl = pa.table({
        "t":  pa.array([r["t"] for r in rows], pa.int64()),
        "kT": pa.array([r["T"] for r in rows], pa.int64()),
        "o":  pa.array([float(r["o"]) for r in rows], pa.float64()),
        "h":  pa.array([float(r["h"]) for r in rows], pa.float64()),
        "l":  pa.array([float(r["l"]) for r in rows], pa.float64()),
        "c":  pa.array([float(r["c"]) for r in rows], pa.float64()),
        "v":  pa.array([float(r["v"]) for r in rows], pa.float64()),
        "n":  pa.array([int(r["n"]) for r in rows], pa.int64()),
    })
    p = f"{OUT}/candles"; os.makedirs(p, exist_ok=True)
    safe = coin.replace("/", "_").replace("@", "at")
    pq.write_table(tbl, f"{p}/{safe}-{iv}.parquet", compression="zstd")
    return len(rows), rows[0]["t"], rows[-1]["t"]

def fetch_funding(coin):
    t, seen, out = LISTING, set(), []
    now = int(time.time() * 1000)
    while t < now:
        d = post({"type":"fundingHistory","coin":coin,"startTime":t,"endTime":now})
        if not d: break
        new = [r for r in d if r["time"] not in seen]
        for r in new: seen.add(r["time"]); out.append(r)
        if len(d) < FCAP: break
        nxt = d[-1]["time"] + 1
        if nxt <= t: break
        t = nxt
    out.sort(key=lambda r: r["time"])
    return out

def write_funding(coin, rows):
    if not rows: return 0, None, None
    tbl = pa.table({
        "time":        pa.array([r["time"] for r in rows], pa.int64()),
        "fundingRate": pa.array([float(r["fundingRate"]) for r in rows], pa.float64()),
        "premium":     pa.array([float(r["premium"]) for r in rows], pa.float64()),
    })
    p = f"{OUT}/funding"; os.makedirs(p, exist_ok=True)
    pq.write_table(tbl, f"{p}/{coin}.parquet", compression="zstd")
    return len(rows), rows[0]["time"], rows[-1]["time"]

def fmt(ms): return dt.datetime.fromtimestamp(ms/1000, dt.UTC).strftime("%Y-%m-%d %H:%M") if ms else "-"

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--coins", default="HYPE,BTC,ETH,SOL,XRP,DOGE,@107")
    ap.add_argument("--intervals", default="1m,5m,15m,30m,1h,2h,4h,1d")
    ap.add_argument("--no-funding", action="store_true")
    a = ap.parse_args()
    coins = a.coins.split(","); ivs = a.intervals.split(",")
    print(f"{'coin':8s} {'iv':4s} {'rows':>7s}  span")
    for c in coins:
        for iv in ivs:
            try:
                n, f, l = write_candles(c, iv, fetch_candles(c, iv))
            except Exception as e:
                print(f"{c:8s} {iv:4s}  ERROR {e}"); continue
            print(f"{c:8s} {iv:4s} {n:7d}  {fmt(f)} -> {fmt(l)}", flush=True)
        if not a.no_funding and not c.startswith("@"):
            try:
                n, f, l = write_funding(c, fetch_funding(c))
                print(f"{c:8s} fund {n:7d}  {fmt(f)} -> {fmt(l)}", flush=True)
            except Exception as e:
                print(f"{c:8s} fund ERROR {e}")
