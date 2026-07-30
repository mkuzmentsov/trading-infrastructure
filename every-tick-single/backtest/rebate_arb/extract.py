"""One-time compaction: 710MB of gz snapshots -> per-coin pickle of just what
the fill model needs. Sweeps then run in seconds instead of minutes."""
import glob, gzip, json, os, pickle, sys
from collections import defaultdict

DATA = ("/Users/maxkuzmentsov/development/projects/my/hummingbot/hummingbot-infra/"
        "every-tick-single/data/raw/mrec")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")

def build(coin):
    snaps = defaultdict(list)      # ws -> [(tl, ub, ubs, db, dbs)] @1Hz
    seen_sec = {}
    sells = defaultdict(list)      # ws -> [(tl, tok, px, sz, side)]
    winners = {}
    for f in sorted(glob.glob(f"{DATA}/{coin}/*.gz")):
        with gzip.open(f, "rt") as fh:
            for line in fh:
                try: r = json.loads(line)
                except Exception: continue
                ev = r.get("ev")
                if ev == "RES":
                    winners[r["ws"]] = r.get("win"); continue
                if ev != "SNAP": continue
                ws = r["ws"]; tl = r.get("tl")
                if tl is None: continue
                # The book is only needed to size the queue AT THE MOMENT WE
                # JOIN, so 1/sec is plenty and keeps the cache ~10x smaller.
                # Every SELL print is still kept at full resolution below.
                sec = int(tl)
                if seen_sec.get(ws) != sec:
                    seen_sec[ws] = sec
                    snaps[ws].append((tl, r.get("ub"), r.get("ubs") or 0.0,
                                      r.get("db"), r.get("dbs") or 0.0,
                                      r.get("ua"), r.get("uas") or 0.0,
                                      r.get("da"), r.get("das") or 0.0))
                for t in (r.get("trd") or []):
                    if len(t) >= 5:
                        # keep BOTH taker sides: SELL prints fill our resting
                        # BIDS, BUY prints fill our resting ASKS (validated at
                        # 88%/87% against the previous top of book)
                        sells[ws].append((tl, t[1], t[2], t[3], t[4]))
    mkts = {}
    for ws in snaps:
        if ws not in winners: continue
        s = sorted(snaps[ws], key=lambda x: -x[0])
        mkts[ws] = dict(win=winners[ws], snaps=s,
                        sells=sorted(sells.get(ws, []), key=lambda x: -x[0]))
    os.makedirs(OUT, exist_ok=True)
    with open(f"{OUT}/{coin}.pkl", "wb") as fh:
        pickle.dump(mkts, fh, protocol=4)
    tl_all = [t for ws in mkts for t, *_ in mkts[ws]["snaps"]]
    print(f"{coin}: {len(mkts)} resolved markets, {len(tl_all)} snaps, "
          f"{sum(len(m['sells']) for m in mkts.values())} prints")

if __name__ == "__main__":
    for c in (sys.argv[1:] or ["btc","eth","sol","xrp","bnb","doge"]):
        build(c)
