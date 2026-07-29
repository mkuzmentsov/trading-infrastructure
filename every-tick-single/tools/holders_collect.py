"""Continuously record top holders of every live 5m up/down bar.

Appends one JSON line per (coin, bar, poll) to data/holders/holders-<date>.jsonl
(data/ is gitignored). Polls every POLL_SECS so we capture how each wallet's
position BUILDS across the bar, not just its end state — that is what tells us
whether a wallet rests through the bar or piles in near the close.

Why this exists: the one-shot 315-bar sample used for the leaderboard study was
too small to separate skill from dispersion (295 wallets, best t=2.87 vs 2.8
expected by chance). Accumulating continuously gives the per-day consistency
test real power.

Run:  nohup python3 every-tick-single/tools/holders_collect.py &
"""
import json, os, time, urllib.request, urllib.parse

COINS = ["btc", "eth", "sol", "doge", "bnb", "xrp"]
POLL_SECS = int(os.getenv("HOLDERS_POLL_SECS", "60"))
LIMIT = int(os.getenv("HOLDERS_LIMIT", "100"))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT_DIR = os.path.join(ROOT, "data", "holders")
UA = {"User-Agent": "curl/8.4.0"}
os.makedirs(OUT_DIR, exist_ok=True)

_cid_cache: dict = {}          # slug -> conditionId (bars are immutable)


def _get(url, timeout=20):
    return json.load(urllib.request.urlopen(
        urllib.request.Request(url, headers=UA), timeout=timeout))


def condition_id(slug):
    if slug in _cid_cache:
        return _cid_cache[slug]
    try:
        ev = _get(f"https://gamma-api.polymarket.com/events?slug={slug}")
        cid = ev[0]["markets"][0]["conditionId"]
    except Exception:
        return None
    if len(_cid_cache) > 4000:
        _cid_cache.clear()
    _cid_cache[slug] = cid
    return cid


def holders(cid):
    try:
        return _get("https://data-api.polymarket.com/holders?"
                    + urllib.parse.urlencode({"market": cid, "limit": LIMIT}))
    except Exception:
        return None


def main():
    log = lambda m: print(f"{time.strftime('%H:%M:%S')} {m}", flush=True)
    log(f"holders collector: {len(COINS)} coins, every {POLL_SECS}s -> {OUT_DIR}")
    while True:
        cycle = time.time()
        ws = int(cycle // 300) * 300          # bar currently open
        path = os.path.join(OUT_DIR, f"holders-{time.strftime('%Y%m%d')}.jsonl")
        wrote = 0
        with open(path, "a") as f:
            for coin in COINS:
                # the open bar, and the one that just closed (holders settle there)
                for bar in (ws, ws - 300):
                    slug = f"{coin}-updown-5m-{bar}"
                    cid = condition_id(slug)
                    if not cid:
                        continue
                    data = holders(cid)
                    if not data:
                        continue
                    rows = []
                    for tok in data:
                        for h in tok.get("holders", []):
                            rows.append([h.get("proxyWallet"),
                                         h.get("name") or h.get("pseudonym") or "",
                                         round(float(h.get("amount") or 0), 2),
                                         h.get("outcomeIndex")])
                    if not rows:
                        continue
                    f.write(json.dumps({"t": round(cycle, 1), "coin": coin,
                                        "ws": bar, "cid": cid,
                                        "n": len(rows), "h": rows}) + "\n")
                    wrote += 1
        if int(cycle) % 600 < POLL_SECS:       # heartbeat every ~10 min
            try:
                sz = os.path.getsize(path) / 1e6
            except OSError:
                sz = 0
            log(f"wrote {wrote} snapshots; {os.path.basename(path)} = {sz:.1f}MB")
        time.sleep(max(5, POLL_SECS - (time.time() - cycle)))


if __name__ == "__main__":
    main()
