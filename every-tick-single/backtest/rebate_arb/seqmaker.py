"""MAKER-MAKER sequential pair (user's refined mechanism, 2026-07-31).

  1. Rest ONE post-only bid at p1 (on whichever token dips there first).
  2. When it fills, place the SECOND post-only bid on the complement at p2.
     Placed only now -- placed together, the dipping side fills immediately
     and the other bid sits at what is momentarily the expensive side.
  3. If the second bid fills (price mean-reverted): maker-maker pair.
     Rebate on BOTH legs + lock = 1 - (p1 + p2). This is the farm.
  4. If it has not filled by the rescue deadline: MARKET order to complete the
     pair (taker fee, adverse ask) -- capped loss, never ride to resolution.
  5. Partial fills handled at share level: only min(f1, f2) is paired; the
     unpaired remainder goes through the same rescue.

Primary objective is the REBATE (farming); lock margin is bonus. Hypothesis to
test: this works in LOW-VOLATILITY (choppy) bars where reversion completes, so
results are bucketed by realized in-bar book movement.
"""
from __future__ import annotations

import math
from collections import defaultdict

import fast

FEE_RATE, REBATE_SHARE = 0.07, 0.20


def rebate(p, sh):
    return REBATE_SHARE * FEE_RATE * p * (1 - p) * sh


def taker_fee(p, sh):
    return FEE_RATE * p * (1 - p) * sh


def _maker_fill(mkt, side, price, size, tl_hi, tl_lo, hidden):
    """First-leg resting bid: (filled, tl_first_fill)."""
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


def _maker_fill_from(mkt, side, price, size, tl_start, tl_stop, hidden):
    """Second-leg bid placed at tl_start (tl counts DOWN): queue sized from the
    snapshot at placement, fills from later SELL prints until tl_stop."""
    tok = "U" if side == "UP" else "D"
    bi, si = (1, 2) if side == "UP" else (3, 4)
    q = None
    for s in mkt["snaps"]:
        if s[0] > tl_start:
            continue
        b, bsz = s[bi], s[si]
        q = (bsz if (b is not None and abs(b - price) < 1e-9) else 0.0) + hidden
        break
    if q is None:
        q = hidden
    filled, first = 0.0, None
    for tl, t, px, sz, tside in mkt["sells"]:
        if tside != "SELL" or tl > tl_start:
            continue
        if tl <= tl_stop or filled >= size:
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


def _ask_at(mkt, tl_target, side):
    ai = 5 if side == "UP" else 7
    best = None
    for s in mkt["snaps"]:
        if s[0] > tl_target:
            best = s
            continue
        return s[ai]
    return best[ai] if best else None


def bar_vol(mkt):
    """Realized chop proxy: range of the UP bid in the FIRST HALF of the
    active bar (tl 300 -> 150), BEFORE resolution convergence dominates --
    by close a binary always converges to 0/1, so full-bar range is ~0.6
    for every bar and carries no regime signal."""
    lo = hi = None
    for s in mkt["snaps"]:
        if s[0] > 300 or s[0] <= 150:
            continue
        b = s[1]
        if b is None:
            continue
        lo = b if lo is None else min(lo, b)
        hi = b if hi is None else max(hi, b)
    return None if lo is None else hi - lo


def run(coins, p1, margin=0.0, size=100.0, tl_hi=1200.0, rescue_tl=30.0,
        hidden=0.0, wait_secs=None):
    """p2 = 1 - p1 - margin (margin>0 demands a positive lock).
    rescue_tl: latest tl at which unpaired shares are taker-completed.
    wait_secs: if set, rescue fires wait_secs AFTER the first fill (or at
    rescue_tl, whichever is earlier) -- caps how long the leg stays naked."""
    p2 = round(1.0 - p1 - margin, 4)
    out = []
    for coin in coins:
        for ws, m in fast.load(coin).items():
            # first leg: whichever token dips to p1 first
            fu, tu = _maker_fill(m, "UP", p1, size, tl_hi, rescue_tl, hidden)
            fd, td = _maker_fill(m, "DOWN", p1, size, tl_hi, rescue_tl, hidden)
            if fu <= 0 and fd <= 0:
                continue
            if fu > 0 and (fd <= 0 or (tu or 9e9) >= (td or 9e9)):
                # NB tl counts down: larger tl = earlier
                first_side, f1, t1 = ("UP", fu, tu) if (fd <= 0 or (tu or 0) >= (td or 0)) else ("DOWN", fd, td)
            else:
                first_side, f1, t1 = "DOWN", fd, td
            other = "DOWN" if first_side == "UP" else "UP"
            # second leg: post-only on the complement, placed at t1
            stop_tl = rescue_tl if wait_secs is None else max(rescue_tl, t1 - wait_secs)
            f2, t2 = _maker_fill_from(m, other, p2, f1, t1, stop_tl, hidden)
            paired = min(f1, f2)
            reb = rebate(p1, f1) + rebate(p2, f2)
            pnl = paired * (1.0 - p1 - p2)
            resid = f1 - paired
            rescue_px = None
            if resid > 0.5:
                a = _ask_at(m, stop_tl, other)
                if a is None or a <= 0 or a >= 1:
                    a = 1.0 - p1 + 0.02
                pnl += resid * (1.0 - p1 - a) - taker_fee(a, resid)
                rescue_px = a
            v = bar_vol(m)
            out.append(dict(coin=coin, ws=ws, f1=f1, f2=f2, paired=paired,
                            resid=resid, rescue_px=rescue_px, vol=v,
                            pnl=pnl, rebate=reb, net=pnl + reb))
    return out


def report(rows, label):
    if not rows:
        return f"{label:40s} NO ENTRIES"
    n = len(rows)
    net = sum(r["net"] for r in rows)
    reb = sum(r["rebate"] for r in rows)
    mm = sum(1 for r in rows if r["paired"] >= r["f1"] - 0.5)   # fully paired as maker
    resc = sum(1 for r in rows if r["resid"] > 0.5)
    vals = [r["net"] for r in rows]
    mu = net / n
    sd = math.sqrt(sum((x - mu) ** 2 for x in vals) / (n - 1)) if n > 1 else 0.0
    t = mu / (sd / math.sqrt(n)) if sd else 0.0
    return (f"{label:40s} bars={n:5d} mm_pair={100*mm/n:3.0f}% rescued={100*resc/n:3.0f}% "
            f"reb=${reb:+7.2f} NET=${net:+9.2f} ${mu:+.4f}/bar t={t:+6.2f}")


def report_by_vol(rows, label, edges=(0.05, 0.15)):
    print(f"\n{label} — by realized in-bar range (UP bid, active bar):")
    buckets = defaultdict(list)
    for r in rows:
        v = r["vol"]
        if v is None:
            buckets["unknown"].append(r)
        elif v <= edges[0]:
            buckets[f"LOW <= {edges[0]}"].append(r)
        elif v <= edges[1]:
            buckets[f"MID <= {edges[1]}"].append(r)
        else:
            buckets[f"HIGH > {edges[1]}"].append(r)
    for k in sorted(buckets):
        print("   " + report(buckets[k], k))
