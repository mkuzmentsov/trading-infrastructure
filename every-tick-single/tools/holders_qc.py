"""Quality-control the holders collector: is it alive, complete, and sane?

Bad data that looks fine is worse than no data — last night's leaderboard work
was nearly derailed by a silent API pagination cap. This checks the things that
would quietly corrupt tonight's analysis:

  liveness   process up, file growing
  coverage   every coin, every 300s bar, no gaps
  depth      polls per bar (we want the position BUILD, not one snapshot)
  sanity     holder counts, amounts, duplicate/blank wallets
  freshness  lag between now and the newest record
"""
import collections, glob, json, os, subprocess, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT_DIR = os.path.join(ROOT, "data", "holders")
COINS = ["btc", "eth", "sol", "doge", "bnb", "xrp"]
WINDOW = int(sys.argv[1]) if len(sys.argv) > 1 else 3600     # analyse last N sec


def main():
    alive = subprocess.run(["pgrep", "-f", "holders_collect.py"],
                           capture_output=True, text=True).stdout.strip()
    files = sorted(glob.glob(f"{OUT_DIR}/holders-*.jsonl"))
    if not files:
        print("NO DATA FILES — collector never wrote")
        return 1
    path = files[-1]
    size = os.path.getsize(path) / 1e6
    now = time.time()

    rows = []
    bad_json = 0
    with open(path) as f:
        for line in f:
            try:
                e = json.loads(line)
            except Exception:
                bad_json += 1
                continue
            rows.append(e)
    recent = [e for e in rows if now - e.get("t", 0) <= WINDOW]

    print(f"LIVENESS   process={'UP pid ' + alive.split()[0] if alive else 'DOWN'}"
          f"  file={os.path.basename(path)} {size:.1f}MB  lines={len(rows)}"
          f"  bad_json={bad_json}")
    if not rows:
        print("  no parsable rows")
        return 1
    newest = max(e["t"] for e in rows)
    print(f"FRESHNESS  newest record {now - newest:.0f}s ago"
          f"   {'OK' if now - newest < 180 else 'STALE >3min'}")
    span = (newest - min(e["t"] for e in rows)) / 60
    print(f"SPAN       {span:.1f} min of data, {len(recent)} rows in last "
          f"{WINDOW//60}min ({len(recent)/max(WINDOW/60,1):.1f}/min)")

    # coverage: per coin, which bars did we capture and how deeply
    per_coin = collections.defaultdict(set)
    polls = collections.Counter()
    depth = collections.defaultdict(list)
    blanks = dupes = zero_amt = 0
    for e in recent:
        per_coin[e["coin"]].add(e["ws"])
        polls[(e["coin"], e["ws"])] += 1
        depth[e["coin"]].append(e.get("n", 0))
        seen = set()
        for h in e.get("h", []):
            w = h[0]
            if not w:
                blanks += 1
            elif w in seen:
                dupes += 1
            else:
                seen.add(w)
            if not h[2]:
                zero_amt += 1

    print(f"{'COVERAGE':10s} {'coin':6s} {'bars':>5s} {'gaps':>5s} "
          f"{'polls/bar':>10s} {'holders/snap':>13s}")
    problems = []
    for c in COINS:
        bars = sorted(per_coin.get(c, []))
        if not bars:
            print(f"{'':10s} {c:6s}     0     -          -             -   MISSING")
            problems.append(f"{c}: no data")
            continue
        expected = (bars[-1] - bars[0]) // 300 + 1
        gaps = expected - len(bars)
        pb = [polls[(c, b)] for b in bars]
        med_poll = sorted(pb)[len(pb) // 2]
        d = depth[c]
        med_depth = sorted(d)[len(d) // 2] if d else 0
        flag = ""
        if gaps > 0:
            flag = f"  {gaps} MISSING BARS"
            problems.append(f"{c}: {gaps} gaps")
        if med_poll < 3:
            flag += "  THIN"
            problems.append(f"{c}: only {med_poll} polls/bar")
        print(f"{'':10s} {c:6s} {len(bars):5d} {gaps:5d} {med_poll:10d} "
              f"{med_depth:13d}{flag}")

    wallets = {h[0] for e in recent for h in e.get("h", [])}
    print(f"SANITY     unique wallets {len(wallets)}  blank {blanks}  "
          f"dup-in-snapshot {dupes}  zero-amount {zero_amt}")
    if not alive:
        problems.append("PROCESS DOWN")
    if now - newest > 180:
        problems.append("stale >3min")
    print("VERDICT    " + ("OK — data is usable"
                           if not problems else "ISSUES: " + "; ".join(problems)))
    return 0 if not problems else 2


if __name__ == "__main__":
    sys.exit(main())
