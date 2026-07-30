"""Fast two-sided maker sim over the compacted cache. See sim.py for the fill
model and why the mid-proxy approach it replaces was wrong."""
from __future__ import annotations

import os
import pickle
from functools import lru_cache

CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")
FEE_RATE, REBATE_SHARE = 0.07, 0.20
COINS = ["btc", "eth", "sol", "xrp", "bnb", "doge"]

ROLE_HI = {"next3": 1200.0, "next2": 900.0, "next1": 600.0, "cur": 300.0}


def rebate_per_share(p):
    return REBATE_SHARE * FEE_RATE * p * (1.0 - p)


@lru_cache(maxsize=8)
def load(coin):
    with open(f"{CACHE}/{coin}.pkl", "rb") as fh:
        return pickle.load(fh)


def leg(mkt, side, price, size, entry_hi, exit_tl):
    """FIFO queue + taker SELL prints. Returns (filled, first_fill_tl)."""
    tok = "U" if side == "UP" else "D"
    bi, si = (1, 2) if side == "UP" else (3, 4)
    queue = None
    for s in mkt["snaps"]:                     # chronological (tl descending)
        if s[0] > entry_hi:
            continue
        b, bsz = s[bi], s[si]
        queue = bsz if (b is not None and abs(b - price) < 1e-9) else 0.0
        break
    if queue is None:
        return 0.0, None
    filled = 0.0
    first = None
    for tl, t, px, sz, tside in mkt["sells"]:
        if tside != "SELL":
            continue
        if tl > entry_hi:
            continue
        if tl <= exit_tl:
            break
        if t != tok or px > price + 1e-9:
            continue
        if queue > 0:
            used = min(queue, sz)
            queue -= used
            sz -= used
        if sz > 0 and filled < size:
            filled += min(sz, size - filled)
            if first is None:
                first = tl
            if filled >= size:
                break
    return filled, first


def run(coins, p_up, p_dn, size=100.0, entry="next2", cancel_at_open=True):
    hi = ROLE_HI[entry]
    exit_tl = 300.0 if cancel_at_open else 0.0
    recs = []
    for coin in coins:
        for ws, m in load(coin).items():
            fu, tu = leg(m, "UP", p_up, size, hi, exit_tl)
            fd, td = leg(m, "DOWN", p_dn, size, hi, exit_tl)
            if fu <= 0 and fd <= 0:
                continue
            win = m["win"]
            payout = (fu if win == "UP" else 0.0) + (fd if win == "DOWN" else 0.0)
            cost = fu * p_up + fd * p_dn
            reb = fu * rebate_per_share(p_up) + fd * rebate_per_share(p_dn)
            recs.append(dict(coin=coin, ws=ws, win=win, fu=fu, fd=fd,
                             both=(fu > 0 and fd > 0),
                             pnl=payout - cost, rebate=reb,
                             net=payout - cost + reb, tu=tu, td=td))
    return recs


def n_markets(coins):
    return sum(len(load(c)) for c in coins)


def summarize(recs, label, mkts=None):
    if not recs:
        return f"{label:38s} NO FILLS"
    n = len(recs)
    both = sum(1 for r in recs if r["both"])
    single = [r for r in recs if not r["both"]]
    sw = sum(1 for r in single
             if (r["fu"] > 0 and r["win"] == "UP") or (r["fd"] > 0 and r["win"] == "DOWN"))
    pnl = sum(r["pnl"] for r in recs)
    reb = sum(r["rebate"] for r in recs)
    net = pnl + reb
    cov = f"{100*n/mkts:.0f}%" if mkts else "-"
    return (f"{label:38s} traded={n:4d} ({cov} of mkts) both={100*both/n:3.0f}% "
            f"single_win={100*sw/max(len(single),1):3.0f}%(n={len(single):4d}) "
            f"out=${pnl:+9.2f} reb=${reb:+7.2f} NET=${net:+9.2f} "
            f"${net/n:+.4f}/traded")
