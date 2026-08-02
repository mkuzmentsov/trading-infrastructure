"""User build spec (2026-08-02, round 4): mint PRE-OPEN (next1/cur+2 market,
book near 50/50 -- earliest FIFO priority), rest 99c asks on both tokens.
On every FILL INCREMENT of q shares at 0.99 on token X, place/extend a 3c ask
for exactly q shares on the complement Y (matched size, incremental -- the
precise-fill-amount rule). Hold everything else to redemption.

Per matched pair: both legs fill -> 0.99+0.03 = 1.02 -> +2c outcome-immune.
3c never fills -> X=winner: -1c; X=loser (jackpot): +99c -- but in jackpot
bars Y is the WINNER whose 3c ask always fills, so jackpots cap at +2c.
Break-even needs P(3c fills | corpse) > 1/3.

Recon: that probability, measured directly. Then the sim grid vs ride.
"""
import math
from collections import defaultdict
import fast

COINS5 = ["btc", "eth", "sol", "xrp", "bnb", "doge"]


def recon_p3(coins, label, k_lo=0.03):
    n99 = 0; p3 = 0; vol3 = []
    for coin in coins:
        for ws, m in fast.load(coin).items():
            wtok = "U" if m["win"] == "UP" else "D"
            wfirst = None
            for tl, tok, px, sz, side in m["sells"]:
                if side == "BUY" and px >= 0.99 - 1e-9 and tok == wtok:
                    wfirst = tl; break
            if wfirst is None:
                continue
            n99 += 1
            v = sum(sz for tl, tok, px, sz, side in m["sells"]
                    if side == "BUY" and tok != wtok and tl < wfirst
                    and px >= k_lo - 1e-9)
            if v > 0:
                p3 += 1; vol3.append(v)
    vol3.sort()
    med = vol3[len(vol3) // 2] if vol3 else 0
    print(f"{label}: winner-99 bars={n99}; loser BUY-printed >={k_lo} after: "
          f"{p3} ({100 * p3 / max(n99, 1):.1f}%)  [break-even 33%]  "
          f"med volume when it happens: {med:,.0f}sh")


def sim(coins, size=100.0, hid_hi=100.0, hid_lo=200.0, k_hi=0.99, k_lo=0.03,
        react=1.0, flip=True):
    out = []
    for coin in coins:
        for ws, m in fast.load(coin).items():
            wtok = "U" if m["win"] == "UP" else "D"
            qh = {"U": hid_hi, "D": hid_hi}
            ql = {"U": hid_lo, "D": hid_lo}
            fh = {"U": 0.0, "D": 0.0}         # sold at 0.99
            fl = {"U": 0.0, "D": 0.0}         # sold at k_lo
            pend = []                          # (arm_tl, lo_tok, qty) awaiting react lag
            cap = {"U": 0.0, "D": 0.0}         # armed lo size per token
            for tl, tok, px, sz, side in m["sells"]:
                if side != "BUY":
                    continue
                while pend and tl <= pend[0][0]:
                    _, lt, qty = pend.pop(0)
                    cap[lt] = min(cap[lt] + qty, size - fh[lt] - fl[lt])
                # hi legs
                if px >= k_hi - 1e-9 and fh[tok] < size - fl[tok]:
                    s2 = sz
                    if qh[tok] > 0:
                        u = min(qh[tok], s2); qh[tok] -= u; s2 -= u
                    if s2 > 0:
                        got = min(s2, size - fh[tok] - fl[tok])
                        if got > 0:
                            fh[tok] += got
                            if flip:
                                other = "D" if tok == "U" else "U"
                                pend.append((tl - react, other, got))
                # lo legs
                if flip and px >= k_lo - 1e-9 and fl[tok] < cap[tok]:
                    s2 = sz
                    if ql[tok] > 0:
                        u = min(ql[tok], s2); ql[tok] -= u; s2 -= u
                    if s2 > 0:
                        fl[tok] += min(s2, cap[tok] - fl[tok])
            cash = (fh["U"] + fh["D"]) * k_hi + (fl["U"] + fl["D"]) * k_lo
            unsold_w = size - fh[wtok] - fl[wtok]
            cash += max(unsold_w, 0.0)
            ltok = "D" if wtok == "U" else "U"
            out.append(dict(ws=ws, coin=coin, net=cash - size,
                            jack=fh[ltok] > 0.5,
                            locked=min(fh["U"], fl["D"]) + min(fh["D"], fl["U"]),
                            orphan=(fh[wtok] > 0.5 and fl[ltok] < fh[wtok] - 0.5)))
    return out


def rep(rows, label):
    n = len(rows)
    net = sum(r["net"] for r in rows)
    jack = sum(1 for r in rows if r["jack"])
    orph = sum(1 for r in rows if r["orphan"])
    vals = [r["net"] for r in rows]
    mu = net / n
    sd = math.sqrt(sum((x - mu) ** 2 for x in vals) / (n - 1)) if n > 1 else 0
    t = mu / (sd / math.sqrt(n)) if sd else 0
    pos = sum(1 for x in vals if x > 0.001)
    return (f"{label:44s} bars={n:4d} pos={100*pos/n:3.0f}% orphan={100*orph/n:3.0f}% jack={jack:3d} "
            f"NET=${net:+8.2f} ${mu:+.4f}/bar t={t:+5.2f} worst=${min(vals):+.2f}")


if __name__ == "__main__":
    print("== recon: P(loser prints >= k_lo AFTER winner's first 0.99) ==")
    for kl in (0.02, 0.03, 0.05):
        recon_p3(COINS5, f"5m x6  k_lo={kl}", k_lo=kl)
        recon_p3(["btc"], f"5m btc k_lo={kl}", k_lo=kl)
    recon_p3(["btc-mrec1h"], "1h btc k_lo=0.03", k_lo=0.03)

    print("\n== THE BUILD: matched incremental 3c flip, pre-open entry ==")
    for hid in (0, 100, 300, 1000, 3000):
        print(rep(sim(COINS5, hid_hi=hid), f"5m x6 flip3c hid_hi={hid}"))
    print()
    for hid in (0, 100, 300):
        print(rep(sim(COINS5, hid_hi=hid, flip=False), f"5m x6 RIDE (no flip) hid_hi={hid}"))
    print()
    for kl in (0.02, 0.05):
        print(rep(sim(COINS5, hid_hi=100, k_lo=kl), f"5m x6 flip{kl} hid_hi=100"))
    print(rep(sim(COINS5, hid_hi=100, hid_lo=0), "5m x6 flip3c hid_lo=0"))
    print(rep(sim(COINS5, hid_hi=100, react=3.0), "5m x6 flip3c react=3s"))
    print("\n== per-coin, flip3c hid_hi=100 ==")
    for c in COINS5:
        print(rep(sim([c], hid_hi=100), f"5m {c}"))
    print("\n== 1h btc ==")
    for hid in (0, 100, 300):
        print(rep(sim(["btc-mrec1h"], hid_hi=hid), f"1h flip3c hid_hi={hid}"))
        print(rep(sim(["btc-mrec1h"], hid_hi=hid, flip=False), f"1h RIDE hid_hi={hid}"))
