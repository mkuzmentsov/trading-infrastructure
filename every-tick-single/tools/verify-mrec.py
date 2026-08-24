#!/usr/bin/env python3
"""verify-mrec.py — deep-verify a local mrec archive directory.

`tools/pull-mrec.sh` already checks size + md5 + `gzip -t` before deleting the
pod-side copy. It does NOT check that the CONTENT is usable. This does:
every line json.loads-ed, row/ev counts, bar coverage, and hour-continuity
(the gaps are what silently break a sim's "n bars" claim).

Run it before trusting an archive — and before deleting anything anywhere.

Usage:
  python3 tools/verify-mrec.py data/mrec/btc [data/mrec/eth ...]
  python3 tools/verify-mrec.py data/mrec/*        # all coins
Exit code 1 if any file fails.
"""
import collections, datetime as dt, glob, gzip, json, os, re, sys
from multiprocessing import Pool

HOUR = re.compile(r"-(\d{8})-(\d{2})\.jsonl\.gz$")


def check(path):
    rec = dict(path=path, name=os.path.basename(path), ok=False, err=None,
               size=0, rows=0, bad=0, snap=0, res=0, bar=0, t0=None, t1=None)
    try:
        rec["size"] = os.path.getsize(path)
        with gzip.open(path, "rt") as fh:
            for line in fh:
                rec["rows"] += 1
                try:
                    r = json.loads(line)
                except Exception:
                    rec["bad"] += 1
                    continue
                ev = r.get("ev")
                if ev == "SNAP":
                    rec["snap"] += 1
                elif ev == "RES":
                    rec["res"] += 1
                elif ev == "BAR":
                    rec["bar"] += 1
                t = r.get("t")
                if t:
                    rec["t0"] = t if rec["t0"] is None or t < rec["t0"] else rec["t0"]
                    rec["t1"] = t if rec["t1"] is None or t > rec["t1"] else rec["t1"]
        rec["err"] = (f"{rec['bad']} unparseable lines" if rec["bad"]
                      else ("empty" if not rec["rows"] else None))
        rec["ok"] = rec["err"] is None
    except Exception as e:
        rec["err"] = f"{type(e).__name__}: {e}"
    return rec


def hours(names):
    out = set()
    for n in names:
        m = HOUR.search(n)
        if m:
            out.add(dt.datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H")
                    .replace(tzinfo=dt.UTC))
    return out


def main(dirs):
    fmt = lambda x: (dt.datetime.fromtimestamp(x, dt.UTC).strftime("%m-%d %H:%M")
                     if x else "-")
    bad_total = 0
    print(f"{'dir':>16} {'files':>6} {'ok':>5} {'bad':>4} {'MB':>7} {'rows':>11} "
          f"{'SNAP':>11} {'RES':>6} {'BAR':>5}  window(UTC)")
    for d in dirs:
        files = sorted(glob.glob(f"{d.rstrip('/')}/*.jsonl.gz"))
        if not files:
            print(f"{os.path.basename(d.rstrip('/')):>16} (no .jsonl.gz)")
            continue
        with Pool(min(10, os.cpu_count() or 4)) as p:
            recs = p.map(check, files, chunksize=4)
        ok = sum(1 for r in recs if r["ok"])
        bad_total += len(recs) - ok
        t0 = min((r["t0"] for r in recs if r["t0"]), default=None)
        t1 = max((r["t1"] for r in recs if r["t1"]), default=None)
        print(f"{os.path.basename(d.rstrip('/')):>16} {len(recs):>6} {ok:>5} "
              f"{len(recs)-ok:>4} {sum(r['size'] for r in recs)/1e6:>7.1f} "
              f"{sum(r['rows'] for r in recs):>11,} "
              f"{sum(r['snap'] for r in recs):>11,} "
              f"{sum(r['res'] for r in recs):>6,} {sum(r['bar'] for r in recs):>5,}"
              f"  {fmt(t0)} -> {fmt(t1)}")
        hs = sorted(hours(r["name"] for r in recs))
        if hs:
            missing, cur = [], hs[0]
            have = set(hs)
            while cur < hs[-1]:
                if cur not in have:
                    missing.append(cur.strftime("%m-%d %H"))
                cur += dt.timedelta(hours=1)
            if missing:
                print(f"{'':>16} ⚠️  {len(missing)} MISSING HOURS: "
                      f"{', '.join(missing[:12])}{' …' if len(missing) > 12 else ''}")
        for r in recs:
            if not r["ok"]:
                print(f"{'':>16} FAIL {r['name']}: {r['err']}")
    print("\nALL FILES OK" if not bad_total else f"\n{bad_total} FILE(S) FAILED")
    return 1 if bad_total else 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1:]))
