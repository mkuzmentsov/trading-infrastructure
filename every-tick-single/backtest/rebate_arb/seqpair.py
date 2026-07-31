"""SEQUENTIAL pair with an ACTIVE neutraliser (user's mechanism, 2026-07-31).

Rest maker bids on BOTH tokens. Whichever fills first, do not ride it: within
`delay` seconds either (a) the second maker leg fills on its own -> free pair,
or (b) we COMPLETE the pair by taking the other side's ask, or (c) we DUMP the
filled side into its bid. Both (b) and (c) pay the 0.07*p(1-p) taker fee.

Why this can beat everything tested so far. Riding an unpaired leg to
resolution is a +-50c/share coin flip and the leg that stays unpaired is the one
crashing (single-fill win rate 4% held to expiry). Completing the pair instead
caps the outcome at `1 - (p_filled + ask_other)` minus one taker fee -- a few
cents, not fifty. The whole question is whether the other side's ask has already
run away by the time we react: we got filled BECAUSE the price was moving, so
the ask we must lift is, by construction, moving against us. `delay` measures
exactly how fast that happens.
"""
from __future__ import annotations

import math

import fast

FEE_RATE, REBATE_SHARE = 0.07, 0.20


def rebate(p, sh):
    return REBATE_SHARE * FEE_RATE * p * (1 - p) * sh


def taker_fee(p, sh):
    return FEE_RATE * p * (1 - p) * sh


def _first_maker_fill(mkt, side, price, size, tl_hi, tl_lo, hidden=0.0):
    """(filled, tl_of_first_fill) for a resting bid, FIFO vs visible queue."""
    tok = "U" if side == "UP" else "D"
    bi, si = (1, 2) if side == "UP" else (3, 4)
    q = None
    for s in mkt["snaps"]:
        if s[0] > tl_hi:
            continue
        b, bsz = s[bi], s[si]
        q = (bsz if (b is not None and abs(b - price) < 1e-9) else 0.0) + hidden
        break
    if q is None:
        return 0.0, None
    filled, first = 0.0, None
    for tl, t, px, sz, tside in mkt["sells"]:
        if tside != "SELL" or tl > tl_hi:
            continue
        if tl <= tl_lo or filled >= size:
            break
        if t != tok or px > price + 1e-9:
            continue
        if q > 0:
            u = min(q, sz)
            q -= u
            sz -= u
        if sz > 0:
            filled += min(sz, size - filled)
            if first is None:
                first = tl
    return filled, first


def _quote_at(mkt, tl_target, side, want):
    """Book level for `side` at the snapshot nearest to (and at or before)
    tl_target. want='ask' or 'bid'."""
    ai = (5 if side == "UP" else 7) if want == "ask" else (1 if side == "UP" else 3)
    best = None
    for s in mkt["snaps"]:
        if s[0] > tl_target:
            best = s
            continue
        return s[ai]
    return best[ai] if best else None


def run(coins, price, size=100.0, tl_hi=1200.0, tl_lo=0.0, delay=1.0,
        mode="complete", hidden=0.0):
    """mode: 'complete' = take the other side's ask; 'dump' = sell into our bid;
    'ride' = hold to resolution (the baseline that loses)."""
    out = []
    for coin in coins:
        for ws, m in fast.load(coin).items():
            fu, tu = _first_maker_fill(m, "UP", price, size, tl_hi, tl_lo, hidden)
            fd, td = _first_maker_fill(m, "DOWN", price, size, tl_hi, tl_lo, hidden)
            if fu <= 0 and fd <= 0:
                continue
            paired = min(fu, fd)
            reb = rebate(price, fu) + rebate(price, fd)
            pnl = paired * (1.0 - 2 * price)          # free maker pair
            # residual: the side that over-filled relative to the other
            if fu > fd:
                side, resid, rtl = "UP", fu - fd, tu
            else:
                side, resid, rtl = "DOWN", fd - fu, td
            act = None
            if resid > 0.5 and rtl is not None:
                other = "DOWN" if side == "UP" else "UP"
                tgt = rtl - delay                     # tl counts DOWN
                if mode == "complete":
                    a = _quote_at(m, tgt, other, "ask")
                    if a is None or a <= 0:
                        a = 1.0 - price
                    pnl += resid * (1.0 - price - a) - taker_fee(a, resid)
                    act = ("complete", a)
                elif mode == "dump":
                    b = _quote_at(m, tgt, side, "bid")
                    b = b if b is not None else 0.0
                    pnl += resid * (b - price) - taker_fee(b, resid)
                    act = ("dump", b)
                else:
                    won = (m["win"] == side)
                    pnl += resid * ((1.0 if won else 0.0) - price)
                    act = ("ride", None)
            out.append(dict(coin=coin, ws=ws, paired=paired, resid=resid,
                            side=side, act=act, pnl=pnl, rebate=reb,
                            net=pnl + reb))
    return out


def report(rows, label):
    if not rows:
        return f"{label:46s} NO FILLS"
    n = len(rows)
    net = sum(r["net"] for r in rows)
    reb = sum(r["rebate"] for r in rows)
    pnl = sum(r["pnl"] for r in rows)
    nres = sum(1 for r in rows if r["resid"] > 0.5)
    vals = [r["net"] for r in rows]
    mu = net / n
    sd = math.sqrt(sum((x - mu) ** 2 for x in vals) / (n - 1)) if n > 1 else 0.0
    t = mu / (sd / math.sqrt(n)) if sd else 0.0
    return (f"{label:46s} bars={n:5d} legged={100*nres/n:3.0f}% "
            f"trade=${pnl:+9.2f} reb=${reb:+7.2f} NET=${net:+9.2f} "
            f"${mu:+.4f}/bar t={t:+6.2f}")
