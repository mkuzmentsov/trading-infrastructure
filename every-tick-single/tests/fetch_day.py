#!/usr/bin/env python3
"""Fetch one date's rotated event archives from the running pods + klines.
Usage: python3 tests/fetch_day.py <YYYY-MM-DD>   (kube context must be Hetzner)
Data files for dates after 2026-07-03 are gitignored (30-40MB/day with prints);
only expected_metrics.json baselines are committed."""
import json, gzip, os, subprocess, sys, urllib.request
date = sys.argv[1]
HERE = os.path.dirname(os.path.abspath(__file__))
d = os.path.join(HERE, "data", date); os.makedirs(d, exist_ok=True)
for c in ("btc", "eth", "sol", "xrp"):
    out = subprocess.run(["kubectl", "exec", "-n", "every-tick-single",
        f"deploy/{c}-every-tick-single", "--", "cat",
        f"/app/logs/logs-training-events.jsonl.{date}.gz"], capture_output=True)
    if out.returncode == 0 and out.stdout:
        open(os.path.join(d, f"{c}_snap.jsonl.gz"), "wb").write(out.stdout)
        print(c, len(out.stdout), "bytes")
    else:
        print(c, "MISSING", out.stderr.decode()[:80])
import datetime as dt
t0 = int(dt.datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc).timestamp()*1000)
kl = {}
for sym, coin in [('BTCUSDT','btc'),('ETHUSDT','eth'),('SOLUSDT','sol'),('XRPUSDT','xrp')]:
    req = urllib.request.Request(
        f"https://api.binance.com/api/v3/klines?symbol={sym}&interval=5m&startTime={t0}&endTime={t0+86400000}&limit=300",
        headers={"User-Agent": "curl/8"})
    kl[coin] = [[int(x[0]/1000), float(x[1]), float(x[4])] for x in json.loads(urllib.request.urlopen(req, timeout=20).read())]
gzip.open(os.path.join(d, "klines_5m.json.gz"), "wt").write(json.dumps(kl))
print("klines ok")
