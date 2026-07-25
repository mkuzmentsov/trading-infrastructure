#!/usr/bin/env python3
"""pm-scout flow — insider/whale flow detector for a market (public data-api).
For each conditionId: pull recent trades, find abnormal one-sided flow —
whale prints (≥ WHALE_X × median size), buyer concentration, net imbalance,
and the price move over the window. Big smart-money entry without public news
= possible insider signal; big dump against a held side = close-warning.

Usage: python3 flow.py <conditionId> [...] [--hours 48] [--whale-x 20]
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
import urllib.parse
import urllib.request

DATA_API = "https://data-api.polymarket.com"


def trades(cond: str, hours: float) -> list[dict]:
    out, offset = [], 0
    cutoff = time.time() - hours * 3600
    for _ in range(20):
        url = f"{DATA_API}/trades?" + urllib.parse.urlencode(
            {"market": cond, "limit": 500, "offset": offset})
        req = urllib.request.Request(url, headers={"User-Agent": "pm-scout/1.0"})
        try:
            batch = json.loads(urllib.request.urlopen(req, timeout=20).read())
        except Exception as exc:
            print(f"  trades fetch failed: {exc}")
            break
        if not isinstance(batch, list) or not batch:
            break
        out.extend(batch)
        if float(batch[-1].get("timestamp") or 0) < cutoff or len(batch) < 500:
            break
        offset += len(batch)
        time.sleep(0.1)
    return [t for t in out if float(t.get("timestamp") or 0) >= cutoff]


def analyze(cond: str, hours: float, whale_x: float) -> None:
    ts = trades(cond, hours)
    if not ts:
        print(f"{cond[:14]}…  no trades in last {hours:.0f}h")
        return
    sizes = [float(t.get("size") or 0) for t in ts]
    med = statistics.median(sizes) or 1.0
    # net flow per outcome (BUY of an outcome = flow toward it)
    flows: dict[str, float] = {}
    buyers: dict[str, float] = {}
    for t in ts:
        oc = t.get("outcome") or "?"
        usd = float(t.get("size") or 0) * float(t.get("price") or 0)
        sgn = 1 if (t.get("side") or "").upper() == "BUY" else -1
        flows[oc] = flows.get(oc, 0.0) + sgn * usd
        w = t.get("proxyWallet") or t.get("pseudonym") or "?"
        if sgn > 0:
            buyers[w] = buyers.get(w, 0.0) + usd
    total_buy = sum(v for v in buyers.values()) or 1.0
    top3 = sorted(buyers.values(), reverse=True)[:3]
    conc = sum(top3) / total_buy
    whales = [t for t in ts if float(t.get("size") or 0) >= whale_x * med]
    first, last = ts[-1], ts[0]      # API returns newest-first
    px_move = {}
    for oc in set(t.get("outcome") for t in ts):
        seq = [t for t in ts if t.get("outcome") == oc]
        if len(seq) >= 2:
            px_move[oc] = float(seq[0].get("price") or 0) - float(seq[-1].get("price") or 0)

    print(f"{cond[:14]}…  {len(ts)} trades/{hours:.0f}h  med_size={med:.0f}sh  "
          f"top3-buyer-conc={conc:.0%}")
    for oc, f in sorted(flows.items(), key=lambda x: -abs(x[1])):
        print(f"   net flow {oc:>12}: ${f:>+12,.0f}   px_move={px_move.get(oc, 0):+.2f}")
    for t in sorted(whales, key=lambda x: -float(x.get("size") or 0))[:8]:
        when = time.strftime("%m-%d %H:%M", time.gmtime(float(t.get("timestamp") or 0)))
        print(f"   WHALE {when} {t.get('side','?'):>4} {float(t.get('size') or 0):>10,.0f}sh "
              f"@{float(t.get('price') or 0):.2f} [{t.get('outcome','?')}] "
              f"{(t.get('pseudonym') or t.get('proxyWallet') or '?')[:20]}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("conds", nargs="+")
    ap.add_argument("--hours", type=float, default=48)
    ap.add_argument("--whale-x", type=float, default=20)
    a = ap.parse_args()
    for c in a.conds:
        analyze(c, a.hours, a.whale_x)
