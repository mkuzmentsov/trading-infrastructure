"""Reversal-hunter feasibility (user idea 2026-08-05, after the sol -$99).

The mirror of mintsalvage: instead of SELLING the trailing token at 1c, BUY it.
By the unified-book identity this is identical to "mint + sell the leader at
99c", minus the mint and its gas.

  buy trailer @0.01 -> +0.99 if it reverses, -0.01 if not.  EV = p - 0.01.
  Break-even p = 1%  (exactly mintsalvage's threshold, opposite sign).

The question is NOT whether reversals happen -- it is whether the trailer is
BUYABLE at 1c on the bars that reverse. Price is informative: a token the
market believes has a 2% chance trades at 2c, not 1c. So we condition on what
a real bot could actually execute (ask <= 0.01) and measure the realised win
rate of exactly those tokens.
"""
import pickle, time, sys
from collections import defaultdict

TGRID = [60, 45, 30, 20, 15, 10, 5]
COINS = ["btc", "eth", "sol", "xrp", "bnb", "doge"]
SESSION = (12 * 60 + 30, 16 * 60)      # 12:30-16:00 UTC = 15:30-19:00 Kyiv


def in_session(ws):
    t = time.gmtime(ws)
    m = t.tm_hour * 60 + t.tm_min
    return SESSION[0] <= m < SESSION[1]


def run(session_only):
    agg = defaultdict(lambda: [0, 0])          # T -> [buyable, of which won]
    bars = defaultdict(set)
    for coin in COINS:
        try:
            mk = pickle.load(open(f"cache/{coin}.pkl", "rb"))
        except FileNotFoundError:
            continue
        for ws, m in mk.items():
            if session_only and not in_session(ws):
                continue
            win = m.get("win")
            if win not in ("UP", "DOWN") or not m.get("snaps"):
                continue
            for T in TGRID:
                best = None
                for s in m["snaps"]:
                    tl, ua, da = s[0], s[5], s[7]
                    if not (0 <= tl <= 300) or abs(tl - T) > 2.0:
                        continue
                    if best is None or abs(tl - T) < abs(best[0] - T):
                        best = (tl, ua, da)
                if best is None:
                    continue
                _, ua, da = best
                # the CHEAP side is the trailer; can we buy it at 1c?
                for side, ask in (("UP", ua), ("DOWN", da)):
                    if ask is not None and ask <= 0.010001:
                        agg[T][0] += 1
                        agg[T][1] += (win == side)
                        bars[T].add((coin, ws))
    return agg, bars


for label, so in (("12:30-16:00 UTC ONLY (the halt window)", True), ("ALL HOURS", False)):
    agg, bars = run(so)
    print(f"\n=== {label} ===")
    print(f"{'t_left':>7s} {'buyable@1c':>11s} {'reversed':>9s} {'rev%':>7s} "
          f"{'EV/$1 risked':>13s} {'verdict':>9s}")
    for T in TGRID:
        n, w = agg[T]
        if n < 20:
            continue
        p = w / n
        ev = (p - 0.01) / 0.01        # per $1 risked (buy at 1c)
        print(f"{T:7d} {n:11d} {w:9d} {100*p:7.2f} {ev:+13.2f} "
              f"{'+EV' if p > 0.01 else 'DEAD':>9s}")
