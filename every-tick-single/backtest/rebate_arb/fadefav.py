"""Fade-the-favorite via mint (user idea 2026-08-02 evening).

Mint $1 mid-bar, taker-SELL the expensive side at its BID, hold the cheap
side to resolution. Unified-book identity: this is exactly BUYING the
underdog at (1 - fav_bid). Pays iff the mid-bar favorite is overpriced.

Per pair: pnl = fav_bid + 1{dog wins} - 1. Also reports realized dog win
rate vs implied (1 - fav_bid): the calibration view.
"""
import math
from collections import defaultdict
import fast

TGRID = [240, 180, 120, 90, 60, 30]
BANDS = [(0.55, 0.65), (0.65, 0.75), (0.75, 0.85), (0.85, 0.95)]


def run(coins):
    rows = []
    for coin in coins:
        for ws, m in fast.load(coin).items():
            win = m["win"]
            for s in m["snaps"]:
                tl, ub, _, db, _, ua, _, da, _ = s
                for T in TGRID:
                    if abs(tl - T) > 1.5:
                        continue
                    if ub is None or db is None:
                        continue
                    if ub > 0.5 and ub > db:
                        fav, fav_bid = "UP", ub
                    elif db > 0.5:
                        fav, fav_bid = "DOWN", db
                    else:
                        continue
                    dog_wins = win != fav
                    rows.append((coin, ws, T, fav_bid, dog_wins,
                                 fav_bid + (1.0 if dog_wins else 0.0) - 1.0))
    return rows


def rep(rows, label):
    print(f"\n=== {label}: {len(rows)} samples ===")
    print(f"{'T':>4s} {'band':>10s} {'n':>6s} {'implied dog%':>12s} {'real dog%':>10s} "
          f"{'EV/pair c':>10s} {'t':>6s}")
    for T in TGRID:
        for lo, hi in BANDS:
            sel = [r for r in rows if r[2] == T and lo <= r[3] < hi]
            if len(sel) < 30:
                continue
            n = len(sel)
            dogw = sum(r[4] for r in sel) / n
            imp = 1.0 - sum(r[3] for r in sel) / n
            ev = sum(r[5] for r in sel) / n
            sd = math.sqrt(sum((r[5] - ev) ** 2 for r in sel) / (n - 1))
            t = ev / (sd / math.sqrt(n)) if sd else 0
            print(f"{T:4d} {f'{lo}-{hi}':>10s} {n:6d} {100*imp:12.1f} {100*dogw:10.1f} "
                  f"{100*ev:+10.2f} {t:+6.2f}")


if __name__ == "__main__":
    btc = run(["btc"])
    rep(btc, "btc 5m")
    pooled = run(["btc", "eth", "sol", "xrp", "bnb", "doge"])
    rep(pooled, "pooled x6")
