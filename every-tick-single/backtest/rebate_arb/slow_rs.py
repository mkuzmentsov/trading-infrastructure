"""Per-print realized spread: the adverse-selection cost of a maker fill,
measured on EVERY taker print (not a sim). Answers whether slow-bar flow is
less informed per fill than 5m flow -- the only thing that could rescue a
two-sided farm on the hourly series.

For a SELL print at px (it filled resting BIDS): maker edge at horizon tau
  = mid(t+tau) - px             (positive = the bid was paid to provide)
For a BUY print at px (it lifted resting ASKS): maker edge
  = px - mid(t+tau)
'res' horizon = terminal value (win ? 1 : 0).

Share-weighted within bar, then t-stat ACROSS bars (prints cluster hard).
Rebate/share at px = 0.2*0.07*px*(1-px) printed alongside.
"""
import bisect, math, sys
import fast

REB = lambda p: 0.2 * 0.07 * p * (1 - p)


def prep(m):
    tls, umid, dmid = [], [], []
    for s in m["snaps"]:                       # tl descending = chronological
        tl, ub, _, db, _, ua, _, da, _ = s
        um = (ub + ua) / 2 if (ub is not None and ua is not None) else None
        dm = (db + da) / 2 if (db is not None and da is not None) else None
        tls.append(-tl)                        # ascending key for bisect
        umid.append(um); dmid.append(dm)
    return tls, umid, dmid


def mid_at(tls, mids, tl_target):
    i = bisect.bisect_left(tls, -tl_target)
    for j in range(i, min(i + 30, len(tls))):
        if mids[j] is not None:
            return mids[j]
    return None


def study(name, bar_secs, taus, band=(0.40, 0.60)):
    per_bar = {}                               # (side, tau) -> {ws: [wsum, sh]}
    for ws, m in fast.load(name).items():
        tls, umid, dmid = prep(m)
        win = m["win"]
        for tl, tok, px, sz, tside in m["sells"]:
            if not (0 < tl <= bar_secs) or not (band[0] <= px <= band[1]):
                continue
            mids = umid if tok == "U" else dmid
            for tau in taus:
                if tau == "res":
                    term = 1.0 if (tok == "U") == (win == "UP") else 0.0
                    edge = (term - px) if tside == "SELL" else (px - term)
                else:
                    if tl - tau < 0:
                        continue
                    mnow = mid_at(tls, mids, tl - tau)
                    if mnow is None:
                        continue
                    edge = (mnow - px) if tside == "SELL" else (px - mnow)
                key = ("BID" if tside == "SELL" else "ASK", tau)
                d = per_bar.setdefault(key, {}).setdefault(ws, [0.0, 0.0])
                d[0] += edge * sz; d[1] += sz
    print(f"\n=== {name}: maker realized edge, fills at {band[0]}-{band[1]} "
          f"(rebate there ~{100*REB(0.5):.2f}c/sh) ===")
    print(f"{'side':4s} {'tau':>6s} {'bars':>5s} {'shares':>9s} {'edge c/sh':>10s} "
          f"{'t':>6s}   (edge+rebate)")
    for side in ("BID", "ASK"):
        for tau in taus:
            d = per_bar.get((side, tau))
            if not d:
                continue
            means = [w / s for w, s in d.values() if s > 0]
            sh = sum(s for _, s in d.values())
            wsum = sum(w for w, _ in d.values())
            mu_sh = wsum / sh                       # share-weighted pooled
            n = len(means)
            mu = sum(means) / n
            sd = math.sqrt(sum((x - mu) ** 2 for x in means) / (n - 1)) if n > 1 else 0.0
            t = mu / (sd / math.sqrt(n)) if sd else 0.0
            lab = f"{tau}s" if tau != "res" else "res"
            print(f"{side:4s} {lab:>6s} {n:5d} {sh:9,.0f} {100*mu_sh:+10.3f} "
                  f"{t:+6.2f}   ({100*(mu_sh+REB(0.5)):+.3f})")


if __name__ == "__main__":
    study("btc-mrec1h", 3600, [10, 30, 120, 600, "res"])
    study("btc", 300, [10, 30, 120, "res"])
    # wide band for context
    study("btc-mrec1h", 3600, [30, "res"], band=(0.10, 0.90))
    study("btc", 300, [30, "res"], band=(0.10, 0.90))
