"""Round 2 on the 99c mint-and-ask idea.

Recon: (a) real visible depth AT the 0.99 ask level (uas/das when ua/da==0.99)
-- the honest queue for open-placed asks (fresh book => front of FIFO; late
joiners queue behind us); (b) TIMING split: winner 0.99-prints (drag) vs loser
0.99-prints (jackpot) by tl -- if jackpots are mid-bar and drag is endgame, a
cancel-at-tl keeps one and sheds the other.

Sims: ride with cancel-at-tl sweep; matched-size user rule (5c leg sized to
the hi fill -- kills the partial-fill disaster); per-coin and per-day jackpot
stability."""
import math
from collections import Counter, defaultdict
import fast

COINS5 = ["btc", "eth", "sol", "xrp", "bnb", "doge"]


def depth99(coins, label):
    ds = []
    for coin in coins:
        for ws, m in fast.load(coin).items():
            for s in m["snaps"]:
                for ai, si in ((5, 6), (7, 8)):
                    if s[ai] is not None and abs(s[ai] - 0.99) < 1e-9 and s[si]:
                        ds.append(s[si])
    ds.sort()
    n = len(ds)
    if not n:
        print(f"{label}: 0.99 never best ask"); return
    print(f"{label}: 0.99 at best ask in {n:,} snap-secs; visible size "
          f"p25={ds[n//4]:.0f} med={ds[n//2]:.0f} p75={ds[3*n//4]:.0f} p95={ds[int(.95*n)]:.0f}")


def timing(coins, bar, label):
    wtl, jtl = [], []
    for coin in coins:
        for ws, m in fast.load(coin).items():
            wtok = "U" if m["win"] == "UP" else "D"
            wfirst = None
            for tl, tok, px, sz, side in m["sells"]:
                if side != "BUY" or px < 0.99 - 1e-9: continue
                if tok == wtok:
                    if wfirst is None: wfirst = tl
                else:
                    jtl.append(tl)
            if wfirst is not None: wtl.append(wfirst)
    def dist(v, name):
        if not v: print(f"  {name}: none"); return
        v = sorted(v)
        frac_end = sum(1 for x in v if x < bar * 0.2) / len(v)
        frac_post = sum(1 for x in v if x < 0) / len(v)
        print(f"  {name}: n={len(v)} med tl={v[len(v)//2]:.0f}s  "
              f"in final-20%-of-bar-or-later: {100*frac_end:.0f}%  post-close: {100*frac_post:.0f}%")
    print(f"{label}:")
    dist(wtl, "winner first >=0.99 BUY (drag)")
    dist(jtl, "loser >=0.99 BUY prints (jackpot)")


def sim(coins, k_hi=0.99, size=100.0, hid=0.0, cancel_tl=None, lo=None,
        react=1.0):
    """ride + optional cancel of BOTH hi asks at tl=cancel_tl; optional
    matched-size lo leg (price lo) armed react after a hi fill."""
    out = []
    for coin in coins:
        for ws, m in fast.load(coin).items():
            wtok = "U" if m["win"] == "UP" else "D"
            qh = {"U": hid, "D": hid}
            fh = {"U": 0.0, "D": 0.0}
            first_hi = None
            lo_tok, ql, fl, lo_cap = None, 200.0, 0.0, 0.0
            for tl, tok, px, sz, side in m["sells"]:
                if side != "BUY": continue
                live = cancel_tl is None or tl > cancel_tl
                if lo is not None and first_hi and lo_tok is None and tl <= first_hi[0] - react:
                    lo_tok = "D" if first_hi[1] == "U" else "U"
                    lo_cap = fh[first_hi[1]]              # matched size only
                if live and px >= k_hi - 1e-9 and fh[tok] < size:
                    s2 = sz
                    if qh[tok] > 0:
                        u = min(qh[tok], s2); qh[tok] -= u; s2 -= u
                    if s2 > 0:
                        fh[tok] += min(s2, size - fh[tok])
                        if first_hi is None: first_hi = (tl, tok)
                if lo is not None and lo_tok == tok and px >= lo - 1e-9 and fl < lo_cap:
                    s2 = sz
                    if ql > 0:
                        u = min(ql, s2); ql -= u; s2 -= u
                    if s2 > 0:
                        fl += min(s2, lo_cap - fl)
            cash = (fh["U"] + fh["D"]) * k_hi + fl * (lo or 0)
            unsold_w = size - fh[wtok] - (fl if lo_tok == wtok else 0.0)
            cash += max(unsold_w, 0.0)
            net = cash - size
            out.append(dict(ws=ws, coin=coin, net=net,
                            jack=fh["D" if wtok == "U" else "U"] > 0.5,
                            whi=fh[wtok] > 0.5))
    return out


def rep(rows, label):
    n = len(rows)
    net = sum(r["net"] for r in rows)
    whi = sum(1 for r in rows if r["whi"]); jack = sum(1 for r in rows if r["jack"])
    vals = [r["net"] for r in rows]
    mu = net / n
    sd = math.sqrt(sum((x - mu) ** 2 for x in vals) / (n - 1)) if n > 1 else 0
    t = mu / (sd / math.sqrt(n)) if sd else 0
    return (f"{label:46s} bars={n:4d} win99={100*whi/n:3.0f}% jack={jack:3d} "
            f"NET=${net:+9.2f} ${mu:+.4f}/bar t={t:+6.2f} worst=${min(vals):+.2f}")


if __name__ == "__main__":
    print("== visible depth at the 0.99 ask level ==")
    depth99(["btc"], "5m btc"); depth99(COINS5, "5m x6"); depth99(["btc-mrec1h"], "1h btc")

    print("\n== timing: drag vs jackpot ==")
    timing(["btc"], 300, "5m btc"); timing(COINS5, 300, "5m x6")

    print("\n== ride + cancel-at-tl sweep (5m x6) ==")
    for hid in (0, 100, 300):
        for ct in (None, 20.0, 45.0, 90.0):
            print(rep(sim(COINS5, hid=hid, cancel_tl=ct),
                      f"5m x6 ride hid={hid} cancel@{ct}"))
        print()
    print("== matched-size user rule (disaster-proofed), hid=100 ==")
    for ct in (None, 45.0):
        print(rep(sim(COINS5, hid=100, cancel_tl=ct, lo=0.05),
                  f"5m x6 matched-5c hid=100 cancel@{ct}"))
    print("\n== per-coin, ride hid=100 cancel@45 ==")
    for c in COINS5:
        print(rep(sim([c], hid=100, cancel_tl=45.0), f"5m {c}"))
    print("\n== per-day (pooled x6), ride hid=100 cancel@45 ==")
    rows = sim(COINS5, hid=100, cancel_tl=45.0)
    days = defaultdict(list)
    import datetime as dt
    for r in rows:
        days[dt.datetime.fromtimestamp(r["ws"], dt.UTC).strftime("%m-%d")].append(r)
    for d in sorted(days):
        print(rep(days[d], f"  {d}"))
    print("\n== 1h, ride, cancel sweep ==")
    for ct in (None, 300.0):
        print(rep(sim(["btc-mrec1h"], hid=100, cancel_tl=ct), f"1h ride hid=100 cancel@{ct}"))
