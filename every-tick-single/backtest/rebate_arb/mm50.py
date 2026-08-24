"""Two-sided 49/50 resting maker (user, 2026-08-06).

Rest a post-only BUY at 0.49 on BOTH sides; try to unwind at 0.50.
Unified book: ub = 1 - da, so a 0.49 bid on UP fills when the market's best
bid on UP falls to 0.49 -- i.e. price came DOWN to us. That is the whole
question: when we get filled, is it because of noise (good) or because the
move is continuing (fatal)?

Simulated per bar from the book tape:
  - bid 0.49 both sides, live from bar open
  - a side FILLS when its best bid <= 0.49 (the market reached our price)
  - after a fill we post 0.50 to unwind; that fills if its best bid >= 0.50
  - unfilled inventory is held to resolution (1.00 or 0.00)
Maker side is fee-free on these markets, so no fee drag is modelled.
"""
import pickle
from collections import Counter

COINS = ["btc", "eth", "sol", "xrp", "bnb", "doge"]
BUY, SELL = 0.49, 0.50
c = Counter(); pnl = 0.0; bars = 0

for coin in COINS:
    try:
        mk = pickle.load(open(f"cache/{coin}.pkl", "rb"))
    except FileNotFoundError:
        continue
    for ws, m in mk.items():
        win = m.get("win"); snaps = m.get("snaps")
        if win not in ("UP", "DOWN") or not snaps:
            continue
        s = sorted([x for x in snaps if 0 <= x[0] <= 300], key=lambda x: -x[0])
        if len(s) < 30:
            continue
        bars += 1
        state = {"UP": None, "DOWN": None}      # None | "long" | "flat(done)"
        for snap in s:
            for side, bid in (("UP", snap[1]), ("DOWN", snap[3])):
                if bid is None:
                    continue
                if state[side] is None and bid <= BUY + 1e-9:
                    state[side] = "long"                    # bought at 0.49
                elif state[side] == "long" and bid >= SELL - 1e-9:
                    state[side] = "done"                    # unwound at 0.50
                    pnl += SELL - BUY
                    c["round_trip_+1c"] += 1
        for side in ("UP", "DOWN"):
            if state[side] == "long":                       # stuck, hold to resolution
                got = 1.0 if win == side else 0.0
                pnl += got - BUY
                c["stuck_WON" if got else "stuck_LOST"] += 1
            elif state[side] is None:
                c["never_filled"] += 1

fills = c["round_trip_+1c"] + c["stuck_WON"] + c["stuck_LOST"]
stuck = c["stuck_WON"] + c["stuck_LOST"]
print(f"bars simulated: {bars}   side-slots: {bars*2}")
print(f"  never filled      : {c['never_filled']:5d}")
print(f"  round-tripped +1c : {c['round_trip_+1c']:5d}")
print(f"  stuck & WON  +51c : {c['stuck_WON']:5d}")
print(f"  stuck & LOST -49c : {c['stuck_LOST']:5d}")
if stuck:
    print(f"\n  ** filled-and-stuck win rate: {100*c['stuck_WON']/stuck:.1f}%  "
          f"(need >49.0% to break even on a 49c buy) **")
if fills:
    print(f"  total PnL {pnl:+.2f} over {fills} fills = {100*pnl/fills:+.2f}c per fill")
    print(f"  per bar: {pnl/bars:+.4f}  ->  {'PROFITABLE' if pnl>0 else 'LOSS-MAKING'}")
