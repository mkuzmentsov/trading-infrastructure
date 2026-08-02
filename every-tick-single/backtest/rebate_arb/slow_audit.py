"""Fill-integrity audits for the dual-ask result.

1. Mirror-print audit: does the feed print one match on BOTH token feeds
   (U SELL @p  <->  D BUY @1-p, same size, same instant)? If yes, both-fill
   rates are inflated by construction. (Prior evidence against: flow is 89%
   BUY -- systematic mirroring would force ~50/50.)
2. volsh cross-check: sum of print sizes vs the market's cumulative volsh
   field from the raw archives (cache drops volsh, so re-read raw).
3. Concentration: per-bar net distribution + per-day split for 1h 0.55 hid=200
   and 5m btc 0.55 hid=200 -- is the total a few monster bars?
4. Per-coin 5m table at 0.55 hid=200 (the Simpson split).
5. Pre-open entry variant for hourly (asks resting before the open burst).
"""
import glob, gzip, json, math, statistics as st
from collections import defaultdict

import fast, slow_deep

DATA = ("/Users/maxkuzmentsov/development/projects/my/hummingbot/hummingbot-infra/"
        "every-tick-single/data/mrec")


def mirror_audit(name, bar_secs):
    tot = mir = 0
    for ws, m in fast.load(name).items():
        by_t = defaultdict(list)
        for tl, tok, px, sz, side in m["sells"]:
            if not (0 < tl <= bar_secs):
                continue
            by_t[round(tl, 1)].append((tok, px, sz, side))
        for tl, tok, px, sz, side in m["sells"]:
            if not (0 < tl <= bar_secs):
                continue
            tot += 1
            for dt in (0.0, 0.1, -0.1, 0.2, -0.2):
                hit = False
                for tok2, px2, sz2, side2 in by_t.get(round(tl + dt, 1), []):
                    if (tok2 != tok and abs((px + px2) - 1.0) < 0.015
                            and abs(sz2 - sz) < max(1.0, 0.05 * sz) and side2 != side):
                        hit = True; break
                if hit:
                    mir += 1; break
    print(f"{name}: {tot} prints, mirror-coincident {mir} ({100*mir/max(tot,1):.1f}%)")


def volsh_check(name, n_files=6):
    last = {}          # slug -> (volsh, printed)
    printed = defaultdict(float)
    for f in sorted(glob.glob(f"{DATA}/{name}/*.gz"))[:n_files]:
        with gzip.open(f, "rt") as fh:
            for line in fh:
                try: r = json.loads(line)
                except Exception: continue
                if r.get("ev") != "SNAP" or r.get("role") not in ("cur", "post"):
                    continue
                s = r["slug"]
                if r.get("volsh"):
                    last[s] = r["volsh"]
                for t in (r.get("trd") or []):
                    if len(t) >= 5:
                        printed[s] += t[3]
    print(f"\n{name} volsh cross-check (first {n_files} files; partial-life markets skipped):")
    for s, v in sorted(last.items()):
        p = printed.get(s, 0.0)
        if v and v > 1000 and p > 0:
            print(f"  {s}: volsh={v:,.0f} printed={p:,.0f} ratio={p/v:.2f}")


def concentration(rows, label):
    nets = sorted((r["net"] for r in rows), reverse=True)
    tot = sum(nets)
    top3 = sum(nets[:3])
    pos = sum(1 for x in nets if x > 0)
    print(f"{label}: total=${tot:+.2f} med=${st.median(nets):+.2f} "
          f"top3=${top3:+.2f} ({100*top3/tot if tot else 0:.0f}% of total) "
          f"pos_bars={pos}/{len(nets)} best=${nets[0]:+.2f} worst=${nets[-1]:+.2f}")


def by_day(rows, label):
    d = defaultdict(list)
    for r in rows:
        d[__import__("datetime").datetime.utcfromtimestamp(r["ws"]).strftime("%m-%d")].append(r["net"])
    parts = "  ".join(f"{k}: ${sum(v):+.2f}/{len(v)}b" for k, v in sorted(d.items()))
    print(f"{label} by day: {parts}")


if __name__ == "__main__":
    print("== 1. mirror-print audit ==")
    mirror_audit("btc-mrec1h", 3600)
    mirror_audit("btc", 300)

    print("\n== 2. volsh cross-check ==")
    volsh_check("btc-mrec1h")

    print("\n== 3. concentration / stability ==")
    h = slow_deep.run(["btc-mrec1h"], 0.55, 0.55, tl_hi=3600.0, hidden=200)
    concentration(h, "1h 0.55 hid=200")
    by_day(h, "1h 0.55 hid=200")
    b5 = slow_deep.run(["btc"], 0.55, 0.55, tl_hi=300.0, hidden=200)
    concentration(b5, "5m btc 0.55 hid=200")
    by_day(b5, "5m btc 0.55 hid=200")

    print("\n== 4. per-coin 5m at 0.55 hid=200 ==")
    for c in ("btc", "eth", "sol", "xrp", "bnb", "doge"):
        print(slow_deep.rep(slow_deep.run([c], 0.55, 0.55, tl_hi=300.0, hidden=200), f"5m {c}"))

    print("\n== 5. hourly pre-open entry (rest during next1) ==")
    for tl_hi in (5400.0, 7200.0):
        print(slow_deep.rep(slow_deep.run(["btc-mrec1h"], 0.55, 0.55, tl_hi=tl_hi, hidden=200),
                            f"1h 0.55 from tl={tl_hi:.0f}"))
    print("\n== 5m btc margin sweep hid=200 ==")
    for a in (0.58, 0.60, 0.65):
        print(slow_deep.rep(slow_deep.run(["btc"], a, a, tl_hi=300.0, hidden=200), f"5m btc {a}"))
