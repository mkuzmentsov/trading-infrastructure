#!/usr/bin/env python3
"""Fetch 5m futures POSITIONING indicators (30-day max history) for ml_positioning.py:
global long/short account ratio, top-trader position ratio, futures taker buy/sell
ratio, open interest. Output: {coin}_pos.json = {ts_str: {gls,tls,taker,oi}}.
Usage: python3 fetch_binance_positioning.py <out_dir> [end_ms]"""
import json, os, sys, time, urllib.request

def get(u):
    return json.loads(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "curl/8"}), timeout=25).read())

def page(base, ep, sym, end):
    rows, e = [], end
    for _ in range(20):
        r = get(f"{base}/{ep}?symbol={sym}&period=5m&limit=500&endTime={e}")
        if not r:
            break
        rows = r + rows; e = int(r[0]["timestamp"]) - 1; time.sleep(0.12)
        if len(r) < 500:
            break
    return rows

def main():
    out = sys.argv[1]; os.makedirs(out, exist_ok=True)
    end = int(sys.argv[2]) if len(sys.argv) > 2 else int(time.time() * 1000)
    base = "https://fapi.binance.com/futures/data"
    for sym, coin in [('BTCUSDT','btc'),('ETHUSDT','eth'),('SOLUSDT','sol'),('XRPUSDT','xrp')]:
        d = {}
        for ep, key in [("globalLongShortAccountRatio","gls"), ("topLongShortPositionRatio","tls"),
                        ("takerlongshortRatio","taker"), ("openInterestHist","oi")]:
            for x in page(base, ep, sym, end):
                ts = int(x["timestamp"]) // 1000; e = d.setdefault(ts, {})
                if key == "taker": e["taker"] = float(x["buySellRatio"])
                elif key == "oi": e["oi"] = float(x["sumOpenInterest"])
                else: e[key] = float(x["longShortRatio"])
        json.dump({str(k): v for k, v in d.items()}, open(os.path.join(out, f"{coin}_pos.json"), "w"))
        print(f"{coin}: {len(d)} points")

if __name__ == "__main__":
    main()
