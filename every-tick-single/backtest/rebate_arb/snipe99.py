"""Mint 50/50 + resting 99c asks on both tokens (user idea 2026-08-02).

Baseline shift vs the dual-ask farm: an unsold minted pair redeems at exactly
$1.00, so doing nothing costs nothing. Branches per 100sh pair:
  winner's 99c ask fills            -> -$1  (sold a $1.00 asset at 0.99)
  LOSER's 99c ask fills (spike that
  reverses; complement redeems $1)  -> +$99 jackpot
  loser sold at 5c after winner 99c -> +$5
  both sold (user rule)             -> +$4 flat, outcome-immune -- which CAPS
                                       jackpot bars to +$4 (the 5c ask on a
                                       secretly-winning complement always fills)
Rules are fully sequential/implementable; 1s reaction lag everywhere; fills
FIFO behind hidden queue (0.99 level live-calibrated at ~3,000sh in §4).
Prints include the post-close window (asks rest until resolution).

Recon first: does taker-BUY flow at >=0.97 exist at all, and ever on the
eventual loser?
"""
import math
from collections import Counter
import fast

FEE_RATE, REBATE_SHARE = 0.07, 0.20
COINS5 = ["btc", "eth", "sol", "xrp", "bnb", "doge"]


def recon(coins, bar, label):
    n = 0
    win_hi = Counter(); lose_hi = Counter()   # bars where winner/loser printed >= K (BUY)
    lose_5_after = 0; jack_vol = 0.0
    postclose_hi = 0
    for coin in coins:
        for ws, m in fast.load(coin).items():
            n += 1
            wtok = "U" if m["win"] == "UP" else "D"
            whi = {}; lhi = {}
            first_whi_tl = None
            for tl, tok, px, sz, side in m["sells"]:
                if side != "BUY":
                    continue
                for K in (0.97, 0.98, 0.99):
                    if px >= K - 1e-9:
                        if tok == wtok:
                            whi[K] = True
                            if K == 0.99 and first_whi_tl is None:
                                first_whi_tl = tl
                            if K == 0.99 and tl < 0:
                                postclose_hi += 1
                        else:
                            lhi[K] = True
                            if K == 0.99:
                                jack_vol += sz
            for K in whi: win_hi[K] += 1
            for K in lhi: lose_hi[K] += 1
            # loser prints >=0.05 BUY after the winner's first 0.99 print
            if first_whi_tl is not None:
                for tl, tok, px, sz, side in m["sells"]:
                    if (side == "BUY" and tok != wtok and tl < first_whi_tl
                            and px >= 0.05 - 1e-9):
                        lose_5_after += 1
                        break
    print(f"\n== recon {label}: {n} bars ==")
    for K in (0.97, 0.98, 0.99):
        print(f"  winner BUY-printed >= {K}: {win_hi[K]:4d} bars ({100*win_hi[K]/n:.0f}%)   "
              f"LOSER >= {K}: {lose_hi[K]:3d} bars ({100*lose_hi[K]/n:.1f}%)")
    print(f"  loser BUY-printed >=0.05 AFTER winner's first 0.99 print: {lose_5_after} bars")
    print(f"  0.99+ BUY prints on winner post-close: {postclose_hi} prints; "
          f"jackpot volume (loser >=0.99 BUY): {jack_vol:,.0f} sh")


def sim(coins, k_hi=0.99, k_lo=0.05, size=100.0, hid_hi=0.0, hid_lo=0.0,
        react=1.0, mode="user"):
    """mode: 'user'  = on first hi-fill cancel other hi ask, place k_lo on other
             'ride'  = both hi asks all the way, no 5c leg, no cancel
             'gate'  = like user, but place k_lo only once other's bid <= 0.02"""
    out = []
    for coin in coins:
        for ws, m in fast.load(coin).items():
            wtok = "U" if m["win"] == "UP" else "D"
            prints = [p for p in m["sells"] if p[4] == "BUY"]     # chronological
            qh = {"U": hid_hi, "D": hid_hi}
            fh = {"U": 0.0, "D": 0.0}
            hi_open = {"U": True, "D": True}
            first_hi = None                    # (tl, tok)
            lo_tok, lo_armed_tl, ql, fl = None, None, hid_lo, 0.0
            for tl, tok, px, sz, side in prints:
                # arm the low ask (react lag after first hi fill)
                if mode in ("user", "gate") and first_hi and lo_tok is None:
                    if tl <= first_hi[0] - react:
                        other = "D" if first_hi[1] == "U" else "U"
                        ok = True
                        if mode == "gate":
                            b = None
                            for s in m["snaps"]:
                                if s[0] > first_hi[0] - react: continue
                                b = s[1] if other == "U" else s[3]; break
                            ok = (b is None or b <= 0.02)
                        if ok:
                            lo_tok, lo_armed_tl = other, tl
                # hi legs
                if hi_open[tok] and px >= k_hi - 1e-9 and fh[tok] < size:
                    if first_hi and mode in ("user", "gate") and tok != first_hi[1] \
                            and tl <= first_hi[0] - react:
                        pass                                   # cancelled
                    else:
                        s2 = sz
                        if qh[tok] > 0:
                            u = min(qh[tok], s2); qh[tok] -= u; s2 -= u
                        if s2 > 0:
                            got = min(s2, size - fh[tok]); fh[tok] += got
                            if first_hi is None:
                                first_hi = (tl, tok)
                # low leg
                if lo_tok == tok and px >= k_lo - 1e-9 and fl < size:
                    s2 = sz
                    if ql > 0:
                        u = min(ql, s2); ql -= u; s2 -= u
                    if s2 > 0:
                        fl += min(s2, size - fl)
            # settle vs $100 mint
            cash = fh["U"] * k_hi + fh["D"] * k_hi + fl * k_lo
            unsold_w = size - fh[wtok] - (fl if lo_tok == wtok else 0.0)
            cash += max(unsold_w, 0.0) * 1.0
            reb = sum(REBATE_SHARE * FEE_RATE * k_hi * (1 - k_hi) * fh[t] for t in "UD") \
                + REBATE_SHARE * FEE_RATE * k_lo * (1 - k_lo) * fl
            net = cash - size + reb
            jack = fh["D" if wtok == "U" else "U"] > 0.5
            out.append(dict(ws=ws, coin=coin, net=net, jack=jack,
                            whi=fh[wtok] > 0.5, lo=fl > 0.5))
    return out


def rep(rows, label):
    n = len(rows)
    if not n:
        return f"{label:44s} NO BARS"
    net = sum(r["net"] for r in rows)
    whi = sum(1 for r in rows if r["whi"])
    jack = sum(1 for r in rows if r["jack"])
    lo = sum(1 for r in rows if r["lo"])
    vals = [r["net"] for r in rows]
    mu = net / n
    sd = math.sqrt(sum((x - mu) ** 2 for x in vals) / (n - 1)) if n > 1 else 0
    t = mu / (sd / math.sqrt(n)) if sd else 0
    best = max(vals); worst = min(vals)
    return (f"{label:44s} bars={n:4d} win99={100*whi/n:3.0f}% jack={jack:3d} lo5={100*lo/n:3.0f}% "
            f"NET=${net:+9.2f} ${mu:+.4f}/bar t={t:+6.2f} best=${best:+.2f} worst=${worst:+.2f}")


if __name__ == "__main__":
    recon(["btc"], 300, "5m btc")
    recon(COINS5, 300, "5m all six")
    recon(["btc-mrec1h"], 3600, "1h btc")

    print("\n== user rule (cancel other 99, place 5c) vs ride, hid_hi sweep ==")
    for coins, lab in ((["btc"], "5m btc"), (COINS5, "5m x6"), (["btc-mrec1h"], "1h")):
        for mode in ("user", "ride", "gate"):
            for hh in (0, 500, 3000):
                print(rep(sim(coins, mode=mode, hid_hi=hh, hid_lo=200),
                          f"{lab} {mode} 0.99/0.05 hid_hi={hh}"))
        print()
    print("== price sweeps, 5m x6, user rule, hid_hi=500 ==")
    for kh in (0.97, 0.98, 0.99):
        for kl in (0.03, 0.05, 0.08):
            print(rep(sim(COINS5, k_hi=kh, k_lo=kl, hid_hi=500, hid_lo=200),
                      f"5m x6 user {kh}/{kl}"))
    print("\n== ride price sweep (jackpot hunt pure), 5m x6, hid_hi=500 ==")
    for kh in (0.97, 0.98, 0.99):
        print(rep(sim(COINS5, k_hi=kh, mode="ride", hid_hi=500),
                  f"5m x6 ride {kh}"))
