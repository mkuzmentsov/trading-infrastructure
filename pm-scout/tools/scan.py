#!/usr/bin/env python3
"""pm-scout market scanner — pull ALL active Polymarket markets (public Gamma
API, no creds), save full JSON snapshot, print a compact digest with four
ranked views: newest / closing-soon / top-volume / rewards-carrying.

Usage:
  python3 scan.py --digest [--min-liquidity 1000] [--max-pages 40] [--out runs/]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request

GAMMA = "https://gamma-api.polymarket.com"


def _get(path: str, params: dict) -> list | dict:
    url = f"{GAMMA}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "pm-scout/1.0"})
    return json.loads(urllib.request.urlopen(req, timeout=20).read())


def _f(x, default=0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


# High-level category tag IDs (Gamma /tags/slug/<slug>) — one newest+volume pass
# each so mid-tail markets in every segment get covered under the depth cap.
CATEGORIES = {
    "Politics": 2, "Crypto": 21, "Sports": 1, "Business": 107, "Economy": 100328,
    "Geopolitics": 100265, "World": 101970, "Culture": 596, "Elections": 144,
    "Middle East": 154, "AI": 439,
}


def _pages(order: str, max_pages: int, page_size: int, ascending: bool = False,
           extra: dict | None = None) -> list[dict]:
    out, offset = [], 0
    for _ in range(max_pages):
        params = {"active": "true", "closed": "false", "limit": page_size,
                  "offset": offset, "order": order,
                  "ascending": "true" if ascending else "false"}
        if extra:
            params.update(extra)
        try:
            batch = _get("/markets", params)
        except Exception:                 # API depth cap (422) or transient
            break
        if not batch:
            break
        out.extend(batch)
        offset += len(batch)
        if len(batch) < page_size:
            break
        time.sleep(0.1)
    return out


def fetch_all(max_pages: int = 40, page_size: int = 100) -> list[dict]:
    """Full-coverage sweep. Gamma caps pagination depth (~2100 offset → 422), so
    a single ordering can't reach the whole universe. We slice it from many
    angles and dedupe by id:
      * global orderings: newest, top-24h-volume, all-time-volume, liquidity,
        closing-soon — each cap-limited pass surfaces a different subset;
      * per-category: newest + top-volume for every high-level tag, so mid-tail
        markets (not brand-new, not top-volume) in each segment (politics, econ,
        geopolitics, crypto, sports, …) are still captured.
    """
    seen, by_id = set(), {}

    def add(rows, cat=None):
        for m in rows:
            mid = m.get("id")
            if mid in seen:
                if cat:                    # already have it; just tag the category
                    by_id[mid].setdefault("_cats", set()).add(cat)
                continue
            seen.add(mid)
            if cat:
                m["_cats"] = {cat}
            by_id[mid] = m

    add(_pages("startDate", max_pages, page_size))
    add(_pages("volume24hr", max(8, max_pages // 2), page_size))
    add(_pages("volumeNum", max(8, max_pages // 2), page_size))
    add(_pages("liquidityNum", max(8, max_pages // 2), page_size))
    add(_pages("endDate", max(6, max_pages // 3), page_size, ascending=True))

    cat_pages = max(4, max_pages // 4)
    for label, tid in CATEGORIES.items():
        add(_pages("startDate", cat_pages, page_size, extra={"tag_id": tid}), cat=label)
        add(_pages("volume24hr", cat_pages, page_size, extra={"tag_id": tid}), cat=label)

    return list(by_id.values())


def slim(m: dict) -> dict:
    """Compact per-market record with everything the analysis needs."""
    try:
        prices = m.get("outcomePrices")
        prices = json.loads(prices) if isinstance(prices, str) else (prices or [])
        prices = [_f(p) for p in prices]
    except Exception:
        prices = []
    try:
        outcomes = m.get("outcomes")
        outcomes = json.loads(outcomes) if isinstance(outcomes, str) else (outcomes or [])
    except Exception:
        outcomes = []
    try:
        tokens = m.get("clobTokenIds")
        tokens = json.loads(tokens) if isinstance(tokens, str) else (tokens or [])
    except Exception:
        tokens = []
    ev = (m.get("events") or [{}])[0] if m.get("events") else {}
    return {
        "id": m.get("id"),
        "q": m.get("question"),
        "slug": m.get("slug"),
        "event": ev.get("title"),
        "category": m.get("category") or ev.get("category"),
        "cats": sorted(m.get("_cats", [])),   # high-level tags this market matched
        "created": m.get("createdAt") or m.get("startDate"),
        "end": m.get("endDate"),
        "volume24h": _f(m.get("volume24hr")),
        "volume": _f(m.get("volumeNum") or m.get("volume")),
        "liquidity": _f(m.get("liquidityNum") or m.get("liquidity")),
        "outcomes": outcomes,
        "prices": prices,
        "bestBid": _f(m.get("bestBid")),
        "bestAsk": _f(m.get("bestAsk")),
        "spread": _f(m.get("spread")),
        "tokens": tokens,
        "conditionId": m.get("conditionId"),
        "negRisk": bool(m.get("negRisk")),
        "feesEnabled": m.get("feesEnabled"),
        "rewardsMinSize": _f(m.get("rewardsMinSize")),
        "rewardsMaxSpread": _f(m.get("rewardsMaxSpread")),
        "orderMinSize": _f(m.get("orderMinSize"), 5.0),
        "resolutionSource": (m.get("resolutionSource") or "")[:200],
        "description": (m.get("description") or "")[:600],
    }


def digest(rows: list[dict], n: int = 20) -> str:
    now = time.time()

    def ts(s):
        if not s:
            return 0
        try:
            return time.mktime(time.strptime(s[:19], "%Y-%m-%dT%H:%M:%S"))
        except Exception:
            return 0

    def line(r):
        pr = "/".join(f"{p:.2f}" for p in r["prices"][:2]) or "?"
        endh = (ts(r["end"]) - now) / 3600 if r["end"] else -1
        rw = " R" if r["rewardsMinSize"] > 0 else ""
        return (f"  {pr:>10} v24=${r['volume24h']:>10,.0f} liq=${r['liquidity']:>9,.0f}"
                f" end={endh:>6.0f}h{rw}  {(r['q'] or '')[:78]}")

    parts = []
    newest = sorted(rows, key=lambda r: ts(r["created"]), reverse=True)[:n]
    parts.append("== NEWEST ==")
    parts += [line(r) for r in newest]
    soon = sorted([r for r in rows if ts(r["end"]) > now],
                  key=lambda r: ts(r["end"]))[:n]
    parts.append("\n== CLOSING SOON ==")
    parts += [line(r) for r in soon]
    vol = sorted(rows, key=lambda r: r["volume24h"], reverse=True)[:n]
    parts.append("\n== TOP VOLUME 24H ==")
    parts += [line(r) for r in vol]
    rew = sorted([r for r in rows if r["rewardsMinSize"] > 0],
                 key=lambda r: r["volume24h"], reverse=True)[:n]
    parts.append("\n== REWARDS-CARRYING ==")
    parts += [line(r) for r in rew]
    return "\n".join(parts)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--digest", action="store_true")
    ap.add_argument("--min-liquidity", type=float, default=0.0)
    ap.add_argument("--max-pages", type=int, default=40)
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "..", "runs"))
    args = ap.parse_args()

    raw = fetch_all(args.max_pages)
    rows = [slim(m) for m in raw]
    rows = [r for r in rows if r["tokens"] and r["liquidity"] >= args.min_liquidity]
    stamp = time.strftime("%Y%m%d-%H%M", time.gmtime())
    path = os.path.join(args.out, f"scan-{stamp}.json")
    os.makedirs(args.out, exist_ok=True)
    with open(path, "w") as f:
        json.dump(rows, f)
    print(f"scanned {len(raw)} markets -> {len(rows)} usable  saved {path}", file=sys.stderr)
    if args.digest:
        print(digest(rows, args.top))


if __name__ == "__main__":
    main()
