"""Build a training parquet from one or more logs-training.jsonl files.

Each snapshot becomes one row. The label `y` is the bar's eventual outcome:
1 if BTC closed higher than bar_open at bar_end, 0 otherwise. A single bar
contributes many rows (one per eval tick), all sharing the same label — so
train/test splits must be grouped by `condition_id`.

Usage:
    python prepare_dataset.py \\
        --logs-glob '../../polymarket/k8s/helm/polymarket-btc-bot/pm-btc-logs_*/logs-training.jsonl' \\
        --output outputs/pm_btc_dataset.parquet
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import os
import sys
from collections import defaultdict
from typing import Any

import pandas as pd

# Allow `from features import …` when run as a script.
sys.path.insert(0, os.path.dirname(__file__))
from features import FEATURE_COLUMNS, extract_features  # noqa: E402


def _iter_jsonl(path: str):
    with open(path, "r") as f:
        for i, line in enumerate(f):
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                print(f"  skipping malformed row {i} in {path}")


def build_bar_outcomes(
    snapshots_by_bar: dict[str, list[dict]],
    min_final_window_secs: int = 180,
) -> dict[str, int]:
    """For each bar (keyed by condition_id), compute label: 1 if BTC price at
    the latest in-bar snapshot > bar_open, else 0.

    Imperfect: real resolution uses a specific chainlink oracle round at
    bar_end. We use the last BTC price we observed inside the bar. Accept bars
    where the last snapshot is within `min_final_window_secs` of bar_end —
    default 180s (i.e. we saw at least the second half of the bar). Tune via
    the CLI if you want stricter labels.
    """
    labels: dict[str, int] = {}
    for cid, rows in snapshots_by_bar.items():
        if not rows:
            continue
        rows_sorted = sorted(rows, key=lambda r: r.get("ts", 0))
        if len(rows_sorted) < 3:
            continue
        last = rows_sorted[-1]
        btc = last.get("btc") or {}
        bar_open = btc.get("bar_open") or 0.0
        last_price = btc.get("current_price") or 0.0
        if bar_open <= 0 or last_price <= 0:
            continue
        market_end = last.get("market_end_ts") or 0
        last_ts = last.get("ts") or 0
        if market_end and last_ts and (market_end - last_ts) > min_final_window_secs:
            # Bar was cut off too early — skip.
            continue
        labels[cid] = int(last_price > bar_open)
    return labels


def build_dataset(log_paths: list[str], min_final_window_secs: int = 180) -> pd.DataFrame:
    """Parse all logs, group by bar, emit one row per snapshot with label.

    Returns DataFrame with columns = FEATURE_COLUMNS + [ts, condition_id, y,
    source_file].
    """
    snapshots_by_bar: dict[str, list[dict]] = defaultdict(list)
    total = 0
    for path in log_paths:
        print(f"scanning {path} …")
        n = 0
        for row in _iter_jsonl(path):
            cid = row.get("condition_id")
            if not cid:
                continue
            row["_source_file"] = os.path.basename(os.path.dirname(path))
            snapshots_by_bar[cid].append(row)
            n += 1
        print(f"  {n} snapshots across {len(snapshots_by_bar)} bars so far")
        total += n

    print(f"\n{total} total snapshots across {len(snapshots_by_bar)} bars — building labels")
    labels = build_bar_outcomes(snapshots_by_bar, min_final_window_secs=min_final_window_secs)
    print(f"{len(labels)} bars have usable labels "
          f"(dropped {len(snapshots_by_bar) - len(labels)} bars as incomplete)")

    records: list[dict[str, Any]] = []
    for cid, label in labels.items():
        for row in snapshots_by_bar[cid]:
            feats = extract_features(row)
            if feats is None:
                continue
            feats["ts"] = float(row.get("ts") or 0.0)
            feats["condition_id"] = cid
            feats["y"] = int(label)
            feats["source_file"] = row.get("_source_file", "")
            records.append(feats)

    df = pd.DataFrame.from_records(records)
    print(f"\nfinal dataset: {len(df)} rows, {df['condition_id'].nunique()} bars")
    print(f"label balance: up={int(df['y'].sum())} down={int((df['y']==0).sum())}")
    return df


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--logs-glob", required=True,
                    help="Glob for logs-training.jsonl files (quote in shell)")
    ap.add_argument("--output", required=True,
                    help="Output path (.parquet if pyarrow installed, else .csv)")
    ap.add_argument("--min-final-window-secs", type=int, default=180,
                    help="Accept bars with last snapshot within this many "
                         "seconds of bar_end (default 180)")
    args = ap.parse_args()

    paths = sorted(glob.glob(os.path.expanduser(args.logs_glob)))
    if not paths:
        raise SystemExit(f"no files match {args.logs_glob}")
    print(f"found {len(paths)} log file(s)")

    df = build_dataset(paths, min_final_window_secs=args.min_final_window_secs)
    out = args.output
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    try:
        df.to_parquet(out, index=False)
    except (ImportError, ValueError) as exc:
        csv_path = os.path.splitext(out)[0] + ".csv"
        print(f"parquet write failed ({exc}); falling back to CSV at {csv_path}")
        df.to_csv(csv_path, index=False)
        out = csv_path
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
