"""Print-exact, FIFO-queue simulator for two-sided maker quoting (arb + rebate).

WHY THIS EXISTS. Every previous pass at the "post-order rebate farmer" used a
1-minute MID proxy (PLAN.md / EXPERIMENTS.md): it assumed a resting bid fills
whenever the mid touches it, which ignores (a) queue position — a 0.50 bid sits
behind whatever size is already there — and (b) that a fill needs an actual
taker SELL print, not a quote. Both errors inflate the both-fill rate, which is
the term the whole strategy lives on. The mrec recorder now gives 100ms
top-of-book + every trade print for each market across its ENTIRE life
(next3 -> next2 -> next1 -> cur -> post) plus the resolution, so the fill model
can be exact instead of assumed.

FILL MODEL. We rest a BUY at price P on a token.
  - Trades carry a taker side; validated on real data: side="SELL" prints at the
    previous best bid 88% of the time, side="BUY" at the previous ask 87%. So a
    resting BID is filled only by SELL prints at price <= P.
  - FIFO: only the size resting at our level WHEN WE JOIN is ahead of us. Later
    arrivals queue behind. So queue_ahead is fixed at join time and only
    decreases as SELL volume arrives.
      * best_bid == P  -> queue_ahead = size at P (we join the back of it)
      * best_bid  < P  -> queue_ahead = 0 (we improve; we are alone at the front)
      * best_bid  > P  -> queue_ahead = 0 but no fill until the market trades
                          down to P (prints at <= P are what we count anyway)
  - Partial fills are tracked; we fill min(remaining, volume beyond the queue).

This is deliberately CONSERVATIVE in one place and optimistic in another:
conservative because we never assume a fill without a print; optimistic because
we assume our whole level is consumed in print order and ignore that some prints
may be matched against orders posted after ours at a better price. Net, it is a
far tighter upper bound than the mid proxy.
"""
from __future__ import annotations

import glob
import gzip
import json
import os
from collections import defaultdict

DATA = os.environ.get(
    "MREC_DIR",
    "/Users/maxkuzmentsov/development/projects/my/hummingbot/hummingbot-infra/"
    "every-tick-single/data/raw/mrec")

FEE_RATE = 0.07          # crypto taker fee
REBATE_SHARE = 0.20      # 20% of taker fees -> maker rebate pool
# E7 measured our capture == 20% of our OWN fee-equivalent (no pool dilution).
def rebate_per_share(p: float) -> float:
    return REBATE_SHARE * FEE_RATE * p * (1.0 - p)


ROLE_WINDOW = {          # role -> (tl_low, tl_high) seconds before close
    "next3": (900, 1200),
    "next2": (600, 900),
    "next1": (300, 600),
    "cur": (0, 300),
}


def load_market_tracks(coin: str, days: list[str] | None = None):
    """Yield (ws, rows, winner) per market: rows are that market's SNAPs in
    time order across every role, winner from the RES event."""
    tracks: dict[int, list] = defaultdict(list)
    winners: dict[int, str] = {}
    files = sorted(glob.glob(f"{DATA}/{coin}/*.gz"))
    if days:
        files = [f for f in files if any(d in f for d in days)]
    for f in files:
        with gzip.open(f, "rt") as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                ev = r.get("ev")
                if ev == "SNAP":
                    tracks[r["ws"]].append(r)
                elif ev == "RES":
                    winners[r["ws"]] = r.get("win")
    for ws in sorted(tracks):
        if ws in winners:
            rows = sorted(tracks[ws], key=lambda x: x["t"])
            yield ws, rows, winners[ws]


def simulate_leg(rows, side: str, price: float, size: float,
                 entry_tl_hi: float, exit_tl: float):
    """Rest a BUY at `price` on UP/DOWN from the first snapshot with
    tl <= entry_tl_hi, cancel at tl <= exit_tl. Returns (filled_shares,
    fill_tl_first). Uses FIFO queue + taker SELL prints only."""
    bid_k, bidsz_k = ("ub", "ubs") if side == "UP" else ("db", "dbs")
    tok = "U" if side == "UP" else "D"
    joined = False
    queue_ahead = 0.0
    filled = 0.0
    first_fill_tl = None
    for r in rows:
        tl = r.get("tl")
        if tl is None or tl > entry_tl_hi:
            continue
        if tl <= exit_tl:
            break
        if not joined:
            b = r.get(bid_k)
            bsz = r.get(bidsz_k) or 0.0
            # size ahead of us at our price level, at the moment we join
            queue_ahead = bsz if (b is not None and abs(b - price) < 1e-9) else 0.0
            joined = True
        for t in (r.get("trd") or []):
            if len(t) < 5 or t[1] != tok or t[4] != "SELL":
                continue
            if t[2] > price + 1e-9:
                continue            # sold above our bid: not our level
            vol = t[3]
            if queue_ahead > 0:
                used = min(queue_ahead, vol)
                queue_ahead -= used
                vol -= used
            if vol > 0 and filled < size:
                take = min(vol, size - filled)
                filled += take
                if first_fill_tl is None:
                    first_fill_tl = tl
        if filled >= size:
            break
    return filled, first_fill_tl


def run(coins, p_up, p_dn, size, entry_role, cancel_at_open, days=None):
    """Two-sided quote; returns per-pair records."""
    lo, hi = ROLE_WINDOW[entry_role]
    exit_tl = 300.0 if cancel_at_open else 0.0
    out = []
    for coin in coins:
        for ws, rows, win in load_market_tracks(coin, days):
            fu, tu = simulate_leg(rows, "UP", p_up, size, hi, exit_tl)
            fd, td = simulate_leg(rows, "DOWN", p_dn, size, hi, exit_tl)
            if fu <= 0 and fd <= 0:
                continue
            payout = (fu if win == "UP" else 0.0) + (fd if win == "DOWN" else 0.0)
            cost = fu * p_up + fd * p_dn
            reb = fu * rebate_per_share(p_up) + fd * rebate_per_share(p_dn)
            out.append(dict(coin=coin, ws=ws, win=win, fu=fu, fd=fd,
                            both=(fu > 0 and fd > 0), pnl=payout - cost,
                            rebate=reb, net=payout - cost + reb))
    return out


def summarize(recs, label):
    if not recs:
        return f"{label}: no fills"
    n = len(recs)
    both = [r for r in recs if r["both"]]
    single = [r for r in recs if not r["both"]]
    net = sum(r["net"] for r in recs)
    pnl = sum(r["pnl"] for r in recs)
    reb = sum(r["rebate"] for r in recs)
    sw = sum(1 for r in single
             if (r["fu"] > 0 and r["win"] == "UP") or (r["fd"] > 0 and r["win"] == "DOWN"))
    return (f"{label}: bars={n} both={len(both)} ({100*len(both)/n:.0f}%) "
            f"single={len(single)} single_win={sw}/{len(single)} "
            f"({100*sw/max(len(single),1):.0f}%) | outcome=${pnl:+.2f} "
            f"rebate=${reb:+.2f} NET=${net:+.2f} (${net/n:+.3f}/bar)")
