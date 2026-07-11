#!/usr/bin/env python3
"""Fetch ~1 month of Binance BTCUSDT 5m klines -> data.csv.
Public REST, paginated forward. Kline: [openTime,o,h,l,c,vol,closeTime,qVol,trades,tbBase,tbQuote,_]."""
import csv, json, time, urllib.request, sys

SYMBOL = sys.argv[1] if len(sys.argv) > 1 else "BTCUSDT"
INTERVAL = "5m"; DAYS = 150
BASES = ["https://api.binance.com", "https://data-api.binance.vision", "https://api.binance.us"]
OUT = sys.argv[2] if len(sys.argv) > 2 else "data.csv"

def get(base, start):
    url = f"{base}/api/v3/klines?symbol={SYMBOL}&interval={INTERVAL}&startTime={start}&limit=1000"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return json.loads(urllib.request.urlopen(req, timeout=15).read())

def now_ms():
    return int(time.time() * 1000)

base = None
for b in BASES:
    try:
        get(b, now_ms() - 3600_000); base = b; break
    except Exception as e:
        print(f"  {b} failed: {e}", file=sys.stderr)
if not base:
    sys.exit("all Binance endpoints failed")
print(f"using {base}")

start = now_ms() - DAYS * 86400_000
rows = []
while True:
    batch = get(base, start)
    if not batch:
        break
    rows += batch
    start = batch[-1][6] + 1          # next after last closeTime
    if len(batch) < 1000 or start >= now_ms():
        break
    time.sleep(0.25)

# de-dup by openTime, keep closed bars only
seen = set(); clean = []
for k in rows:
    ot = int(k[0])
    if ot in seen or int(k[6]) >= now_ms():
        continue
    seen.add(ot); clean.append(k)
clean.sort(key=lambda k: k[0])

with open(OUT, "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["openTime", "open", "high", "low", "close", "volume", "closeTime", "trades", "takerBuyBase"])
    for k in clean:
        w.writerow([k[0], k[1], k[2], k[3], k[4], k[5], k[6], k[8], k[9]])

print(f"wrote {len(clean)} bars to {OUT}  "
      f"({time.strftime('%Y-%m-%d %H:%M', time.gmtime(clean[0][0]/1000))} -> "
      f"{time.strftime('%Y-%m-%d %H:%M', time.gmtime(clean[-1][0]/1000))} UTC)")
