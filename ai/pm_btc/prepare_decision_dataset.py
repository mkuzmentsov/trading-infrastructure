"""Synthesize entry/exit decision datasets from PM BTC bot logs.

The labels are forward-looking:
- entry: if we bought the proposed side now, would the future best bid or final
  bar resolution justify entering?
- exit: is the current bid already close enough to the best value still
  available from here that we should exit now?
"""
from __future__ import annotations

import argparse
import glob
import json
import os
from collections import Counter, defaultdict
from typing import Any, Iterable, Optional

import pandas as pd

from decision_features import (
    extract_entry_features,
    extract_exit_features,
)


def iter_jsonl(path: str) -> Iterable[dict[str, Any]]:
    with open(path, "r") as handle:
        for idx, line in enumerate(handle):
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                print(f"skipping malformed row {idx} in {path}")


def discover_bundle_dirs(patterns: list[str]) -> list[str]:
    bundle_dirs: list[str] = []
    for pattern in patterns:
        for path in sorted(glob.glob(os.path.expanduser(pattern))):
            if os.path.isdir(path):
                bundle_dirs.append(path)
            elif os.path.basename(path) == "logs-training.jsonl":
                bundle_dirs.append(os.path.dirname(path))
    return sorted(set(bundle_dirs))


def bundle_name(bundle_dir: str) -> str:
    return os.path.basename(os.path.abspath(bundle_dir))


def is_clean_close_event(row: dict[str, Any]) -> bool:
    if row.get("event") != "position_closed":
        return False
    tracked_position = row.get("tracked_position")
    if tracked_position is False:
        return False
    if row.get("market_start_ts") is None and tracked_position is not True:
        return False
    return True


def load_bundle_rows(bundle_dir: str) -> dict[str, list[dict[str, Any]]]:
    path = os.path.join(bundle_dir, "logs-training.jsonl")
    by_bar: dict[str, list[dict[str, Any]]] = defaultdict(list)
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


def compute_future_best_values(rows: list[dict[str, Any]], terminal_up_value: float) -> dict[str, list[float]]:
    n_rows = len(rows)
    incl_up = [0.0] * n_rows
    incl_down = [0.0] * n_rows
    excl_up = [0.0] * n_rows
    excl_down = [0.0] * n_rows

    best_up_after = terminal_up_value
    best_down_after = 1.0 - terminal_up_value

    for idx in range(n_rows - 1, -1, -1):
        excl_up[idx] = best_up_after
        excl_down[idx] = best_down_after
        pm = rows[idx].get("pm") or {}
        best_up_after = max(best_up_after, float(pm.get("up_bid") or 0.0))
        best_down_after = max(best_down_after, float(pm.get("down_bid") or 0.0))
        incl_up[idx] = best_up_after
        incl_down[idx] = best_down_after

    return {
        "incl_up": incl_up,
        "incl_down": incl_down,
        "excl_up": excl_up,
        "excl_down": excl_down,
    }


def clean_realized_metrics(bundle_dir: str) -> dict[str, Any]:
    path = os.path.join(bundle_dir, "logs-training-events.jsonl")
    if not os.path.exists(path):
        return {
            "bundle": bundle_name(bundle_dir),
            "n_clean_closes": 0,
            "realized_pnl": 0.0,
            "exit_reason_split": {},
        }

    pnl = 0.0
    closes = 0
    reasons: Counter[str] = Counter()
    for row in iter_jsonl(path):
        if not is_clean_close_event(row):
            continue
        closes += 1
        pnl += float(row.get("pnl") or 0.0)
        reasons[str(row.get("reason") or "unknown")] += 1

    return {
        "bundle": bundle_name(bundle_dir),
        "n_clean_closes": closes,
        "realized_pnl": round(pnl, 4),
        "exit_reason_split": dict(sorted(reasons.items())),
    }


def load_matched_trades(bundle_dir: str) -> list[dict[str, Any]]:
    path = os.path.join(bundle_dir, "logs-training-events.jsonl")
    if not os.path.exists(path):
        return []

    open_queues: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    trades: list[dict[str, Any]] = []
    events = sorted(iter_jsonl(path), key=lambda row: float(row.get("ts") or 0.0))

    for row in events:
        event = row.get("event")
        if event == "position_opened":
            key = (str(row.get("condition_id") or ""), str(row.get("direction") or ""))
            if key[0] and key[1]:
                open_queues[key].append(row)
            continue
        if not is_clean_close_event(row):
            continue
        key = (str(row.get("condition_id") or ""), str(row.get("direction") or ""))
        queue = open_queues.get(key) or []
        if not queue:
            continue
        open_event = queue.pop(0)
        trades.append(
            {
                "bundle": bundle_name(bundle_dir),
                "condition_id": key[0],
                "direction": key[1],
                "open_ts": float(open_event.get("ts") or 0.0),
                "close_ts": float(row.get("ts") or 0.0),
                "entry_price": float(open_event.get("entry_price") or row.get("entry_price") or 0.0),
                "entry_seconds_left": int(open_event.get("entry_seconds_left") or 0),
                "entry_edge": float(open_event.get("entry_edge") or 0.0),
                "shares": float(row.get("shares") or open_event.get("shares") or 0.0),
                "pnl": float(row.get("pnl") or 0.0),
                "exit_price": float(row.get("exit_price") or 0.0),
                "exit_reason": str(row.get("reason") or ""),
                "dry_run": bool(open_event.get("dry_run") or row.get("dry_run")),
                "tracked_position": row.get("tracked_position"),
                "market_start_ts": row.get("market_start_ts"),
            }
        )

    return trades


def _find_entry_snapshot(rows: list[dict[str, Any]], trade: dict[str, Any]) -> Optional[dict[str, Any]]:
    best_row = None
    best_score = None
    for row in rows:
        if row.get("context") != "try_enter":
            continue
        signal = row.get("signal") or {}
        action = signal.get("action")
        row_dir = "UP" if action == "BUY_UP" else "DOWN" if action == "BUY_DOWN" else None
        if row_dir != trade["direction"]:
            continue
        row_ts = float(row.get("ts") or 0.0)
        dt = abs(row_ts - trade["open_ts"])
        if dt > 10.0:
            continue
        signal_price = float(signal.get("price") or 0.0)
        price_gap = abs(signal_price - trade["entry_price"])
        score = (dt, price_gap)
        if best_score is None or score < best_score:
            best_score = score
            best_row = row
    return best_row


def _find_exit_snapshot(rows: list[dict[str, Any]], trade: dict[str, Any]) -> Optional[dict[str, Any]]:
    best_row = None
    best_ts = float("-inf")
    for row in rows:
        if row.get("context") != "manage_position":
            continue
        position = row.get("position") or {}
        if position.get("direction") != trade["direction"]:
            continue
        entry_price = float(position.get("entry_price") or 0.0)
        if abs(entry_price - trade["entry_price"]) > 0.03:
            continue
        row_ts = float(row.get("ts") or 0.0)
        if row_ts < trade["open_ts"] - 2.0 or row_ts > trade["close_ts"] + 2.0:
            continue
        if row_ts <= trade["close_ts"] + 2.0 and row_ts > best_ts:
            best_ts = row_ts
            best_row = row
    return best_row


def build_decision_datasets(
    bundle_dirs: list[str],
    entry_profit_threshold: float,
    exit_margin: float,
    entry_label_mode: str = "bestbid",
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    entry_records: list[dict[str, Any]] = []
    exit_records: list[dict[str, Any]] = []
    bundle_records: list[dict[str, Any]] = []

    for bundle_dir in bundle_dirs:
        bundle = bundle_name(bundle_dir)
        rows_by_bar = load_bundle_rows(bundle_dir)
        outcomes = build_bar_outcomes(rows_by_bar)
        bundle_entry_rows = 0
        bundle_exit_rows = 0

        for cid, rows in rows_by_bar.items():
            if cid not in outcomes:
                continue

            future = compute_future_best_values(rows, terminal_up_value=float(outcomes[cid]))
            trade_segment = 0
            active_trade_key: tuple[Any, ...] | None = None

            for idx, row in enumerate(rows):
                context = row.get("context")

                if context == "try_enter":
                    feats = extract_entry_features(row)
                    if feats is not None:
                        direction = "UP" if feats["direction_up"] >= 0.5 else "DOWN"
                        future_best_value = future["incl_up"][idx] if direction == "UP" else future["incl_down"][idx]
                        entry_price = float(feats["candidate_price"])
                        best_edge = future_best_value - entry_price
                        terminal_value = float(outcomes[cid]) if direction == "UP" else float(1 - outcomes[cid])
                        terminal_edge = terminal_value - entry_price
                        if entry_label_mode == "terminal":
                            # Hold-to-expiry: only resolution matters. Ignores
                            # mid-bar bid spikes that aren't actually realizable.
                            label = int(terminal_edge >= entry_profit_threshold)
                        elif entry_label_mode == "hybrid":
                            # Must be a winner at resolution AND have enough
                            # mid-bar slack to survive noise.
                            label = int(terminal_edge > 0 and best_edge >= entry_profit_threshold)
                        else:
                            label = int(best_edge >= entry_profit_threshold)
                        entry_records.append(
                            {
                                **feats,
                                "bundle": bundle,
                                "condition_id": cid,
                                "ts": float(row.get("ts") or 0.0),
                                "direction": direction,
                                "entry_label": label,
                                "label_source": "synthetic",
                                "sample_weight": 1.0,
                                "future_best_value": round(future_best_value, 6),
                                "future_best_edge": round(best_edge, 6),
                                "terminal_value": terminal_value,
                                "terminal_edge": round(terminal_edge, 6),
                            }
                        )
                        bundle_entry_rows += 1
                    active_trade_key = None
                    continue

                if context != "manage_position":
                    active_trade_key = None
                    continue

                feats = extract_exit_features(row)
                if feats is None:
                    continue

                position = row.get("position") or {}
                direction = position.get("direction")
                trade_key = (
                    direction,
                    round(float(position.get("entry_price") or 0.0), 4),
                    int(position.get("entry_seconds_left") or 0),
                )
                if trade_key != active_trade_key:
                    trade_segment += 1
                    active_trade_key = trade_key

                future_best_value = future["excl_up"][idx] if direction == "UP" else future["excl_down"][idx]
                current_bid = float(feats["current_side_bid"])
                future_improvement = future_best_value - current_bid
                label = int(current_bid >= (future_best_value - exit_margin))
                exit_records.append(
                    {
                        **feats,
                        "bundle": bundle,
                        "condition_id": cid,
                        "trade_id": f"{bundle}:{cid}:{trade_segment}",
                        "ts": float(row.get("ts") or 0.0),
                        "direction": direction,
                        "exit_label": label,
                        "label_source": "synthetic",
                        "sample_weight": 1.0,
                        "future_best_value": round(future_best_value, 6),
                        "future_improvement": round(future_improvement, 6),
                        "terminal_value": float(outcomes[cid]) if direction == "UP" else float(1 - outcomes[cid]),
                    }
                )
                bundle_exit_rows += 1

        matched_trades = load_matched_trades(bundle_dir)
        real_entry_rows = 0
        real_exit_rows = 0
        for trade_idx, trade in enumerate(matched_trades, start=1):
            rows = rows_by_bar.get(trade["condition_id"]) or []
            if not rows:
                continue
            entry_snapshot = _find_entry_snapshot(rows, trade)
            if entry_snapshot is not None:
                feats = extract_entry_features(entry_snapshot)
                if feats is not None:
                    entry_records.append(
                        {
                            **feats,
                            "bundle": bundle,
                            "condition_id": trade["condition_id"],
                            "ts": float(entry_snapshot.get("ts") or 0.0),
                            "direction": trade["direction"],
                            "entry_label": int(trade["pnl"] > 0),
                            "label_source": "realized_trade",
                            "sample_weight": 0.35 if not trade["dry_run"] else 0.2,
                            "future_best_value": None,
                            "future_best_edge": None,
                            "terminal_value": None,
                            "realized_pnl": trade["pnl"],
                            "exit_reason": trade["exit_reason"],
                        }
                    )
                    real_entry_rows += 1

            exit_snapshot = _find_exit_snapshot(rows, trade)
            if exit_snapshot is not None:
                feats = extract_exit_features(exit_snapshot)
                if feats is not None:
                    exit_records.append(
                        {
                            **feats,
                            "bundle": bundle,
                            "condition_id": trade["condition_id"],
                            "trade_id": f"{bundle}:{trade['condition_id']}:real:{trade_idx}",
                            "ts": float(exit_snapshot.get("ts") or 0.0),
                            "direction": trade["direction"],
                            "exit_label": 1,
                            "label_source": "realized_trade",
                            "sample_weight": 0.3 if not trade["dry_run"] else 0.18,
                            "future_best_value": None,
                            "future_improvement": None,
                            "terminal_value": None,
                            "realized_pnl": trade["pnl"],
                            "exit_reason": trade["exit_reason"],
                        }
                    )
                    real_exit_rows += 1

        bundle_records.append(
            {
                **clean_realized_metrics(bundle_dir),
                "n_bars": len(rows_by_bar),
                "usable_bars": len(outcomes),
                "entry_rows": bundle_entry_rows,
                "exit_rows": bundle_exit_rows,
                "real_entry_rows": real_entry_rows,
                "real_exit_rows": real_exit_rows,
            }
        )

    entry_df = pd.DataFrame.from_records(entry_records)
    exit_df = pd.DataFrame.from_records(exit_records)
    bundle_df = pd.DataFrame.from_records(bundle_records).sort_values("bundle")
    return entry_df, exit_df, bundle_df


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--bundle-glob",
        action="append",
        required=True,
        help="Glob for bundle directories or logs-training.jsonl files. Repeatable.",
    )
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--entry-profit-threshold", type=float, default=0.04)
    parser.add_argument("--exit-margin", type=float, default=0.02)
    parser.add_argument(
        "--entry-label-mode",
        choices=["bestbid", "terminal", "hybrid"],
        default="bestbid",
        help=(
            "bestbid=legacy (mid-bar best bid as label target); "
            "terminal=use only bar resolution (for hold-to-expiry bots); "
            "hybrid=require terminal win AND mid-bar slack."
        ),
    )
    args = parser.parse_args()

    bundle_dirs = discover_bundle_dirs(args.bundle_glob)
    if not bundle_dirs:
        raise SystemExit("no bundle directories matched")

    print(f"found {len(bundle_dirs)} bundles")
    entry_df, exit_df, bundle_df = build_decision_datasets(
        bundle_dirs=bundle_dirs,
        entry_profit_threshold=args.entry_profit_threshold,
        exit_margin=args.exit_margin,
        entry_label_mode=args.entry_label_mode,
    )

    os.makedirs(args.output_dir, exist_ok=True)
    entry_path = os.path.join(args.output_dir, "pm_btc_entry_dataset.parquet")
    exit_path = os.path.join(args.output_dir, "pm_btc_exit_dataset.parquet")
    bundle_path = os.path.join(args.output_dir, "pm_btc_bundle_summary.json")

    entry_df.to_parquet(entry_path, index=False)
    exit_df.to_parquet(exit_path, index=False)
    with open(bundle_path, "w") as handle:
        json.dump(bundle_df.to_dict(orient="records"), handle, indent=2)

    print(
        f"entry rows={len(entry_df)} positives={int(entry_df['entry_label'].sum())} "
        f"bundles={entry_df['bundle'].nunique()}"
    )
    print(f"entry label sources={entry_df['label_source'].value_counts().to_dict()}")
    print(
        f"exit rows={len(exit_df)} positives={int(exit_df['exit_label'].sum())} "
        f"trades={exit_df['trade_id'].nunique()}"
    )
    print(f"exit label sources={exit_df['label_source'].value_counts().to_dict()}")
    print(f"wrote {entry_path}")
    print(f"wrote {exit_path}")
    print(f"wrote {bundle_path}")


if __name__ == "__main__":
    main()
