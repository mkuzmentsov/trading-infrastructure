"""Round 3: the user's conditional flip.

Rule under test (fully implementable, matched sizes everywhere):
  mint SIZE pairs, rest 99c asks on both tokens.
  When ONE token's 99c ask is filled COMPLETELY (partial fills never trigger
  anything -- kills the false-spike disaster):
     if the spot lead TOWARD that token >= Y bps (and optionally tl <= X):
         flip: cancel the complement's 99c ask, place a 5c ask on the
         complement, sized to what we actually hold unsold.
     else: leave everything be (ride -- the jackpot stays alive).

Hypothesis: jackpots (0.99 prints that later reverse) can only happen at
SMALL |lead| (only a few-bps lead can flip in the endgame; the 0.99 book is
sigma*sqrt(t)->0 overreaction), while decided bars have big |lead|. If true,
the gate collects +5c on corpses without capping the +99c jackpots.

Event study first: |lead| at the first winner->=0.99 BUY print vs at loser
>=0.99 prints, plus the >=0.99 BUY volume per event (full-fill feasibility).
"""
import bisect, math, pickle, os
from collections import defaultdict
import fast

CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")
COINS5 = ["btc", "eth", "sol", "xrp", "bnb", "doge"]
_leads = {}


def leads(coin):
    if coin not in _leads:
        with open(f"{CACHE}/{coin}-leads.pkl", "rb") as fh:
            _leads[coin] = pickle.load(fh)
    return _leads[coin]


def lead_at(series, tl):
    if not series:
        return None
    keys = [-s[0] for s in series]              # ascending
    i = bisect.bisect_left(keys, -tl)
    if i >= len(series):
        i = len(series) - 1
    return series[i][1]


def q(v, p):
    xs = sorted(x for x in v if x is not None)
    return xs[min(int(p * len(xs)), len(xs) - 1)] if xs else None


def event_study(coins, label):
    drag, jack = [], []
    for coin in coins:
        L = leads(coin)
        for ws, m in fast.load(coin).items():
            wtok = "U" if m["win"] == "UP" else "D"
            ser = L.get(ws, [])
            seen_w = False; seen_j = False
            vol = {"U": 0.0, "D": 0.0}
            first = {}
            for tl, tok, px, sz, side in m["sells"]:
                if side != "BUY" or px < 0.99 - 1e-9:
                    continue
                vol[tok] += sz
                if tok not in first:
                    first[tok] = tl
            for tok in first:
                lb = lead_at(ser, first[tok])
                if lb is None:
                    continue
                toward = lb if tok == "U" else -lb
                rec = dict(coin=coin, ws=ws, tl=first[tok], toward=toward,
                           vol=vol[tok])
                (drag if tok == wtok else jack).append(rec)
    print(f"\n== {label}: lead TOWARD the printing token at first >=0.99 print ==")
    for name, ev in (("drag (true winner)", drag), ("JACKPOT (later flips)", jack)):
        if not ev:
            print(f"  {name}: none"); continue
        tw = [e["toward"] for e in ev]
        vv = [e["vol"] for e in ev]
        print(f"  {name}: n={len(ev)}  toward-lead bps p10={q(tw,.1):+.1f} p25={q(tw,.25):+.1f} "
              f"med={q(tw,.5):+.1f} p75={q(tw,.75):+.1f}   >=0.99-vol/event med={q(vv,.5):,.0f}sh p25={q(vv,.25):,.0f}")
    # separation table
    for Y in (3, 6, 10, 15, 25):
        dbig = sum(1 for e in drag if e["toward"] >= Y)
        jbig = sum(1 for e in jack if e["toward"] >= Y)
        print(f"    gate Y={Y:>2}bps: flips {100*dbig/max(len(drag),1):3.0f}% of drag events, "
              f"wrongly flips {jbig}/{len(jack)} jackpots")
    return drag, jack


def sim(coins, Y=None, size=100.0, hid=100.0, hid_lo=200.0, k_hi=0.99, k_lo=0.05,
        react=1.0, tl_gate=None, mode="gated"):
    """mode: 'gated' (flip on full fill iff toward>=Y [and tl<=tl_gate]),
    'always' (flip on any full fill), 'ride' (never flip)."""
    out = []
    for coin in coins:
        L = leads(coin)
        for ws, m in fast.load(coin).items():
            wtok = "U" if m["win"] == "UP" else "D"
            ser = L.get(ws, [])
            qh = {"U": hid, "D": hid}
            fh = {"U": 0.0, "D": 0.0}
            open_hi = {"U": True, "D": True}
            full_t = None; full_tok = None
            flipped = False; flip_capped_jack = False
            lo_tok, ql, fl, lo_cap = None, hid_lo, 0.0, 0.0
            for tl, tok, px, sz, side in m["sells"]:
                if side != "BUY":
                    continue
                # arm flip decision react secs after full fill
                if (mode != "ride" and full_t is not None and not flipped
                        and lo_tok is None and tl <= full_t - react):
                    toward = None
                    if ser:
                        lb = lead_at(ser, full_t)
                        toward = (lb if full_tok == "U" else -lb) if lb is not None else None
                    ok = (mode == "always") or (Y is not None and toward is not None and toward >= Y)
                    if ok and tl_gate is not None:
                        ok = full_t <= tl_gate
                    if ok:
                        other = "D" if full_tok == "U" else "U"
                        open_hi[other] = False
                        lo_tok = other
                        lo_cap = size - fh[other]
                        flipped = True
                        if other == wtok:
                            flip_capped_jack = True
                if open_hi[tok] and px >= k_hi - 1e-9 and fh[tok] < size:
                    s2 = sz
                    if qh[tok] > 0:
                        u = min(qh[tok], s2); qh[tok] -= u; s2 -= u
                    if s2 > 0:
                        fh[tok] += min(s2, size - fh[tok])
                        if fh[tok] >= size - 0.5 and full_t is None:
                            full_t, full_tok = tl, tok
                if lo_tok == tok and px >= k_lo - 1e-9 and fl < lo_cap:
                    s2 = sz
                    if ql > 0:
                        u = min(ql, s2); ql -= u; s2 -= u
                    if s2 > 0:
                        fl += min(s2, lo_cap - fl)
            cash = (fh["U"] + fh["D"]) * k_hi + fl * k_lo
            unsold_w = size - fh[wtok] - (fl if lo_tok == wtok else 0.0)
            cash += max(unsold_w, 0.0)
            out.append(dict(ws=ws, coin=coin, net=cash - size,
                            jack=fh["D" if wtok == "U" else "U"] > 0.5,
                            capped=flip_capped_jack, lo=fl > 0.5,
                            flipped=flipped))
    return out


def rep(rows, label):
    n = len(rows)
    net = sum(r["net"] for r in rows)
    jack = sum(1 for r in rows if r["jack"])
    capped = sum(1 for r in rows if r["capped"])
    fl = sum(1 for r in rows if r["flipped"])
    lo = sum(1 for r in rows if r["lo"])
    vals = [r["net"] for r in rows]
    mu = net / n
    sd = math.sqrt(sum((x - mu) ** 2 for x in vals) / (n - 1)) if n > 1 else 0
    t = mu / (sd / math.sqrt(n)) if sd else 0
    return (f"{label:44s} bars={n:4d} flip={100*fl/n:3.0f}% lo5={100*lo/n:2.0f}% jack={jack:3d} "
            f"capped={capped:2d} NET=${net:+8.2f} ${mu:+.4f}/bar t={t:+5.2f} worst=${min(vals):+.2f}")


if __name__ == "__main__":
    event_study(["btc"], "5m btc")
    event_study(COINS5, "5m all six")
    event_study(["btc-mrec1h"], "1h btc")

    for hid in (0, 100, 300, 1000):
        print(f"\n== 5m x6, hid={hid} ==")
        print(rep(sim(COINS5, mode="ride", hid=hid), f"ride"))
        print(rep(sim(COINS5, mode="always", hid=hid), f"flip always (full-fill only)"))
        for Y in (6, 10, 15, 25):
            print(rep(sim(COINS5, mode="gated", Y=Y, hid=hid), f"gated flip Y={Y}bps"))
    print(f"\n== 1h btc, hid=100 ==")
    print(rep(sim(["btc-mrec1h"], mode="ride", hid=100), "ride"))
    print(rep(sim(["btc-mrec1h"], mode="always", hid=100), "flip always"))
    for Y in (10, 25, 50):
        print(rep(sim(["btc-mrec1h"], mode="gated", Y=Y, hid=100), f"gated Y={Y}bps"))
