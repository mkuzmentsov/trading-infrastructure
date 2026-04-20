"""v2 dataset builder for the PM BTC entry gate.

Key differences vs prepare_decision_dataset.py:
  * Labels are **time-windowed** and **size-executable**:
      label_60s  = 1 if within 60s of the candidate snap there exists a future
                   snap whose same-side best bid >= candidate_price + threshold
                   AND whose same-side bid_size >= the candidate's shares.
      label_120s analogous with a 120s horizon (emitted for multi-task).
      label_bar_end = 1 if the bar outcome matches the candidate direction
                   (keeps the v1-style "hold-to-expiry wins" signal).
  * Chronological bundle ordering so train_v2.py can build proper walk-forward
    splits without re-sorting.
  * Computes rate-of-change features via decision_features_v2 using the
    in-bar history up to the candidate tick.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
from collections import defaultdict
from typing import Any, Iterable, Optional

import pandas as pd

from decision_features_v2 import ENTRY_FEATURE_COLUMNS_V2, extract_entry_features_v2


_BUNDLE_TS_RE = re.compile(r"(\d{8}_\d{6})")


def iter_jsonl(path: str) -> Iterable[dict[str, Any]]:
    with open(path, "r") as handle:
        for idx, line in enumerate(handle):
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                print(f"skipping malformed row {idx} in {path}")


def discover_bundle_dirs(patterns: list[str]) -> list[str]:
    out: list[str] = []
    for pattern in patterns:
        for path in sorted(glob.glob(os.path.expanduser(pattern))):
            if os.path.isdir(path):
                out.append(path)
            elif os.path.basename(path) == "logs-training.jsonl":
                out.append(os.path.dirname(path))
    return sorted(set(out))


def bundle_name(bundle_dir: str) -> str:
    return os.path.basename(os.path.abspath(bundle_dir))


def bundle_sort_key(bundle_dir: str) -> str:
    """Sort bundles chronologically by the YYYYMMDD_HHMMSS in their folder name.
    Falls back to the raw name when no timestamp is present."""
    name = bundle_name(bundle_dir)
    match = _BUNDLE_TS_RE.search(name)
    return match.group(1) if match else name


def load_bundle_rows(bundle_dir: str) -> dict[str, list[dict[str, Any]]]:
    path = os.path.join(bundle_dir, "logs-training.jsonl")
    by_bar: dict[str, list[dict[str, Any]]] = defaultdict(list)
    if not os.path.exists(path):
        return {}
    for row in iter_jsonl(path):
        cid = row.get("condition_id")
        if not cid:
            continue
        row["_bundle"] = bundle_name(bundle_dir)
        by_bar[cid].append(row)
    for rows in by_bar.values():
        rows.sort(key=lambda row: float(row.get("ts") or 0.0))
    return dict(by_bar)


def build_bar_outcomes(rows_by_bar: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
    labels: dict[str, int] = {}
    for cid, rows in rows_by_bar.items():
        if not rows:
            continue
        last = rows[-1]
        btc = last.get("btc") or {}
        bar_open = float(btc.get("bar_open") or 0.0)
        last_price = float(btc.get("current_price") or 0.0)
        if bar_open <= 0 or last_price <= 0:
            continue
        labels[cid] = int(last_price > bar_open)
    return labels


def _pm_bid_size(row: dict[str, Any], direction: str) -> tuple[float, float]:
    pm = row.get("pm") or {}
    if direction == "UP":
        return float(pm.get("up_bid") or 0.0), float(pm.get("up_bid_size") or 0.0)
    return float(pm.get("down_bid") or 0.0), float(pm.get("down_bid_size") or 0.0)


def executable_window_label(
    rows: list[dict[str, Any]],
    idx: int,
    direction: str,
    candidate_price: float,
    candidate_shares: float,
    horizon_secs: float,
    profit_threshold: float,
) -> tuple[int, float, float]:
    """Return (label, best_bid_seen, best_bid_with_size_seen) over the window
    (rows[idx].ts, rows[idx].ts + horizon_secs].

    label=1 requires BOTH the price threshold and bid_size >= shares at the
    same snapshot, so the trade is actually fillable for size.
    """
    if not rows or idx >= len(rows):
        return 0, 0.0, 0.0
    start_ts = float(rows[idx].get("ts") or 0.0)
    deadline = start_ts + horizon_secs
    best_bid = 0.0
    best_bid_with_size = 0.0
    label = 0
    for j in range(idx + 1, len(rows)):
        ts = float(rows[j].get("ts") or 0.0)
        if ts > deadline:
            break
        bid, size = _pm_bid_size(rows[j], direction)
        if bid > best_bid:
            best_bid = bid
        if size >= max(1.0, candidate_shares) and bid > best_bid_with_size:
            best_bid_with_size = bid
            if bid >= candidate_price + profit_threshold:
                label = 1
                break
    return label, best_bid, best_bid_with_size


def bar_end_direction_label(direction: str, outcome: int) -> int:
    if direction == "UP":
        return int(outcome == 1)
    return int(outcome == 0)


def build_dataset(
    bundle_dirs: list[str],
    profit_threshold: float,
    horizons: list[float],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows_out: list[dict[str, Any]] = []
    bundle_records: list[dict[str, Any]] = []

    for bundle_dir in bundle_dirs:
        bundle = bundle_name(bundle_dir)
        rows_by_bar = load_bundle_rows(bundle_dir)
        outcomes = build_bar_outcomes(rows_by_bar)
        entries = 0
        positives_primary = 0

        for cid, rows in rows_by_bar.items():
            if cid not in outcomes:
                continue

            for idx, row in enumerate(rows):
                if row.get("context") != "try_enter":
                    continue
                feats = extract_entry_features_v2(row, rows[:idx])
                if feats is None:
                    continue
                direction = feats.pop("_direction")
                candidate_price = feats.pop("_candidate_price")
                feats.pop("_candidate_bid_size", None)

                signal = row.get("signal") or {}
                candidate_shares = float(signal.get("size") or 1.0)

                labels: dict[str, int] = {}
                for horizon in horizons:
                    key = f"label_{int(horizon)}s"
                    label, best_bid, best_bid_with_size = executable_window_label(
                        rows=rows,
                        idx=idx,
                        direction=direction,
                        candidate_price=candidate_price,
                        candidate_shares=candidate_shares,
                        horizon_secs=horizon,
                        profit_threshold=profit_threshold,
                    )
                    labels[key] = label
                    labels[f"best_bid_{int(horizon)}s"] = round(best_bid, 4)
                    labels[f"best_bid_with_size_{int(horizon)}s"] = round(best_bid_with_size, 4)

                labels["label_bar_end"] = bar_end_direction_label(direction, int(outcomes[cid]))

                record = dict(feats)
                record["bundle"] = bundle
                record["condition_id"] = cid
                record["ts"] = float(row.get("ts") or 0.0)
                record["direction"] = direction
                record["candidate_price"] = candidate_price
                record["candidate_shares"] = candidate_shares
                record.update(labels)
                rows_out.append(record)
                entries += 1
                if labels.get(f"label_{int(horizons[0])}s", 0) == 1:
                    positives_primary += 1

        bundle_records.append(
            {
                "bundle": bundle,
                "sort_key": bundle_sort_key(bundle_dir),
                "n_bars": len(rows_by_bar),
                "usable_bars": len(outcomes),
                "entry_rows": entries,
                "positives_primary": positives_primary,
            }
        )

    df = pd.DataFrame.from_records(rows_out)
    bundles = pd.DataFrame.from_records(bundle_records).sort_values("sort_key").reset_index(drop=True)
    return df, bundles


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle-glob", action="append", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--profit-threshold", type=float, default=0.04)
    parser.add_argument("--horizons", type=str, default="60,120",
                        help="Comma-separated horizons in seconds. First is the primary label.")
    args = parser.parse_args()

    horizons = [float(x.strip()) for x in args.horizons.split(",") if x.strip()]
    if not horizons:
        raise SystemExit("--horizons must include at least one value")

    bundle_dirs = discover_bundle_dirs(args.bundle_glob)
    if not bundle_dirs:
        raise SystemExit("no bundle directories matched")
    bundle_dirs_sorted = sorted(bundle_dirs, key=bundle_sort_key)

    entry_df, bundle_df = build_dataset(
        bundle_dirs=bundle_dirs_sorted,
        profit_threshold=args.profit_threshold,
        horizons=horizons,
    )

    os.makedirs(args.output_dir, exist_ok=True)
    entry_path = os.path.join(args.output_dir, "pm_btc_entry_dataset_v2.parquet")
    bundle_path = os.path.join(args.output_dir, "pm_btc_bundle_order_v2.json")

    entry_df.to_parquet(entry_path, index=False)
    with open(bundle_path, "w") as handle:
        json.dump(bundle_df.to_dict(orient="records"), handle, indent=2)

    primary_key = f"label_{int(horizons[0])}s"
    positives = int(entry_df[primary_key].sum()) if len(entry_df) else 0
    print(
        f"entry rows={len(entry_df)} positives={positives} "
        f"bundles={entry_df['bundle'].nunique()}"
    )
    print(f"feature count: {len(ENTRY_FEATURE_COLUMNS_V2)}")
    print(f"wrote {entry_path}")
    print(f"wrote {bundle_path}")


if __name__ == "__main__":
    main()
