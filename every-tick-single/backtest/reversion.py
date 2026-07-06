#!/usr/bin/env python3
"""TA/momentum — does lag 1/2/3 bar direction+magnitude predict the next 5m bar?
Answer: YES (short-term mean reversion, monotonic in prior-move size) but the
market PRICES it (reversion side opens at ~ask = the reversion probability).

Two parts:
  raw_stats(binance_dir)      — autocorrelation + magnitude conditioning on 62d klines
  entry_economics(paper,bin)  — on OUR paper bars: reversion win rate + the price we'd
                                actually pay (maker@0.48 vs taker@open-ask)
Usage: python3 reversion.py <binance_dir> [paper_root]
"""
import json, os, sys, statistics


def raw_stats(bdir):
    coins = ("btc", "eth", "sol", "xrp")
    by_thresh = {}
    for c in coins:
        rows = json.load(open(os.path.join(bdir, f"{c}_5m.json")))
        d = [1 if r[4] >= r[1] else 0 for r in rows]
        ret = [(r[4]/r[1]-1)*1e4 if r[1] > 0 else 0 for r in rows]
        for i in range(1, len(rows)):
            m = abs(ret[i-1]); cont = 1 if d[i] == d[i-1] else 0
            for th in (0, 5, 15, 30):
                if m > th:
                    k = by_thresh.setdefault(th, [0, 0]); k[0] += cont; k[1] += 1
    return {th: {"p_continue": round(v[0]/v[1], 4), "n": v[1]} for th, v in by_thresh.items()}


def entry_economics(paper_root, bdir, dates, min_move=15):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import experiments as X
    kl = {c: {r[0]: (r[1], r[4]) for r in json.load(open(os.path.join(bdir, f"{c}_5m.json")))}
          for c in ("btc", "eth", "sol", "xrp")}
    def prior(c, ts):
        o = kl[c].get(ts-300); return (o[1]/o[0]-1)*1e4 if o and o[0] > 0 else None
    mk = [0, 0, 0.0]; tk = [0, 0, 0.0]; asks = []
    for d in dates:
        bars = X.load(os.path.join(paper_root, d))
        for (c, cid), b in bars.items():
            if b["outcome"] not in ("UP", "DOWN") or not b["bar_ts"] or not b["snaps"]:
                continue
            pr = prior(c, b["bar_ts"])
            if pr is None or abs(pr) <= min_move:
                continue
            rev = "DOWN" if pr > 0 else "UP"
            won = b["outcome"] == rev
            first = sorted(b["snaps"], key=lambda s: -s[0])[0]
            ask = first[2] if rev == "UP" else first[4]
            if any(p[1] == rev and 0 < p[2] <= 0.48 for p in b["prints"]):
                mk[0] += won; mk[1] += 1; mk[2] += (0.52 if won else -0.48)
            if 0 < ask < 1:
                asks.append(ask); fee = 0.07*ask*(1-ask)
                tk[0] += won; tk[1] += 1; tk[2] += ((1-ask-fee) if won else -ask-fee)
    return {"maker@0.48": {"q": round(mk[0]/mk[1], 3), "n": mk[1], "pnl_sh": round(mk[2]/mk[1], 4)} if mk[1] else None,
            "taker@openask": {"q": round(tk[0]/tk[1], 3), "n": tk[1], "pnl_sh": round(tk[2]/tk[1], 4)} if tk[1] else None,
            "avg_reversion_ask": round(statistics.mean(asks), 3) if asks else None}


def main():
    bdir = sys.argv[1]
    print("RAW mean-reversion (P continue by prior-bar magnitude, 62d):")
    for th, v in raw_stats(bdir).items():
        print(f"  |prior|>{th}bps: P(continue)={v['p_continue']} (n={v['n']})  <0.5 = reverts")
    if len(sys.argv) > 2:
        import glob
        dates = sorted(os.path.basename(d) for d in glob.glob(os.path.join(sys.argv[2], "2*")))
        print("\nEntry economics on paper bars (|prior|>15bps):")
        print(" ", json.dumps(entry_economics(sys.argv[2], bdir, dates), indent=0))


if __name__ == "__main__":
    main()
