"""Build exit-classifier dataset from manage_position snapshots.

Walks all pm-btc-smart training bundles under the helm chart, joins each
in-position tick to its eventual close, and writes a feature matrix +
labels to parquet. Label is binary: did this tick's position eventually
exit at a price meaningfully worse than the current bid?

Usage:
    python3 prepare_exit_dataset.py [--out PATH] [--bundles GLOB]

Mirrors the convention from ai/pm_btc/prepare_decision_dataset_v2.py.
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import os
from collections import defaultdict
from pathlib import Path

import pandas as pd

DEFAULT_BUNDLE_GLOB = (
    "polymarket/k8s/helm/polymarket-btc-bot/pm-btc-logs_pm-btc-smart_*"
)
DEFAULT_OUT = "ai/pm_btc_exit/exit_dataset_v1.parquet"

# Label config: positive when eventual exit ≥ current_bid + LABEL_DROP (i.e.
# dumping now would have been better than waiting for the actual exit).
LABEL_DROP = 0.05


FEATURE_COLUMNS = [
    # time/state — these change every tick
    "seconds_left", "time_held", "time_frac",
    # price state on own side, derived relative to entry
    "current_bid", "bid_above_entry",
    "peak_minus_current", "unrealized_per_share",
    # bid velocity (the strongest visual signal in the anatomy diagnostic)
    "bid_drift_3s", "bid_drift_10s",
    # PM book
    "own_spread", "own_bid_size_log", "own_ask_size_log",
    "opp_spread", "book_imbalance",
    # BTC
    "btc_ret_30s", "btc_ret_60s", "btc_ret_30m", "sigma_5m",
    "btc_distance_from_entry", "adverse_btc",
    "binance_chainlink_divergence",
    # direction (UP=1, DOWN=0). Entry-static features (entry_edge, entry_p_up,
    # entry_price, entry_seconds_left, peak_bid absolute) are deliberately
    # excluded: they were dominating gain in the first model run and caused it
    # to memorize positions instead of learning per-tick trajectory signal.
    "direction_up",
]


def safe_log1p(x: float) -> float:
    try:
        return math.log1p(max(0.0, float(x)))
    except (TypeError, ValueError):
        return 0.0


def feature_row(snap: dict) -> dict | None:
    pos = snap.get("position") or {}
    ext = snap.get("position_extras") or {}
    dec = snap.get("decision") or {}
    btc = snap.get("btc") or {}
    pm = snap.get("pm") or {}
    bid_hist = snap.get("bid_history") or {}

    direction = pos.get("direction")
    if direction not in ("UP", "DOWN"):
        return None
    direction_up = 1.0 if direction == "UP" else 0.0
    entry_price = float(pos.get("entry_price") or 0.0)
    if entry_price <= 0:
        return None

    current_bid = float(dec.get("current_bid") or 0.0)
    peak_bid = float(pos.get("peak_bid") or current_bid)
    seconds_left = int(snap.get("seconds_left") or 0)
    time_held = float(ext.get("time_held") or 0.0)
    bar_total = max(time_held + seconds_left, 1.0)
    time_frac = time_held / bar_total

    # Bid velocity from bid_history
    own_3s_key = "up_bid_3s_ago" if direction == "UP" else "down_bid_3s_ago"
    own_10s_key = "up_bid_10s_ago" if direction == "UP" else "down_bid_10s_ago"
    bid_3s_ago = float(bid_hist.get(own_3s_key) or current_bid)
    bid_10s_ago = float(bid_hist.get(own_10s_key) or current_bid)
    bid_drift_3s = current_bid - bid_3s_ago
    bid_drift_10s = current_bid - bid_10s_ago

    # PM book
    if direction == "UP":
        own_bid = float(pm.get("up_bid") or 0)
        own_ask = float(pm.get("up_ask") or 0)
        own_bid_size = float(pm.get("up_bid_size") or 0)
        own_ask_size = float(pm.get("up_ask_size") or 0)
        opp_bid = float(pm.get("down_bid") or 0)
        opp_ask = float(pm.get("down_ask") or 0)
    else:
        own_bid = float(pm.get("down_bid") or 0)
        own_ask = float(pm.get("down_ask") or 0)
        own_bid_size = float(pm.get("down_bid_size") or 0)
        own_ask_size = float(pm.get("down_ask_size") or 0)
        opp_bid = float(pm.get("up_bid") or 0)
        opp_ask = float(pm.get("up_ask") or 0)

    own_spread = max(0.0, own_ask - own_bid)
    opp_spread = max(0.0, opp_ask - opp_bid)
    total_size = own_bid_size + own_ask_size
    book_imbalance = (own_bid_size - own_ask_size) / total_size if total_size > 0 else 0.0

    # BTC
    bar_open = float(btc.get("bar_open") or 0.0)
    cur_btc = float(btc.get("current_price") or 0.0)
    binance_price = float(btc.get("binance_price") or 0.0)
    entry_btc = float(ext.get("entry_btc_price") or 0.0)
    btc_distance_from_entry = 0.0
    if entry_btc > 0 and cur_btc > 0:
        log_return = math.log(cur_btc / entry_btc)
        # Sign so that "favorable" = positive (DOWN bet wants BTC down)
        btc_distance_from_entry = log_return if direction == "UP" else -log_return
    binance_chainlink_divergence = 0.0
    if binance_price > 0 and cur_btc > 0:
        binance_chainlink_divergence = math.log(binance_price / cur_btc)

    return {
        # features
        "seconds_left": float(seconds_left),
        "time_held": time_held,
        "time_frac": time_frac,
        "current_bid": current_bid,
        "entry_price": entry_price,
        "bid_above_entry": current_bid - entry_price,
        "peak_bid": peak_bid,
        "peak_minus_current": peak_bid - current_bid,
        "unrealized_per_share": float(dec.get("unrealized") or 0.0)
        / max(float(pos.get("shares") or 1.0), 1.0),
        "bid_drift_3s": bid_drift_3s,
        "bid_drift_10s": bid_drift_10s,
        "own_spread": own_spread,
        "own_bid_size_log": safe_log1p(own_bid_size),
        "own_ask_size_log": safe_log1p(own_ask_size),
        "opp_spread": opp_spread,
        "book_imbalance": book_imbalance,
        "btc_ret_30s": float(btc.get("ret_30s") or 0.0),
        "btc_ret_60s": float(btc.get("ret_60s") or 0.0),
        "btc_ret_30m": float(btc.get("ret_30m") or 0.0),
        "sigma_5m": float(btc.get("sigma_5m") or 0.0),
        "btc_distance_from_entry": btc_distance_from_entry,
        "adverse_btc": float(ext.get("adverse_btc") or 0.0),
        "binance_chainlink_divergence": binance_chainlink_divergence,
        "entry_edge": float(pos.get("entry_edge") or 0.0),
        "entry_p_up": float(pos.get("entry_p_up") or 0.5),
        "entry_seconds_left": float(pos.get("entry_seconds_left") or 0),
        "direction_up": direction_up,
        # join keys / metadata (not features)
        "_cid": snap.get("condition_id", ""),
        "_dir": direction,
        "_entry_ts": float(ext.get("entry_ts") or 0.0),
        "_ts": float(snap.get("ts") or 0.0),
    }


def load_bundle(bundle_dir: Path) -> tuple[list[dict], list[dict]]:
    """Returns (manage_position_rows, position_close_events)."""
    manage_rows = []
    close_events = []
    bad = 0
    train_path = bundle_dir / "logs-training.jsonl"
    if train_path.exists():
        with open(train_path) as f:
            for line in f:
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    bad += 1
                    continue
                if d.get("context") == "manage_position":
                    manage_rows.append(d)
    events_path = bundle_dir / "logs-training-events.jsonl"
    if events_path.exists():
        with open(events_path) as f:
            for line in f:
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if e.get("event") in ("position_closed", "position_partial_close"):
                    close_events.append(e)
    if bad:
        print(f"  {bundle_dir.name}: skipped {bad} bad json lines")
    return manage_rows, close_events


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--bundles", default=DEFAULT_BUNDLE_GLOB,
        help="Glob (relative to repo root) of bundle directories.",
    )
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument(
        "--label-drop", type=float, default=LABEL_DROP,
        help="Positive label if eventual_exit_bid <= current_bid - this.",
    )
    ap.add_argument(
        "--repo-root",
        default=str(Path(__file__).resolve().parents[2]),
        help="Repo root (defaults to three levels up from this script).",
    )
    args = ap.parse_args()

    repo_root = Path(args.repo_root).resolve()
    bundles = sorted(Path(p) for p in glob.glob(str(repo_root / args.bundles)))
    print(f"repo_root={repo_root}")
    print(f"matched {len(bundles)} bundles:")
    for b in bundles:
        print(f"  {b.name}")

    rows = []
    total_manage = 0
    total_unmatched = 0
    bundle_id = 0
    for bundle in bundles:
        manage_rows, closes = load_bundle(bundle)
        total_manage += len(manage_rows)

        # Build close lookup keyed by (cid, dir) -> sorted by ts
        close_by_pos: dict[tuple[str, str], list[dict]] = defaultdict(list)
        for c in closes:
            close_by_pos[(c["condition_id"], c["direction"])].append(c)
        for v in close_by_pos.values():
            v.sort(key=lambda c: c["ts"])

        for snap in manage_rows:
            ext = snap.get("position_extras") or {}
            entry_ts = float(ext.get("entry_ts") or 0.0)
            cid = snap.get("condition_id", "")
            pos = snap.get("position") or {}
            direction = pos.get("direction")
            if not (cid and direction and entry_ts > 0):
                continue
            # Find first close on same (cid, dir) at ts >= entry_ts
            candidates = close_by_pos.get((cid, direction), [])
            close = None
            for c in candidates:
                if c["ts"] >= entry_ts:
                    close = c
                    break
            if close is None:
                total_unmatched += 1
                continue
            feat = feature_row(snap)
            if feat is None:
                continue
            cur_bid = feat["current_bid"]
            exit_price = float(close.get("exit_price") or 0.0)
            # Only label if exit happened AFTER this tick (not partial close already past)
            if close["ts"] < snap["ts"]:
                continue
            # Label: 1 if dumping at current_bid would have beaten the actual exit by >= label_drop
            label = 1 if (cur_bid - exit_price) >= args.label_drop else 0
            feat["label"] = label
            feat["_close_pnl"] = float(close.get("pnl") or 0.0)
            feat["_close_reason"] = close.get("reason", "")
            feat["_exit_price"] = exit_price
            feat["_bundle_id"] = bundle_id
            rows.append(feat)
        bundle_id += 1

    print(
        f"manage_position rows: {total_manage}; unmatched: {total_unmatched}; "
        f"feature rows: {len(rows)}"
    )
    if not rows:
        raise SystemExit("No rows produced.")

    df = pd.DataFrame(rows)
    pos_rate = df["label"].mean()
    print(f"label positive rate: {pos_rate:.3f}  (n={len(df)})")
    print("class distribution by reason:")
    print(df.groupby("_close_reason")["label"].agg(["count", "mean"]).round(3))

    out_path = repo_root / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_path)
    print(f"wrote {out_path}  rows={len(df)}  cols={len(df.columns)}")

    # Print per-bundle row counts for sanity
    print("rows per bundle_id:")
    print(df.groupby("_bundle_id").size())


if __name__ == "__main__":
    main()
