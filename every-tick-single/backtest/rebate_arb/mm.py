"""Canonical two-sided market making on ONE token: rest a bid AND an ask
simultaneously, re-post after each fill, carry inventory, mark out at the end.

This is the textbook "post order rebate farmer": every fill on either side is a
maker fill and earns rebate, and buys/sells offset so inventory mean-reverts
around zero instead of accumulating a directional bet. It differs from
roundtrip.py, which only quoted the ask AFTER a buy filled.

Quotes track the book: bid at max(best_bid, target) is not modelled -- we quote
at FIXED prices (b, a) and rely on the real prints to decide fills, which is
what the recorder can support exactly. Inventory is capped: we stop bidding
when long the cap and stop offering when short it (no naked shorts -- on
Polymarket you can only sell what you hold, so short inventory is disallowed
and the ask only works down existing longs).
"""
from __future__ import annotations

import math

import fast

FEE_RATE, REBATE_SHARE = 0.07, 0.20


def rebate(p, sh):
    return REBATE_SHARE * FEE_RATE * p * (1 - p) * sh


def taker_fee(p, sh):
    return FEE_RATE * p * (1 - p) * sh


def simulate(coins, bid_px, ask_px, clip=50.0, cap=200.0,
             tl_hi=1200.0, tl_lo=0.0, flat_at=None):
    """Returns per (market, token) records. flat_at: tl at which leftover
    inventory is dumped into the bid as a taker (None = hold to resolution)."""
    out = []
    for coin in coins:
        for ws, m in fast.load(coin).items():
            for side, bi, bs, ai, asz, tok in (("UP", 1, 2, 5, 6, "U"),
                                               ("DOWN", 3, 4, 7, 8, "D")):
                inv = 0.0
                cash = 0.0
                reb = 0.0
                nfill = 0
                # queue ahead at each level, refreshed when we (re)post
                qb = qa = None
                for s in m["snaps"]:
                    if s[0] > tl_hi:
                        continue
                    b, bsz, a, asz_ = s[bi], s[bs], s[ai], s[asz]
                    qb = bsz if (b is not None and abs(b - bid_px) < 1e-9) else 0.0
                    qa = asz_ if (a is not None and abs(a - ask_px) < 1e-9) else 0.0
                    break
                if qb is None:
                    continue
                for tl, tk, px, sz, tside in m["sells"]:
                    if tl > tl_hi:
                        continue
                    if tl <= tl_lo:
                        break
                    if tk != tok:
                        continue
                    if tside == "SELL" and px <= bid_px + 1e-9 and inv < cap:
                        if qb > 0:
                            used = min(qb, sz)
                            qb -= used
                            sz -= used
                        if sz > 0:
                            got = min(sz, clip, cap - inv)
                            if got > 0:
                                inv += got
                                cash -= got * bid_px
                                reb += rebate(bid_px, got)
                                nfill += 1
                                qb = 0.0        # we re-post at the front
                    elif tside == "BUY" and px >= ask_px - 1e-9 and inv > 0:
                        if qa > 0:
                            used = min(qa, sz)
                            qa -= used
                            sz -= used
                        if sz > 0:
                            got = min(sz, clip, inv)
                            if got > 0:
                                inv -= got
                                cash += got * ask_px
                                reb += rebate(ask_px, got)
                                nfill += 1
                                qa = 0.0
                if nfill == 0:
                    continue
                resid = 0.0
                if inv > 0:
                    if flat_at is not None:
                        bid = None
                        for s in m["snaps"]:
                            if s[0] > flat_at:
                                continue
                            bid = s[bi]
                            break
                        bid = bid if bid is not None else 0.0
                        resid = inv * bid - taker_fee(bid, inv)
                    else:
                        resid = inv * (1.0 if m["win"] == side else 0.0)
                out.append(dict(coin=coin, ws=ws, side=side, fills=nfill,
                                inv=inv, cash=cash, rebate=reb, resid=resid,
                                net=cash + reb + resid))
    return out


def report(rows, label):
    if not rows:
        return f"{label:46s} NO FILLS"
    n = len(rows)
    fills = sum(r["fills"] for r in rows)
    cash = sum(r["cash"] for r in rows)
    reb = sum(r["rebate"] for r in rows)
    res = [r["resid"] + r["cash"] for r in rows if r["inv"] > 0]
    net = sum(r["net"] for r in rows)
    flat = [r for r in rows if r["inv"] <= 0]
    flatnet = sum(r["net"] for r in flat)
    nets = [r["net"] for r in rows]
    mu = net / n
    sd = math.sqrt(sum((x - mu) ** 2 for x in nets) / (n - 1)) if n > 1 else 0.0
    t = mu / (sd / math.sqrt(n)) if sd else 0.0
    return (f"{label:46s} mkts={n:5d} fills={fills:6d} reb=${reb:+7.2f} "
            f"flat_mkts={len(flat):4d}(${flatnet:+7.2f}) "
            f"NET=${net:+9.2f} ${mu:+.3f}/mkt t={t:+.2f}")
