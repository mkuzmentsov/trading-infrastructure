"""Round 5: the post-close window (user 2026-08-02). Orders keep working after
the bar closes and before resolution posts -- and the winner's ask side is
typically EMPTY there (nobody offers at 0.99 post-close), so post-close fills
may face zero queue, unlike in-bar fills vs the measured 4,265sh wall.

Measures: (1) post-close BUY volume at >=0.99 on the winner and >=0.02 on the
loser; (2) post-close ask-side competition on the winner (ua distribution);
(3) the round-4 btc flip2c PnL split by fill window; (4) a POST-CLOSE-ONLY
variant: arm both 99c asks at tl=0 (no resolution knowledge -- the loser's
99c just never fills), matched 2c flip as before."""
import math
import fast

COINS5 = ["btc", "eth", "sol", "xrp", "bnb", "doge"]


def recon_post(coins, label):
    n = 0
    w99 = []; l2 = []; l2bars = 0; w99bars = 0
    ask_none = ask_low = ask_snaps = 0
    for coin in coins:
        for ws, m in fast.load(coin).items():
            n += 1
            wtok = "U" if m["win"] == "UP" else "D"
            v99 = v2 = 0.0
            for tl, tok, px, sz, side in m["sells"]:
                if tl >= 0 or side != "BUY":
                    continue
                if tok == wtok and px >= 0.99 - 1e-9:
                    v99 += sz
                if tok != wtok and px >= 0.02 - 1e-9:
                    v2 += sz
            w99.append(v99); l2.append(v2)
            w99bars += v99 > 0; l2bars += v2 > 0
            for s in m["snaps"]:
                if s[0] >= 0:
                    continue
                ask_snaps += 1
                ua = s[5] if wtok == "U" else s[7]
                if ua is None:
                    ask_none += 1
                elif ua <= 0.99 + 1e-9:
                    ask_low += 1
    w99.sort(); l2.sort()
    tot99 = sum(w99); tot2 = sum(l2)
    print(f"\n== {label}: post-close window, {n} bars ==")
    print(f"  winner >=0.99 BUY: {w99bars}/{n} bars ({100*w99bars/n:.0f}%), "
          f"total {tot99:,.0f}sh, mean/bar {tot99/n:,.0f}sh, p90 {w99[int(.9*len(w99))]:,.0f}sh")
    print(f"  loser  >=0.02 BUY: {l2bars}/{n} bars ({100*l2bars/n:.0f}%), "
          f"total {tot2:,.0f}sh, mean/bar {tot2/n:,.0f}sh")
    print(f"  winner ask-side post-close: EMPTY {100*ask_none/max(ask_snaps,1):.0f}% "
          f"of snap-secs, ask<=0.99 present {100*ask_low/max(ask_snaps,1):.0f}%")


def sim(coins, size=100.0, hid_hi=100.0, hid_lo=200.0, k_hi=0.99, k_lo=0.02,
        react=1.0, arm_tl=None, hid_hi_post=None):
    """arm_tl=None: asks live from the start (round-4). arm_tl=0.0: post-close
    only. hid_hi_post: queue for hi fills from post-close prints (defaults to
    hid_hi); lets in-bar fills face the wall while post-close fills face ~0."""
    out = []
    for coin in coins:
        for ws, m in fast.load(coin).items():
            wtok = "U" if m["win"] == "UP" else "D"
            qh = {"U": hid_hi, "D": hid_hi}
            qhp = {"U": hid_hi_post if hid_hi_post is not None else hid_hi,
                   "D": hid_hi_post if hid_hi_post is not None else hid_hi}
            ql = {"U": hid_lo, "D": hid_lo}
            fh = {"U": 0.0, "D": 0.0}; fh_post = {"U": 0.0, "D": 0.0}
            fl = {"U": 0.0, "D": 0.0}; fl_post = {"U": 0.0, "D": 0.0}
            pend = []; cap = {"U": 0.0, "D": 0.0}
            for tl, tok, px, sz, side in m["sells"]:
                if side != "BUY":
                    continue
                if arm_tl is not None and tl > arm_tl:
                    continue
                while pend and tl <= pend[0][0]:
                    _, lt, qty = pend.pop(0)
                    cap[lt] = min(cap[lt] + qty, size - fh[lt] - fl[lt])
                post = tl < 0
                if px >= k_hi - 1e-9 and fh[tok] < size - fl[tok]:
                    q = qhp if post else qh
                    s2 = sz
                    if q[tok] > 0:
                        u = min(q[tok], s2); q[tok] -= u; s2 -= u
                    if s2 > 0:
                        got = min(s2, size - fh[tok] - fl[tok])
                        if got > 0:
                            fh[tok] += got
                            if post: fh_post[tok] += got
                            other = "D" if tok == "U" else "U"
                            pend.append((tl - react, other, got))
                if px >= k_lo - 1e-9 and fl[tok] < cap[tok]:
                    s2 = sz
                    if ql[tok] > 0:
                        u = min(ql[tok], s2); ql[tok] -= u; s2 -= u
                    if s2 > 0:
                        got = min(s2, cap[tok] - fl[tok])
                        fl[tok] += got
                        if post: fl_post[tok] += got
            cash = (fh["U"] + fh["D"]) * k_hi + (fl["U"] + fl["D"]) * k_lo
            unsold_w = size - fh[wtok] - fl[wtok]
            cash += max(unsold_w, 0.0)
            ltok = "D" if wtok == "U" else "U"
            out.append(dict(ws=ws, coin=coin, net=cash - size,
                            hi_post=fh_post["U"] + fh_post["D"],
                            lo_post=fl_post["U"] + fl_post["D"],
                            hi=fh["U"] + fh["D"], lo=fl["U"] + fl["D"],
                            jack=fh[ltok] > 0.5))
    return out


def rep(rows, label):
    n = len(rows)
    net = sum(r["net"] for r in rows)
    hi = sum(r["hi"] for r in rows); hip = sum(r["hi_post"] for r in rows)
    lo = sum(r["lo"] for r in rows); lop = sum(r["lo_post"] for r in rows)
    vals = [r["net"] for r in rows]
    mu = net / n
    sd = math.sqrt(sum((x - mu) ** 2 for x in vals) / (n - 1)) if n > 1 else 0
    t = mu / (sd / math.sqrt(n)) if sd else 0
    return (f"{label:46s} bars={n:4d} hi_fills={hi:7,.0f}sh ({100*hip/max(hi,1):3.0f}% post) "
            f"lo={lo:7,.0f}sh ({100*lop/max(lo,1):3.0f}% post) "
            f"NET=${net:+8.2f} ${mu:+.4f}/bar t={t:+5.2f}")


if __name__ == "__main__":
    recon_post(["btc"], "5m btc")
    recon_post(COINS5, "5m x6")
    recon_post(["btc-mrec1h"], "1h btc")

    print("\n== round-4 btc flip2c, fills split by window ==")
    for hid in (0, 100, 300):
        print(rep(sim(["btc"], hid_hi=hid, hid_lo=0), f"btc flip2c hid_hi={hid} (full)"))
    print("\n== realistic split queue: in-bar hi vs the wall, post-close hi vs EMPTY ==")
    for hid in (300, 1000, 3000):
        print(rep(sim(["btc"], hid_hi=hid, hid_hi_post=0, hid_lo=0),
                  f"btc flip2c inbar_hid={hid} post_hid=0"))
    print("\n== POST-CLOSE-ONLY variant (arm both asks at tl=0) ==")
    for hid in (0, 100):
        print(rep(sim(["btc"], hid_hi=hid, hid_lo=0, arm_tl=0.0), f"btc postonly hid={hid}"))
        print(rep(sim(COINS5, hid_hi=hid, hid_lo=0, arm_tl=0.0), f"x6  postonly hid={hid}"))
    print(rep(sim(["btc-mrec1h"], hid_hi=0, hid_lo=0, arm_tl=0.0), "1h postonly hid=0"))
