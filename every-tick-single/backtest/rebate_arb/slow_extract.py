"""Compaction for the SLOW recorders (btc-mrec1h / btc-mrec1d) -> same cache
shape as extract.py so fast.py/seqmaker.py load them unchanged.

One difference from the 5m path: these archives contain NO RES rows -- hourly
and daily markets carry customLiveness=600, so gamma flips closed=true right
when multi_recorder's 600s post-close give-up drops the market. Winners are
fetched from gamma here instead (all recorded bars are closed by now) and
cached in cache/<name>-winners.json."""
import glob, gzip, json, os, pickle, sys, time, urllib.request
from collections import defaultdict

DATA = ("/Users/maxkuzmentsov/development/projects/my/hummingbot/hummingbot-infra/"
        "every-tick-single/data/mrec")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")


def fetch_winner(slug):
    url = f"https://gamma-api.polymarket.com/markets?slug={slug}&closed=true"
    try:
        d = json.loads(urllib.request.urlopen(
            urllib.request.Request(url, headers={"User-Agent": "mrec"}),
            timeout=10).read())
        if d and d[0].get("closed"):
            op = d[0]["outcomePrices"]
            op = json.loads(op) if isinstance(op, str) else op
            return "UP" if str(op[0]) in ("1", "1.0") else "DOWN"
    except Exception as e:
        print(f"  gamma {slug}: {e}")
    return None


def build(name):
    snaps = defaultdict(list)
    seen_sec = {}
    sells = defaultdict(list)
    slugs = {}
    for f in sorted(glob.glob(f"{DATA}/{name}/*.gz")):
        with gzip.open(f, "rt") as fh:
            for line in fh:
                try: r = json.loads(line)
                except Exception: continue
                if r.get("ev") != "SNAP": continue
                ws = r["ws"]; tl = r.get("tl")
                if tl is None: continue
                slugs.setdefault(ws, r.get("slug"))
                sec = int(tl)
                if seen_sec.get(ws) != sec:
                    seen_sec[ws] = sec
                    snaps[ws].append((tl, r.get("ub"), r.get("ubs") or 0.0,
                                      r.get("db"), r.get("dbs") or 0.0,
                                      r.get("ua"), r.get("uas") or 0.0,
                                      r.get("da"), r.get("das") or 0.0))
                for t in (r.get("trd") or []):
                    if len(t) >= 5:
                        sells[ws].append((tl, t[1], t[2], t[3], t[4]))

    wfile = f"{OUT}/{name}-winners.json"
    winners = json.load(open(wfile)) if os.path.exists(wfile) else {}
    for ws, slug in sorted(slugs.items()):
        k = str(ws)
        if k in winners: continue
        w = fetch_winner(slug)
        if w: winners[k] = w
        time.sleep(0.3)
    os.makedirs(OUT, exist_ok=True)
    json.dump(winners, open(wfile, "w"), indent=1)

    mkts = {}
    unresolved = []
    for ws in snaps:
        w = winners.get(str(ws))
        if not w:
            unresolved.append(slugs[ws]); continue
        s = sorted(snaps[ws], key=lambda x: -x[0])
        mkts[ws] = dict(win=w, slug=slugs[ws], snaps=s,
                        sells=sorted(sells.get(ws, []), key=lambda x: -x[0]))
    with open(f"{OUT}/{name}.pkl", "wb") as fh:
        pickle.dump(mkts, fh, protocol=4)
    print(f"{name}: {len(mkts)} resolved markets, "
          f"{sum(len(m['snaps']) for m in mkts.values())} snaps, "
          f"{sum(len(m['sells']) for m in mkts.values())} prints; "
          f"unresolved skipped: {unresolved}")


if __name__ == "__main__":
    for n in (sys.argv[1:] or ["btc-mrec1h", "btc-mrec1d"]):
        build(n)
