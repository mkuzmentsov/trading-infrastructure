"""Parallel cache: per-market 1Hz (tl, lead_bps) series for role cur/post --
the spot's distance from the bar open, needed by the lead-gated 99c flip
study. Kept separate from the main cache so nothing downstream breaks."""
import glob, gzip, json, os, pickle, sys
from collections import defaultdict

BASES = {
    "btc": "data/raw/mrec/btc", "eth": "data/raw/mrec/eth",
    "sol": "data/raw/mrec/sol", "xrp": "data/raw/mrec/xrp",
    "bnb": "data/raw/mrec/bnb", "doge": "data/raw/mrec/doge",
    "btc-mrec1h": "data/mrec/btc-mrec1h", "btc-mrec1d": "data/mrec/btc-mrec1d",
}
ROOT = ("/Users/maxkuzmentsov/development/projects/my/hummingbot/hummingbot-infra/"
        "every-tick-single")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")


def build(name):
    leads = defaultdict(list)
    seen = {}
    for f in sorted(glob.glob(f"{ROOT}/{BASES[name]}/*.gz")):
        with gzip.open(f, "rt") as fh:
            for line in fh:
                try: r = json.loads(line)
                except Exception: continue
                if r.get("ev") != "SNAP" or r.get("role") not in ("cur", "post"):
                    continue
                tl = r.get("tl"); lb = r.get("lead_bps")
                if tl is None or lb is None: continue
                ws = r["ws"]; sec = int(tl)
                if seen.get(ws) != sec:
                    seen[ws] = sec
                    leads[ws].append((tl, lb))
    for ws in leads:
        leads[ws].sort(key=lambda x: -x[0])
    with open(f"{OUT}/{name}-leads.pkl", "wb") as fh:
        pickle.dump(dict(leads), fh, protocol=4)
    print(f"{name}: {len(leads)} markets, {sum(len(v) for v in leads.values())} lead-secs")


if __name__ == "__main__":
    for n in (sys.argv[1:] or ["btc", "eth", "sol", "xrp", "bnb", "doge", "btc-mrec1h"]):
        build(n)
