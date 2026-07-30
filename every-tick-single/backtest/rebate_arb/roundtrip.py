"""MAKER ROUND-TRIP farmer: buy as maker, then SELL as maker, so both fills
earn rebate and the position ends flat.

Why this is the only remaining shape worth testing. The pair-lock farmer fails
because the both-fill rate and the lock are inversely related (0.51/0.51 fills
22% of bars but pays 1.02 for a $1 pair; 0.49/0.49 locks 2c but fills 2%). And
holding an unpaired leg to resolution turns 0.35c of rebate into a +-50c coin
flip. A maker round trip removes BOTH problems: no pair needed, and the
position is closed the same bar.

CRITICAL CONSTRAINT the naive version gets wrong: you cannot buy at 0.50 and
sell at 0.50 and call both "maker". If the book is 0.50/0.51, a sell at 0.50 is
marketable -- it crosses into the resting bid and pays the 0.07*p(1-p) TAKER
fee, which at 50c is 1.75c/share, five times the rebate. The exit must rest at
or above the prevailing ask to stay a maker. So the round trip is really
buy-at-bid / sell-at-ask: spread capture plus rebate on both legs, and the open
question is what fraction of entries ever get their exit filled, and whether
those that do are the adversely-selected ones.
"""
from __future__ import annotations

import math

import fast

FEE_RATE, REBATE_SHARE = 0.07, 0.20


def rebate(p, sh):
    return REBATE_SHARE * FEE_RATE * p * (1 - p) * sh


def taker_fee(p, sh):
    return FEE_RATE * p * (1 - p) * sh


def _queue_at(mkt, tl_hi, idx_px, idx_sz, price):
    for s in mkt["snaps"]:
        if s[0] > tl_hi:
            continue
        px, sz = s[idx_px], s[idx_sz]
        return sz if (px is not None and abs(px - price) < 1e-9) else 0.0
    return None


def simulate(coins, p_buy, exit_off=0.01, size=100.0, entry_hi=1200.0,
             entry_stop=300.0, exit_deadline=0.0, force_flat=False, hidden=0.0):
    """Rest bids at p_buy on both tokens over (entry_stop, entry_hi];
    on each fill rest a maker ask at p_buy+exit_off until exit_deadline.
    force_flat: taker-dump whatever is still open at the deadline."""
    p_sell = round(p_buy + exit_off, 4)
    rows = []
    for coin in coins:
        for ws, m in fast.load(coin).items():
            for side, bi, bs, ai, asz, tok in (("UP", 1, 2, 5, 6, "U"),
                                               ("DOWN", 3, 4, 7, 8, "D")):
                q = _queue_at(m, entry_hi, bi, bs, p_buy)
                if q is None:
                    continue
                q += hidden      # unobservable size resting at our level
                filled = 0.0
                fill_tl = None
                # ---- entry: our BID is filled by taker SELL prints <= p_buy
                for t in m["sells"]:
                    tl, tk, px, sz, tside = t
                    if tl > entry_hi:
                        continue
                    if tl <= entry_stop or filled >= size:
                        break
                    if tk != tok or tside != "SELL" or px > p_buy + 1e-9:
                        continue
                    if q > 0:
                        used = min(q, sz)
                        q -= used
                        sz -= used
                    if sz > 0:
                        filled += min(sz, size - filled)
                        if fill_tl is None:
                            fill_tl = tl
                if filled <= 0:
                    continue
                # ---- exit: our ASK is filled by taker BUY prints >= p_sell
                qa = None
                sold = 0.0
                exit_tl = None
                for s in m["snaps"]:
                    if s[0] > fill_tl:
                        continue
                    px, sz = s[ai], s[asz]
                    qa = sz if (px is not None and abs(px - p_sell) < 1e-9) else 0.0
                    break
                if qa is None:
                    qa = 0.0
                qa += hidden
                for t in m["sells"]:
                    tl, tk, px, sz, tside = t
                    if tl > fill_tl:
                        continue
                    if tl <= exit_deadline or sold >= filled:
                        break
                    if tk != tok or tside != "BUY" or px < p_sell - 1e-9:
                        continue
                    if qa > 0:
                        used = min(qa, sz)
                        qa -= used
                        sz -= used
                    if sz > 0:
                        sold += min(sz, filled - sold)
                        if exit_tl is None:
                            exit_tl = tl
                open_sh = filled - sold
                # ---- P&L
                pnl = sold * (p_sell - p_buy)
                reb = rebate(p_buy, filled) + rebate(p_sell, sold)
                resid = 0.0
                if open_sh > 0:
                    if force_flat:
                        # dump at the deadline into the bid, paying taker fee
                        bid = None
                        for s in m["snaps"]:
                            if s[0] > exit_deadline:
                                continue
                            bid = s[bi]
                            break
                        bid = bid if bid is not None else 0.0
                        resid = open_sh * (bid - p_buy) - taker_fee(bid, open_sh)
                    else:
                        won = (m["win"] == side)
                        resid = open_sh * ((1.0 if won else 0.0) - p_buy)
                rows.append(dict(coin=coin, ws=ws, side=side, filled=filled,
                                 sold=sold, open=open_sh, spread=pnl,
                                 rebate=reb, resid=resid,
                                 net=pnl + reb + resid))
    return rows


def report(rows, label):
    if not rows:
        return f"{label:44s} NO ENTRIES"
    n = len(rows)
    fl = sum(r["filled"] for r in rows)
    sd = sum(r["sold"] for r in rows)
    spread = sum(r["spread"] for r in rows)
    reb = sum(r["rebate"] for r in rows)
    resid = [r["resid"] for r in rows if r["open"] > 0]
    rsum = sum(resid)
    det = spread + reb
    if len(resid) > 1:
        mu = rsum / len(resid)
        sd_ = math.sqrt(sum((x - mu) ** 2 for x in resid) / (len(resid) - 1))
        noise = sd_ * math.sqrt(len(resid))
    else:
        noise = 0.0
    return (f"{label:44s} entries={n:5d} fill_sh={fl:8.0f} exit_rate={100*sd/max(fl,1):3.0f}% "
            f"spread=${spread:+8.2f} reb=${reb:+7.2f} DET=${det:+8.2f} "
            f"resid=${rsum:+9.2f}(n={len(resid):4d}) noise_sd=${noise:7.0f} "
            f"TOT=${det+rsum:+9.2f}")
