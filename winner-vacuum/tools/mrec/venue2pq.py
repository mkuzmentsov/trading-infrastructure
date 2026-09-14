#!/usr/bin/env python3
"""venue2pq — convert the raw venue tapes (brec = Binance, hrec = Hyperliquid)
into typed, zstd-compressed parquet, one file per (coin, source, stream, day).

Why: the raw hourly `.jsonl.gz` archive runs ~15 GB/day fleet-wide. These rows
are extremely repetitive numeric records, so columnar + zstd typically shrinks
them several-fold AND makes them queryable without a JSON parse.

Usage:
    venue2pq.py <mrec_dir> <out_dir> [--coins btc,eth] [--days 20260913,...]
                [--prune]         # delete a raw file ONLY after its parquet
                                  # is written AND read back with the same row
                                  # count (verify-then-delete, same discipline
                                  # as tools/drain_mrec.sh)

Layout produced:
    <out_dir>/<source>/<stream>/<coin>-<YYYYMMDD>.parquet
      source : bin | hl
      stream : bookTicker | aggTrade | depth20 | kline_1s
               bbo | trades | l2Book | activeAssetCtx | candle

Schemas are flattened per stream (see _ROWS). Anything unrecognised is kept in
a catch-all `raw` table so nothing is silently dropped.
"""
from __future__ import annotations

import argparse, glob, gzip, json, os, sys, collections
import pyarrow as pa
import pyarrow.parquet as pq

CODEC = "zstd"


# ── per-stream flatteners: raw payload -> flat dict ─────────────────────────
def _bin_bookticker(t, m):
    return {"t": t, "u": m.get("u"), "bid": float(m["b"]), "bidsz": float(m["B"]),
            "ask": float(m["a"]), "asksz": float(m["A"])}


def _bin_aggtrade(t, m):
    return {"t": t, "E": m.get("E"), "T": m.get("T"), "a": m.get("a"),
            "px": float(m["p"]), "sz": float(m["q"]),
            "buyer_maker": bool(m.get("m"))}


def _bin_depth20(t, m):
    b = m.get("bids") or []
    a = m.get("asks") or []
    r = {"t": t, "lastUpdateId": m.get("lastUpdateId")}
    for i in range(20):
        r[f"bp{i}"] = float(b[i][0]) if i < len(b) else None
        r[f"bs{i}"] = float(b[i][1]) if i < len(b) else None
        r[f"ap{i}"] = float(a[i][0]) if i < len(a) else None
        r[f"as{i}"] = float(a[i][1]) if i < len(a) else None
    return r


def _bin_kline(t, m):
    k = m.get("k") or {}
    return {"t": t, "E": m.get("E"), "kt": k.get("t"), "kT": k.get("T"),
            "o": float(k["o"]), "h": float(k["h"]), "l": float(k["l"]),
            "c": float(k["c"]), "v": float(k["v"]), "n": k.get("n"),
            "closed": bool(k.get("x"))}


def _hl_bbo(t, m):
    bb = (m.get("bbo") or [None, None])
    f = lambda x, k: float(x[k]) if x and x.get(k) is not None else None
    return {"t": t, "time": m.get("time"),
            "bid": f(bb[0], "px"), "bidsz": f(bb[0], "sz"),
            "ask": f(bb[1], "px"), "asksz": f(bb[1], "sz")}


def _hl_l2(t, m):
    lv = m.get("levels") or [[], []]
    r = {"t": t, "time": m.get("time")}
    for i in range(10):
        for side, idx, pfx in ((lv[0], i, "b"), (lv[1], i, "a")):
            e = side[idx] if idx < len(side) else None
            r[f"{pfx}p{i}"] = float(e["px"]) if e else None
            r[f"{pfx}s{i}"] = float(e["sz"]) if e else None
            r[f"{pfx}n{i}"] = e.get("n") if e else None
    return r


def _hl_ctx(t, m):
    c = m.get("ctx") or {}
    g = lambda k: float(c[k]) if c.get(k) not in (None, "") else None
    return {"t": t, "funding": g("funding"), "oi": g("openInterest"),
            "mark": g("markPx"), "oracle": g("oraclePx"), "mid": g("midPx"),
            "prevDayPx": g("prevDayPx"), "dayNtlVlm": g("dayNtlVlm")}


def _hl_candle(t, m):
    return {"t": t, "kt": m.get("t"), "kT": m.get("T"),
            "o": float(m["o"]), "h": float(m["h"]), "l": float(m["l"]),
            "c": float(m["c"]), "v": float(m.get("v") or 0), "n": m.get("n")}


_ROWS = {
    ("bin", "bookTicker"): _bin_bookticker,
    ("bin", "aggTrade"): _bin_aggtrade,
    ("bin", "depth20"): _bin_depth20,
    ("bin", "kline_1s"): _bin_kline,
    ("hl", "bbo"): _hl_bbo,
    ("hl", "l2Book"): _hl_l2,
    ("hl", "activeAssetCtx"): _hl_ctx,
    ("hl", "trades"): None,          # list payload, flattened inline below
    ("hl", "candle"): _hl_candle,
}


def _classify(row):
    """(source, stream) for a raw row, or (source, None) if unknown."""
    ev = row.get("ev")
    if ev == "BIN":
        s = (row.get("s") or "").split("@", 1)[-1]
        s = {"depth20": "depth20"}.get(s.split("@")[0], s.split("@")[0])
        return "bin", s
    if ev == "HL":
        return "hl", row.get("s")
    return None, None


def convert(mrec_dir, out_dir, coins=None, days=None, prune=False):
    pat = os.path.join(mrec_dir, "*", "*-[bh]rec-*.jsonl.gz")
    files = sorted(glob.glob(pat))
    if coins:
        files = [f for f in files if os.path.basename(f).split("-")[0] in coins]
    if days:
        files = [f for f in files if any(d in os.path.basename(f) for d in days)]
    # NOTE: no mtime settle-filter. Local .gz files arrive via drain_mrec.sh,
    # which only pulls files already rotated AND settled >=90s POD-side, and
    # verifies size + gzip before writing. A local mtime check would filter on
    # "when we downloaded it", not "is it complete" — it only delayed every
    # file by one 30-min cycle.
    if not files:
        print("no raw venue files matched"); return 0, 0

    # group per RAW FILE (one hour). Per-DAY grouping would overwrite a day's
    # earlier rows when the same day is converted again later — the raw archive
    # grows hour by hour, so conversion must be idempotent at file granularity.
    # pyarrow reads a directory of hourly files as one dataset, so nothing is
    # lost by the finer split.
    groups = collections.defaultdict(list)
    for f in files:
        bn = os.path.basename(f)                      # btc-brec-20260913-14.jsonl.gz
        coin = bn.split("-")[0]
        stamp = "-".join(bn.rsplit("-", 2)[-2:]).replace(".jsonl.gz", "")  # 20260913-14
        groups[(coin, stamp)].append(f)

    raw_bytes = pq_bytes = 0
    for (coin, stamp), fl in sorted(groups.items()):
        tables = collections.defaultdict(list)        # (src,stream) -> rows
        unknown = []
        ndiff = [0]
        nread = 0
        for f in sorted(fl):
            raw_bytes += os.path.getsize(f)
            try:
                with gzip.open(f, "rt") as fh:
                    for line in fh:
                        try:
                            r = json.loads(line)
                        except Exception:
                            continue
                        nread += 1
                        src, stream = _classify(r)
                        # Binance `depth@100ms` is a DIFF stream: unusable
                        # without a REST snapshot anchor we never fetched, and
                        # storing it as JSON text defeats the whole point of
                        # this converter. The stream was dropped fleet-wide
                        # 2026-09-13; historical rows are discarded here.
                        if (src, stream) == ("bin", "depth"):
                            ndiff[0] += 1
                            continue
                        known = (src, stream) in _ROWS
                        fn = _ROWS.get((src, stream))
                        m = r.get("m")
                        if not known or not isinstance(m, (dict, list)):
                            unknown.append({"t": r.get("t"), "ev": r.get("ev"),
                                            "s": r.get("s"), "m": json.dumps(m)[:2000]})
                            continue
                        try:
                            if stream in ("trades",):        # HL trades = list
                                for x in (m if isinstance(m, list) else [m]):
                                    tables[(src, "trades")].append(
                                        {"t": r["t"], "time": x.get("time"),
                                         "side": x.get("side"), "px": float(x["px"]),
                                         "sz": float(x["sz"]), "hash": x.get("hash")})
                            else:
                                tables[(src, stream)].append(fn(r["t"], m))
                        except Exception:
                            unknown.append({"t": r.get("t"), "ev": r.get("ev"),
                                            "s": r.get("s"), "m": json.dumps(m)[:2000]})
            except (EOFError, OSError) as e:
                print(f"WARN {f}: {e}", file=sys.stderr)

        written = 0

        def _write(src, stream, rows):
            nonlocal pq_bytes, written
            if not rows:
                return
            d = os.path.join(out_dir, src, stream)
            os.makedirs(d, exist_ok=True)
            p = os.path.join(d, f"{coin}-{stamp}.parquet")
            tbl = pa.Table.from_pylist(rows)
            pq.write_table(tbl, p, compression=CODEC)
            back = pq.read_metadata(p).num_rows
            if back != len(rows):
                raise RuntimeError(f"verify failed {p}: {back} != {len(rows)}")
            pq_bytes += os.path.getsize(p)
            written += back

        for (src, stream), rows in sorted(tables.items()):
            _write(src, stream, rows)
        if unknown:
            _write("misc", "raw", unknown)

        # verify: every raw row must be accounted for — written to parquet,
        # deliberately dropped (depth diffs), or captured in the catch-all.
        # ⚠️ the first version omitted ndiff here, so `ok` was False on every
        # file containing depth diffs and NOTHING was ever pruned (found
        # 2026-09-13 by noticing raw files surviving repeated cycles).
        ok = (written + ndiff[0] + len(unknown)) >= nread
        print(f"{coin} {stamp}: {nread:>9,} rows -> {written:>9,} parquet rows"
              f" ({len(tables)} streams, {ndiff[0]:,} depth-diffs dropped,"
              f" {len(unknown)} unknown)")
        if prune and ok and written:
            for f in fl:
                os.remove(f)
            print(f"   pruned {len(fl)} raw files")
    return raw_bytes, pq_bytes


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("mrec_dir"); ap.add_argument("out_dir")
    ap.add_argument("--coins"); ap.add_argument("--days")
    ap.add_argument("--prune", action="store_true")
    a = ap.parse_args()
    rb, pb = convert(a.mrec_dir, a.out_dir,
                     a.coins.split(",") if a.coins else None,
                     a.days.split(",") if a.days else None,
                     a.prune)
    if rb:
        print(f"\nraw {rb/1e9:.2f} GB -> parquet {pb/1e9:.2f} GB "
              f"({rb/max(pb,1):.1f}x smaller, codec={CODEC})")
