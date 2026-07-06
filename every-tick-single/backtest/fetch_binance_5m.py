#!/usr/bin/env python3
"""Fetch rich 5m klines (with number-of-trades + taker-buy volume) for the horizon
model. Compact fields: [openT_s, open, high, low, close, volume, ntrades, takerbuybase].
Usage: python3 fetch_binance_5m.py <out_dir> [days=62] [end_ms=<now>]"""
import json, os, sys, time, urllib.request

def get(u):
    return json.loads(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "curl/8"}), timeout=25).read())

def main():
    out = sys.argv[1]; os.makedirs(out, exist_ok=True)
    days = int(sys.argv[2]) if len(sys.argv) > 2 else 62
    end = int(sys.argv[3]) if len(sys.argv) > 3 else int(time.time() * 1000)
    pages = max(1, round(days * 288 / 1000))
    for sym, coin in [('BTCUSDT','btc'),('ETHUSDT','eth'),('SOLUSDT','sol'),('XRPUSDT','xrp')]:
        rows, e = [], end
        for _ in range(pages):
            k = get(f"https://api.binance.com/api/v3/klines?symbol={sym}&interval=5m&endTime={e}&limit=1000")
            if not k:
                break
            rows = k + rows; e = k[0][0] - 1; time.sleep(0.15)
        comp = [[int(r[0]/1000), float(r[1]), float(r[2]), float(r[3]), float(r[4]),
                 float(r[5]), int(r[8]), float(r[9])] for r in rows]
        json.dump(comp, open(os.path.join(out, f"{coin}_5m.json"), "w"))
        print(f"{coin}: {len(comp)} bars")

if __name__ == "__main__":
    main()
