#!/usr/bin/env python3
"""pm-scout book check — CLOB depth for candidate tokens (public, no creds).
Usage: python3 book.py <token_id> [<token_id> ...] [--size 100]
Prints mid/spread/depth-at-±2c and whether `--size` shares fit inside 2c."""
from __future__ import annotations

import argparse
import json
import urllib.request

CLOB = "https://clob.polymarket.com"


def book(token_id: str) -> dict | None:
    req = urllib.request.Request(f"{CLOB}/book?token_id={token_id}",
                                 headers={"User-Agent": "pm-scout/1.0"})
    try:
        return json.loads(urllib.request.urlopen(req, timeout=15).read())
    except Exception as exc:
        print(f"  book fetch failed: {exc}")
        return None


def summarize(token_id: str, size: float) -> None:
    b = book(token_id)
    if not b:
        return
    bids = sorted(((float(x["price"]), float(x["size"])) for x in b.get("bids", [])),
                  reverse=True)
    asks = sorted(((float(x["price"]), float(x["size"])) for x in b.get("asks", [])))
    if not bids or not asks:
        print(f"{token_id[:16]}…  EMPTY BOOK bids={len(bids)} asks={len(asks)}")
        return
    bb, ba = bids[0][0], asks[0][0]
    mid = (bb + ba) / 2
    d_bid = sum(s for p, s in bids if p >= bb - 0.02)
    d_ask = sum(s for p, s in asks if p <= ba + 0.02)
    fits = "OK" if min(d_bid, d_ask) >= size else "THIN"
    print(f"{token_id[:16]}…  bid={bb:.3f} ask={ba:.3f} mid={mid:.3f} "
          f"spread={ba-bb:.3f}  depth±2c: bid={d_bid:,.0f} ask={d_ask:,.0f} "
          f"[{fits} for {size:.0f}sh]")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("tokens", nargs="+")
    ap.add_argument("--size", type=float, default=100)
    a = ap.parse_args()
    for t in a.tokens:
        summarize(t, a.size)
