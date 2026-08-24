"""Reversal hunter, USER'S spec (2026-08-05): rest/take a 1c BUY on the
trailing side whenever |lead| >= 8bps. NOT conditioned on the book being
cheap -- conditioned on the SIGNAL, which is a different population.

  buy trailer @1c -> +0.99 reversal / -0.01 otherwise.  EV = p - 0.01.
  Break-even p = 1%.  This is exactly mintsalvage's threshold, sign-flipped:
  the hunter wins precisely where mintsalvage loses.

Reported per session because that is the whole thesis -- mintsalvage lost
money in 12:30-16:00 UTC, so the mirror should win there if the thesis holds.
"""
import math, pickle, time
from collections import defaultdict

COINS = ["btc", "eth", "sol", "xrp", "bnb", "doge"]
TGRID = [45, 30, 20, 15, 10]
GATES = [8, 10, 12, 15]
SESSION = (12 * 60 + 30, 16 * 60)


def sess(ws):
    t = time.gmtime(ws); m = t.tm_hour * 60 + t.tm_min
    return SESSION[0] <= m < SESSION[1]


rows = []
for coin in COINS:
    try:
        mk = pickle.load(open(f"cache/{coin}.pkl", "rb"))
        leads = pickle.load(open(f"cache/{coin}-leads.pkl", "rb"))
    except FileNotFoundError:
        continue
    for ws, m in mk.items():
        win = m.get("win"); ser = leads.get(ws)
        if win not in ("UP", "DOWN") or not ser:
            continue
        bar = [(tl, lb) for tl, lb in ser if 0 <= tl <= 300]
        snap = {}
        for s in m.get("snaps") or []:
            tl = s[0]
            if 0 <= tl <= 300:
                for T in TGRID:
                    if abs(tl - T) <= 2.0 and (T not in snap or abs(tl-T) < abs(snap[T][0]-T)):
                        snap[T] = (tl, s[5], s[7])       # tl, up_ask, down_ask
        for T in TGRID:
            cand = [lb for tl, lb in bar if tl >= T]
            if not cand:
                continue
            lead = cand[-1]
            trailer = "DOWN" if lead > 0 else "UP"
            reversed_ = (win == trailer)
            ask = None
            if T in snap:
                ask = snap[T][1] if trailer == "UP" else snap[T][2]
            rows.append((coin, ws, T, abs(lead), reversed_, ask, sess(ws)))

def rep(sel, label):
    print(f"\n=== {label} ===")
    print(f"{'gate':>5s} {'t':>4s} {'n':>6s} {'rev':>4s} {'rev%':>6s} {'95% CI':>14s} "
          f"{'EV/$1':>7s} {'buyable@1c':>11s}")
    for g in GATES:
        for T in TGRID:
            s = [r for r in sel if r[3] >= g and r[2] == T]
            if len(s) < 40:
                continue
            n = len(s); k = sum(r[4] for r in s); p = k / n
            se = math.sqrt(p * (1 - p) / n)
            lo, hi = max(0, p - 1.96 * se), p + 1.96 * se
            buy = [r for r in s if r[5] is not None and r[5] <= 0.010001]
            print(f"{g:5d} {T:4d} {n:6d} {k:4d} {100*p:6.2f} "
                  f"{f'{100*lo:.2f}-{100*hi:.2f}':>14s} {p-0.01:+7.4f} "
                  f"{100*len(buy)/n:10.0f}%")

allr = rows
rep([r for r in allr if r[6]], "12:30-16:00 UTC (the halted window) -- the thesis")
rep([r for r in allr if not r[6]], "OUTSIDE the window (mintsalvage trades here)")
