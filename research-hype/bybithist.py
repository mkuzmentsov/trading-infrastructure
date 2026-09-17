#!/usr/bin/env python3
"""
/Users/maxkuzmentsov/development/projects/my/hummingbot/hummingbot-infra/research-hype/bybithist.py

HYPE deep history from BYBIT linear perp (HYPEUSDT).

WHY THIS EXISTS: Hyperliquid's own candleSnapshot keeps only a rolling ~5000
candles per interval, so HL serves 1m for ~3.5 days and only 4h/1d reach the
2024-12-05 listing.  Bybit listed HYPEUSDT perp on the SAME DAY and serves 1m
klines, funding and hourly open interest all the way back.

⚠️  DIFFERENT INSTRUMENT, DIFFERENT BOOK.  This is a *proxy* history panel.
    Never join it row-wise to the HL tick tape, and never compare price LEVELS
    across the two venues — only each venue's own changes (the Chainlink /
    Binance +4.71 bps lesson).  HL is HYPE's home venue and almost certainly
    leads; treat Bybit as a regime/vol/seasonality reference, not as HL.

OUT: /Users/maxkuzmentsov/development/projects/my/hummingbot/hummingbot-infra/every-tick-single/data/hl-hist/bybit/
       kline/<SYM>-<iv>.parquet    t,o,h,l,c,v,turnover
       funding/<SYM>.parquet       time,fundingRate
       oi/<SYM>-<iv>.parquet       time,openInterest
"""
import argparse, datetime as dt, json, os, time, urllib.request
import pyarrow as pa, pyarrow.parquet as pq

OUT = "/Users/maxkuzmentsov/development/projects/my/hummingbot/hummingbot-infra/every-tick-single/data/hl-hist/bybit"
LISTING = 1733356800000          # 2024-12-05
IV_MS = {"1":60_000,"5":300_000,"15":900_000,"60":3_600_000,"240":14_400_000,"D":86_400_000}

def get(url, tries=6):
    last=None
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent":"research"}), timeout=40) as r:
                d = json.load(r)
            if d.get("retCode") == 0: return d["result"]
            last = d.get("retMsg")
        except Exception as e: last = e
        time.sleep(1.0 + i)
    raise RuntimeError(f"bybit failed: {last} :: {url}")

def klines(sym, iv, start=LISTING):
    step = IV_MS[iv] * 1000
    now = int(time.time()*1000); t = start; seen=set(); out=[]
    while t < now:
        r = get(f"https://api.bybit.com/v5/market/kline?category=linear&symbol={sym}"
                f"&interval={iv}&start={t}&end={min(t+step,now)}&limit=1000")
        L = r["list"]                      # newest-first
        for k in L:
            ts=int(k[0])
            if ts in seen: continue
            seen.add(ts); out.append(k)
        t += step
        time.sleep(0.06)
    out.sort(key=lambda k:int(k[0]))
    return out

def w_kl(sym, iv, L):
    if not L: return 0,None,None
    os.makedirs(f"{OUT}/kline", exist_ok=True)
    tbl = pa.table({"t":pa.array([int(k[0]) for k in L],pa.int64()),
                    "o":pa.array([float(k[1]) for k in L],pa.float64()),
                    "h":pa.array([float(k[2]) for k in L],pa.float64()),
                    "l":pa.array([float(k[3]) for k in L],pa.float64()),
                    "c":pa.array([float(k[4]) for k in L],pa.float64()),
                    "v":pa.array([float(k[5]) for k in L],pa.float64()),
                    "turnover":pa.array([float(k[6]) for k in L],pa.float64())})
    pq.write_table(tbl, f"{OUT}/kline/{sym}-{iv}.parquet", compression="zstd")
    return len(L), int(L[0][0]), int(L[-1][0])

def funding(sym):
    now=int(time.time()*1000); t=LISTING; seen=set(); out=[]
    while t < now:
        r = get(f"https://api.bybit.com/v5/market/funding/history?category=linear&symbol={sym}"
                f"&startTime={t}&endTime={min(t+200*3600_000*8,now)}&limit=200")
        L=r["list"]
        if not L: t += 200*3600_000*8; continue
        for k in L:
            ts=int(k["fundingRateTimestamp"])
            if ts in seen: continue
            seen.add(ts); out.append(k)
        t = max(int(k["fundingRateTimestamp"]) for k in L)+1
        time.sleep(0.06)
    out.sort(key=lambda k:int(k["fundingRateTimestamp"]))
    if not out: return 0,None,None
    os.makedirs(f"{OUT}/funding", exist_ok=True)
    tbl=pa.table({"time":pa.array([int(k["fundingRateTimestamp"]) for k in out],pa.int64()),
                  "fundingRate":pa.array([float(k["fundingRate"]) for k in out],pa.float64())})
    pq.write_table(tbl,f"{OUT}/funding/{sym}.parquet",compression="zstd")
    return len(out), out[0]["fundingRateTimestamp"], out[-1]["fundingRateTimestamp"]

def oi(sym, iv="1h"):
    ivms={"5min":300_000,"15min":900_000,"1h":3_600_000,"4h":14_400_000,"1d":86_400_000}[iv]
    now=int(time.time()*1000); t=LISTING; seen=set(); out=[]
    while t < now:
        r = get(f"https://api.bybit.com/v5/market/open-interest?category=linear&symbol={sym}"
                f"&intervalTime={iv}&startTime={t}&endTime={min(t+200*ivms,now)}&limit=200")
        L=r.get("list") or []
        for k in L:
            ts=int(k["timestamp"])
            if ts in seen: continue
            seen.add(ts); out.append(k)
        t += 200*ivms
        time.sleep(0.06)
    out.sort(key=lambda k:int(k["timestamp"]))
    if not out: return 0,None,None
    os.makedirs(f"{OUT}/oi", exist_ok=True)
    tbl=pa.table({"time":pa.array([int(k["timestamp"]) for k in out],pa.int64()),
                  "openInterest":pa.array([float(k["openInterest"]) for k in out],pa.float64())})
    pq.write_table(tbl,f"{OUT}/oi/{sym}-{iv}.parquet",compression="zstd")
    return len(out), int(out[0]["timestamp"]), int(out[-1]["timestamp"])

def fmt(x): return dt.datetime.fromtimestamp(int(x)/1000, dt.UTC).strftime("%Y-%m-%d %H:%M") if x else "-"

if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--full", default="HYPEUSDT")            # 1m + 5m + 1h + D + funding + oi
    ap.add_argument("--ref",  default="BTCUSDT,ETHUSDT,SOLUSDT")  # 5m + 1h + D only
    a=ap.parse_args()
    for sym in a.full.split(","):
        for iv in ["1","5","15","60","240","D"]:
            n,f,l = w_kl(sym, iv, klines(sym, iv)); print(f"{sym:10s} kline {iv:3s} {n:8d} {fmt(f)} -> {fmt(l)}", flush=True)
        n,f,l = funding(sym); print(f"{sym:10s} funding   {n:8d} {fmt(f)} -> {fmt(l)}", flush=True)
        n,f,l = oi(sym);      print(f"{sym:10s} oi 1h     {n:8d} {fmt(f)} -> {fmt(l)}", flush=True)
    for sym in a.ref.split(","):
        for iv in ["5","60","D"]:
            n,f,l = w_kl(sym, iv, klines(sym, iv)); print(f"{sym:10s} kline {iv:3s} {n:8d} {fmt(f)} -> {fmt(l)}", flush=True)
