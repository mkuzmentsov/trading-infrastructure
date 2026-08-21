#!/usr/bin/env python3
"""swing.py — how much can the TWAP-60 settlement estimate still MOVE after we
enter? (the §26b open question: "is eth's late-window vol structurally lower,
or was 19W/0L luck? Measure per-coin late-window swing from the recorders")

For every 5m bar in the mrec archives:
  window   = [T-62, T-3]                      (the TWAP-60 settlement window)
  est(tl)  = mean(lead_bps) over [T-62, T-tl]  (what the bot can know at T-tl,
                                                same math as twapedge._estimate)
  final    = mean(lead_bps) over the whole window (the settlement lead)
  swing(tl)= final - est(tl)                  (what is still unwritten)

A bar flips iff the remaining window is big enough AND opposite: |swing| >
|est| with the sign against us. So the decision rule falls straight out:
  "at entry time tl, |est| must exceed the p99 swing of that coin at tl".

lead_bps here is Binance spot vs the bar open (what the recorder stores);
settlement is Chainlink, and the two diverge only on ~0bps ties
([[binance-chainlink-divergence]]). That makes the SWING MAGNITUDE (a
volatility measure) sound, while any single near-tie bar's sign is not.

Usage: python3 tools/swing.py [coin ...]
"""
import collections, glob, gzip, json, math, os, statistics, sys
from multiprocessing import Pool

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "every-tick-single/data/mrec")
COINS = ["btc", "eth", "sol", "xrp", "doge", "bnb", "hype"]
W_LO, W_HI = 62, 3          # TWAP-60 window edges, seconds before close
TLS = [30, 28, 25, 20, 14, 10, 5]


def scan(path):
    """-> {slug: [(tl, lead_bps), ...]} for samples inside the TWAP window."""
    out = collections.defaultdict(list)
    for line in gzip.open(path, "rt"):
        if '"role":"cur"' not in line:
            continue
        r = json.loads(line)
        tl = r.get("tl")
        lb = r.get("lead_bps")
        if tl is None or lb is None or not (W_HI <= tl <= W_LO):
            continue
        out[r["slug"]].append((tl, lb))
    return dict(out)


def bars_for(coin, procs=8):
    files = sorted(glob.glob(f"{ROOT}/{coin}/*.gz"))
    acc = collections.defaultdict(list)
    with Pool(procs) as p:
        for part in p.map(scan, files):
            for slug, v in part.items():
                acc[slug] += v
    rows = []
    for slug, v in acc.items():
        v.sort(key=lambda x: -x[0])                 # T-62 ... T-3
        if len(v) < 400:                            # need a near-complete window
            continue
        final = statistics.fmean(lb for _, lb in v)
        rec = dict(coin=coin, slug=slug, final=final, n=len(v))
        ok = True
        for tl in TLS:
            seen = [lb for t, lb in v if t >= tl]
            if len(seen) < 20:
                ok = False
                break
            est = statistics.fmean(seen)
            rec[f"est{tl}"] = est
            rec[f"swing{tl}"] = final - est
        if ok:
            rows.append(rec)
    return rows


def pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))]


def main(coins):
    allrows = []
    for c in coins:
        rows = bars_for(c)
        allrows += rows
        print(f"{c}: {len(rows)} bars with a complete TWAP window", flush=True)

    print("\n=== |SWING| STILL TO COME, in bps (how wrong the estimate can be) ===")
    print(f"{'coin':>6} " + " ".join(f"{'T-'+str(t):>17}" for t in TLS))
    print(f"{'':>6} " + " ".join(f"{'med / p90 / p99':>17}" for t in TLS))
    for c in coins:
        v = [r for r in allrows if r["coin"] == c]
        if not v:
            continue
        cells = []
        for tl in TLS:
            s = [abs(r[f"swing{tl}"]) for r in v]
            cells.append(f"{statistics.median(s):.2f}/{pct(s,.90):.2f}/{pct(s,.99):.2f}".rjust(17))
        print(f"{c:>6} " + " ".join(cells))

    print("\n=== P(FLIP) = P(swing reverses the estimate's sign), by |est| at entry ===")
    print("    the cell is: flips / bars  (rate)")
    for tl in (30, 28, 25, 20, 14, 10):
        print(f"\n  -- entry at T-{tl}s --")
        print(f"{'coin':>6} " + " ".join(f"{lbl:>16}" for lbl in
              ["|est|<0.5", "0.5-1.0", "1.0-1.5", "1.5-2.5", "2.5+"]))
        for c in coins + ["ALL"]:
            v = [r for r in allrows if c == "ALL" or r["coin"] == c]
            cells = []
            for lo, hi in [(0, .5), (.5, 1.), (1., 1.5), (1.5, 2.5), (2.5, 1e9)]:
                sel = [r for r in v if lo <= abs(r[f"est{tl}"]) < hi]
                if not sel:
                    cells.append(f"{'-':>16}")
                    continue
                f = sum(1 for r in sel
                        if (r[f"est{tl}"] > 0) != (r["final"] > 0))
                cells.append(f"{f}/{len(sel)} ({100*f/len(sel):.2f}%)".rjust(16))
            print(f"{c:>6} " + " ".join(cells))

    # The gate must be judged on the MARGINAL bars it lets in (est just above
    # the threshold), not on the average of everything above it — the huge
    # >=2.5bps mass otherwise drags any pooled rate under 1%.
    print("\n=== THE GATE: smallest |est| whose MARGINAL bars (est in "
          "[thr, thr+0.5]) flip <=1% ===")
    print(f"{'coin':>6} " + " ".join(f"{'T-'+str(t):>8}" for t in TLS))
    for c in coins + ["ALL"]:
        v = [r for r in allrows if c == "ALL" or r["coin"] == c]
        if not v:
            continue
        cells = []
        for tl in TLS:
            need = None
            for thr in [x / 10 for x in range(1, 61)]:
                sel = [r for r in v if thr <= abs(r[f"est{tl}"]) < thr + 0.5]
                if len(sel) < 40:
                    continue
                f = sum(1 for r in sel if (r[f"est{tl}"] > 0) != (r["final"] > 0))
                if f / len(sel) <= 0.01:
                    need = thr
                    break
            cells.append((f"{need:.1f}bps" if need else "n/a").rjust(8))
        print(f"{c:>6} " + " ".join(cells))
    print("  mnemonic: the gate tracks the p99 swing -> |est| >= ~tl/10 bps")

    with open("swing_rows.jsonl", "w") as fh:
        for r in allrows:
            fh.write(json.dumps(r) + "\n")
    print(f"\nwrote swing_rows.jsonl ({len(allrows)} bars)")


if __name__ == "__main__":
    main(sys.argv[1:] or COINS)
