#!/usr/bin/env python3
"""Test the PRE-OPEN resting-bid hypothesis (user idea 2026-07-06): the next 5m
market is live and liquid DURING the current bar. Pre-open there is no realized
move to be informed about (the bar's open isn't set yet), so fills there should
be ~unbiased coin flips → a resting bid at 0.48-0.49 pre-open would be +EV.

Method (public data, proxy): for many RESOLVED 5m markets, pull each side's
price path (clob prices-history, fidelity=1 ≈ 1-min mids). A resting bid at P on
a side "fills pre-open" if the side's mid touched <= P while t < open. Win =
that side resolved to 1. Compare pre-open fill win% to the intra-bar ~44%.
Caveat: 1-min mids proxy for trade prints (coarse) — a positive result justifies
instrumenting the bot for print-exact pre-open data.

Usage: python3 preopen_study.py [n_markets=150] [coins=btc,eth,sol,xrp]
"""
import json, sys, urllib.request, time

SERIES = {"btc": 10684}  # extend when other series ids known; btc is the deep one


def get(u):
    try:
        return json.loads(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "curl/8"}), timeout=20).read())
    except Exception as e:
        return {"_err": str(e)[:60]}


def resolved_markets(series_id, n):
    out, offset = [], 0
    while len(out) < n and offset < n * 2 + 40:
        ev = get(f"https://gamma-api.polymarket.com/events?series_id={series_id}&closed=true&limit=100&offset={offset}&order=startDate&ascending=false")
        if not isinstance(ev, list) or not ev:
            break
        for e in ev:
            for m in e.get("markets", []):
                sl = m.get("slug", "")
                if sl.startswith("btc-updown-5m") and m.get("outcomePrices") and m.get("clobTokenIds"):
                    out.append(m)
        offset += 100
    return out[:n]


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 150
    mkts = resolved_markets(SERIES["btc"], n)
    print(f"resolved btc 5m markets: {len(mkts)}")
    # per price: [preopen_fills, preopen_wins, intra_fills, intra_wins]
    grid = {P: [0, 0, 0, 0] for P in (0.46, 0.47, 0.48, 0.49, 0.50)}
    used = 0
    for m in mkts:
        ws = int(m["slug"].split("-")[-1])
        toks = json.loads(m["clobTokenIds"])
        outp = json.loads(m["outcomePrices"]) if isinstance(m["outcomePrices"], str) else m["outcomePrices"]
        # outp[0] = UP resolution (1/0)
        up_win = float(outp[0]) > 0.5
        ph = get(f"https://clob.polymarket.com/prices-history?market={toks[0]}&startTs={ws-900}&endTs={ws+300}&fidelity=1")
        h = ph.get("history", []) if isinstance(ph, dict) else []
        if not h:
            continue
        used += 1
        pre = [(p["t"]-ws, p["p"]) for p in h if p["t"]-ws < 0]
        intra = [(p["t"]-ws, p["p"]) for p in h if 0 <= p["t"]-ws <= 300]
        for P in grid:
            g = grid[P]
            # UP side: mid is p; DOWN side mid = 1-p
            for side_win, mids_pre, mids_intra in (
                    (up_win, [pp for _, pp in pre], [pp for _, pp in intra]),
                    (not up_win, [1-pp for _, pp in pre], [1-pp for _, pp in intra])):
                if any(mm <= P for mm in mids_pre):
                    g[0] += 1; g[1] += side_win
                if any(mm <= P for mm in mids_intra):
                    g[2] += 1; g[3] += side_win
        time.sleep(0.05)
    print(f"markets with price history: {used}\n")
    print(f"{'P':>5} {'PRE-OPEN fill/win':>22} {'INTRA-BAR fill/win':>22}  {'pre edge':>9}")
    for P in sorted(grid):
        pf, pw, itf, itw = grid[P]
        pq = pw/pf if pf else 0
        iq = itw/itf if itf else 0
        print(f"{P:5.2f}  {pf:5d} fills, win {pq*100:5.1f}%    {itf:5d} fills, win {iq*100:5.1f}%   {pq-P:+.3f}")
    print("\npre edge = pre-open win% − P (breakeven). >0 = pre-open resting bid +EV on outcome.")
    print("NOTE: 1-min mid proxy for fills; positive result → instrument bot for print-exact pre-open data.")


if __name__ == "__main__":
    main()
