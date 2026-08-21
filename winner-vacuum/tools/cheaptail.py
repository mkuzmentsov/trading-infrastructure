#!/usr/bin/env python3
"""cheaptail.py — is the OPPOSING side worth buying at ~1c near close?

Question (user, 2026-08-17): vacmaker buys the TWAP-implied winner at T−14s.
Some of those bars mean-revert. Can we ALSO buy the other side for 1c
(e.g. 100 shares = $1) as a lottery on the reversal?

Method — ground truth only, no proxy signal:
  mrec 100ms recorder archives (every-tick-single/data/mrec/<coin>/*.gz) carry
  SNAP rows (role=cur, tl=seconds-to-close, best bid/ask+size per side) and a
  RES row per bar with the real winner. For each bar take the cur-SNAP nearest
  each target tl, call the side with the LOWER bid the "cheap" side, and price
  a taker buy of it:
        EV/share = P(cheap wins) − ask − 0.07·ask·(1−ask)
  (0.07·p(1−p) = crypto_fees_v2 taker fee, see engine/paper_book.py.)

Usage:  python3 tools/cheaptail.py [coin ...]        # default 6 coins
        python3 tools/cheaptail.py --rows out.jsonl  # reuse a previous scan

Verdict 2026-08-17 (15.7k bar-obs, 6 coins, 07-30→08-11): ⛔ DEAD. The 1c ask
wins 0.18% vs a 1.07% breakeven — 5.3× overpriced, hi95 0.32% excludes +EV.
Every price band and every tl is −27%…−100% of premium. See
docs/vacmaker-offline-notes.md §27.
"""
import collections, glob, gzip, json, math, os, sys
from multiprocessing import Pool

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "every-tick-single/data/mrec")
COINS = ["btc", "eth", "sol", "xrp", "doge", "bnb"]
TARGETS = [30, 20, 14, 10, 5]
TOL = 2.5          # accept a snap within ±2.5s of the target tl
FEE = 0.07         # crypto_fees_v2: shares × 0.07 × p × (1−p)


# ---------------------------------------------------------------- scan
def scan(path):
    """One archive file -> ({slug: {tl_target: snap}}, {slug: winner})."""
    res, best = {}, collections.defaultdict(dict)
    for line in gzip.open(path, "rt"):
        if '"ev":"RES"' in line:
            r = json.loads(line)
            res[r["slug"]] = r["win"]
            continue
        if '"role":"cur"' not in line:      # skip next1..3 / post rows fast
            continue
        r = json.loads(line)
        tl = r.get("tl")
        if tl is None or tl < 2 or tl > 33:
            continue
        for tgt in TARGETS:
            d = abs(tl - tgt)
            if d <= TOL:
                cur = best[r["slug"]].get(tgt)
                if cur is None or d < cur[0]:
                    best[r["slug"]][tgt] = (d, r)
    return {s: {t: v[1] for t, v in m.items()} for s, m in best.items()}, res


def rows_for(coin, procs=8):
    files = sorted(glob.glob(f"{ROOT}/{coin}/*.gz"))
    bars, res = collections.defaultdict(dict), {}
    with Pool(procs) as p:
        for b, r in p.map(scan, files):
            for slug, m in b.items():
                bars[slug].update(m)
            res.update(r)
    out = []
    for slug, m in bars.items():
        win = res.get(slug)
        if win not in ("UP", "DOWN"):
            continue
        for tgt, r in m.items():
            ub, ua, db, da = r.get("ub"), r.get("ua"), r.get("db"), r.get("da")
            if ub is None and db is None:
                continue
            up_px = ub if ub is not None else (ua or 0) - 0.01
            dn_px = db if db is not None else (da or 0) - 0.01
            if up_px == dn_px:
                continue                    # no favourite -> undefined
            cheap_up = up_px < dn_px
            out.append(dict(
                coin=coin, slug=slug, tl=tgt, t=r["t"],
                cheap_ask=(ua if cheap_up else da),
                cheap_sz=(r.get("uas") if cheap_up else r.get("das")) or 0.0,
                fav_ask=(da if cheap_up else ua),
                fav_bid=(dn_px if cheap_up else up_px),
                cheap_won=((win == "UP") == cheap_up), spot=r.get("spot")))
    return out


# ------------------------------------------------------------- reporting
def wilson_hi(w, n, z=1.96):
    if n == 0:
        return float("nan")
    p, d = w / n, 1 + z * z / n
    return (p + z * z / (2 * n)) / d + z * math.sqrt(
        p * (1 - p) / n + z * z / (4 * n * n)) / d


def breakeven(px):
    return px + FEE * px * (1 - px)


def tab(sel, label, keyf, order=None):
    print(f"\n=== {label}  (obs={len(sel)}) ===")
    print(f"{'bucket':>14} {'n':>6} {'wins':>5} {'win%':>7} {'breakeven%':>11} "
          f"{'win%_hi95':>10} {'EV/sh':>9} {'EV%prem':>8} {'med sz':>8}")
    g = collections.defaultdict(list)
    for r in sel:
        g[keyf(r)].append(r)
    for k in (order or sorted(g)):
        v = g.get(k)
        if not v:
            continue
        n = len(v)
        w = sum(1 for r in v if r["cheap_won"])
        ev = sum((1.0 if r["cheap_won"] else 0.0) - breakeven(r["cheap_ask"])
                 for r in v) / n
        be = sum(breakeven(r["cheap_ask"]) for r in v) / n
        szs = sorted(r["cheap_sz"] for r in v)
        print(f"{str(k):>14} {n:>6} {w:>5} {100*w/n:>6.2f}% {100*be:>10.2f}% "
              f"{100*wilson_hi(w,n):>9.2f}% {ev:>+9.4f} {100*ev/be:>+7.0f}% "
              f"{szs[n//2]:>8.0f}")


def px_bucket(r):
    a = r["cheap_ask"]
    for hi, name in ((0.0015, "0.001"), (0.010, "0.002-0.009"),
                     (0.015, "0.010"), (0.025, "0.020"), (0.035, "0.030"),
                     (0.055, "0.04-0.05"), (0.105, "0.06-0.10")):
        if a < hi:
            return name
    return ">0.10"


PX_ORDER = ["0.001", "0.002-0.009", "0.010", "0.020", "0.030", "0.04-0.05",
            "0.06-0.10", ">0.10"]


def report(rows):
    have = [r for r in rows if r["cheap_ask"] is not None]
    for tl in TARGETS:
        tab([r for r in have if r["tl"] == tl],
            f"pooled all coins, tl~{tl}s", px_bucket, PX_ORDER)

    s14 = [r for r in have if r["tl"] == 14]
    tab([r for r in s14 if r["fav_ask"] is not None and r["fav_ask"] <= 0.99],
        "tl~14, bars where fav ask<=0.99 (vacmaker's own trade bars)",
        px_bucket, PX_ORDER)
    tab([r for r in s14 if r["cheap_ask"] <= 0.011],
        "tl~14, cheap ask<=0.011, BY COIN", lambda r: r["coin"])
    tab([r for r in have if r["tl"] == 5 and r["cheap_ask"] <= 0.011],
        "tl~5, cheap ask<=0.011, BY COIN", lambda r: r["coin"])

    print("\n=== overall reversal rate (book favourite by bid loses) ===")
    for tl in TARGETS:
        v = [r for r in rows if r["tl"] == tl]
        print(f"  tl~{tl:>2}s  n={len(v):>6}  "
              f"reversal={100*sum(1 for r in v if r['cheap_won'])/len(v):.2f}%")

    by = collections.defaultdict(dict)
    for r in rows:
        by[(r["coin"], r["slug"])][r["tl"]] = r

    sums = sorted(r["cheap_ask"] + r["fav_ask"] for r in s14
                  if r["fav_ask"] is not None)
    n = len(sums)
    print(f"\npair sum (fav ask + loser ask) at tl~14: n={n} "
          f"p5={sums[n//20]:.3f} median={sums[n//2]:.3f} "
          f"frac<1.00={100*sum(1 for s in sums if s < 1.0)/n:.1f}%   "
          "<- a 'buy winner + buy loser' hedge is a guaranteed loss")

    print("\n=== STEELMAN: late-decided bars (loser expensive at tl30, 1c at tl14) ===")
    for thr in (0.03, 0.05, 0.10, 0.20, 0.30):
        sel = [m for m in by.values() if m.get(30) and m.get(14)
               and m[30]["cheap_ask"] is not None
               and m[14]["cheap_ask"] is not None
               and m[30]["cheap_ask"] >= thr and m[14]["cheap_ask"] <= 0.011]
        if not sel:
            continue
        n = len(sel)
        w = sum(1 for m in sel if m[14]["cheap_won"])
        be = sum(breakeven(m[14]["cheap_ask"]) for m in sel) / n
        print(f"  loser>={thr:.2f} @tl30 -> n={n:>4} reversals={w:>2} "
              f"({100*w/n:.2f}%) breakeven={100*be:.2f}% "
              f"hi95={100*wilson_hi(w,n):.2f}%")

    cell = [r for r in s14 if 0.005 < r["cheap_ask"] < 0.015]
    n = len(cell)
    p = sum(1 for r in cell if r["cheap_won"]) / n
    print(f"\ntl~14 1c cell: win={100*p:.3f}% -> fair px ~{p:.4f} "
          f"({p*1000:.1f} tenths of a cent); you pay 0.010 = "
          f"{0.010/max(p,1e-9):.1f}x fair")


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "--rows":
        rows = [json.loads(l) for l in open(args[1])]
    else:
        rows = []
        for c in (args or COINS):
            rc = rows_for(c)
            rows += rc
            print(f"{c}: {len(rc)} obs, "
                  f"{len(set(r['slug'] for r in rc))} bars", flush=True)
        with open("cheaptail_rows.jsonl", "w") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
    report(rows)
