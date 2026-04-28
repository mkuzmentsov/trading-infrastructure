"""Build entry-classifier dataset from position_opened/closed events.

Walks all pm-btc-smart training bundles. For each `position_opened` event,
joins to its eventual `position_closed` by (condition_id, direction, ts>=open_ts)
and joins to the nearest preceding `try_enter` snapshot for context features
that aren't carried in the open event (regime/session_pnl, ret_30m, sigma_5m).

Label: 1 iff close pnl > LABEL_PNL (default 0).

Usage:
    python3 prepare_entry_dataset.py [--out PATH] [--bundles GLOB] [--label-pnl 0]
"""
from __future__ import annotations

import argparse
import bisect
import glob
import json
import math
from collections import defaultdict
from pathlib import Path

import pandas as pd

DEFAULT_BUNDLE_GLOB = (
    "polymarket/k8s/helm/polymarket-btc-bot/pm-btc-logs_pm-btc-smart_*"
)
DEFAULT_OUT = "ai/pm_btc_entry/entry_dataset_v1.parquet"
LABEL_PNL = 0.0

FEATURE_COLUMNS = [
    # entry-time signal
    "entry_edge", "entry_p_up", "entry_price", "entry_seconds_left",
    "direction_up", "time_frac",
    # PM book at entry (relative to direction)
    "own_bid", "own_ask", "own_spread",
    "own_bid_size_log", "own_ask_size_log",
    "opp_bid", "opp_spread",
    "book_imbalance", "implied_p_own",
    # BTC state at entry (from try_enter context)
    "btc_ret_30s", "btc_ret_60s", "btc_ret_30m", "sigma_5m",
    "btc_distance_from_open", "binance_chainlink_divergence",
    # Move alignment: does our bet fight or follow recent BTC drift?
    "ret30s_align", "ret60s_align", "ret30m_align",
    # Session regime at entry
    "session_pnl", "closes_30min", "pnl_30min", "wr_30min_filled",
    "wr_30min_known",
]


def safe_log1p(x):
    try:
        return math.log1p(max(0.0, float(x)))
    except (TypeError, ValueError):
        return 0.0


def signed_log_return(num, den):
    try:
        n = float(num); d = float(den)
        if n > 0 and d > 0:
            return math.log(n / d)
    except (TypeError, ValueError):
        pass
    return 0.0


def feature_row(open_evt: dict, ctx_snap: dict | None) -> dict:
    direction = open_evt["direction"]
    direction_up = 1.0 if direction == "UP" else 0.0
    direction_sign = 1.0 if direction == "UP" else -1.0

    entry_price = float(open_evt.get("entry_price") or 0.0)
    entry_edge = float(open_evt.get("entry_edge") or 0.0)
    entry_p_up = float(open_evt.get("entry_p_up") or 0.5)
    entry_seconds_left = float(open_evt.get("entry_seconds_left") or 0.0)
    bar_total = max(
        float(open_evt.get("market_end_ts", 0)) - float(open_evt.get("market_start_ts", 0)),
        1.0,
    )
    time_frac = max(0.0, min(1.0, 1.0 - entry_seconds_left / bar_total))

    if direction == "UP":
        own_bid = float(open_evt.get("up_bid") or 0)
        own_ask = float(open_evt.get("up_ask") or 0)
        own_bid_size = float(open_evt.get("up_bid_size") or 0)
        own_ask_size = float(open_evt.get("up_ask_size") or 0)
        opp_bid = float(open_evt.get("down_bid") or 0)
        opp_ask = float(open_evt.get("down_ask") or 0)
    else:
        own_bid = float(open_evt.get("down_bid") or 0)
        own_ask = float(open_evt.get("down_ask") or 0)
        own_bid_size = float(open_evt.get("down_bid_size") or 0)
        own_ask_size = float(open_evt.get("down_ask_size") or 0)
        opp_bid = float(open_evt.get("up_bid") or 0)
        opp_ask = float(open_evt.get("up_ask") or 0)

    own_spread = max(0.0, own_ask - own_bid)
    opp_spread = max(0.0, opp_ask - opp_bid)
    total_size = own_bid_size + own_ask_size
    book_imbalance = (own_bid_size - own_ask_size) / total_size if total_size > 0 else 0.0
    own_mid = 0.5 * (own_bid + own_ask)
    opp_mid = 0.5 * (opp_bid + opp_ask)
    total_mid = own_mid + opp_mid
    implied_p_own = own_mid / total_mid if total_mid > 0 else 0.5

    bar_open = float(open_evt.get("bar_open") or 0.0)
    btc_price = float(open_evt.get("btc_price") or 0.0)
    btc_distance_from_open = signed_log_return(btc_price, bar_open)

    btc = (ctx_snap or {}).get("btc") or {}
    ret_30s = float(btc.get("ret_30s") or 0.0)
    ret_60s = float(btc.get("ret_60s") or 0.0)
    ret_30m = float(btc.get("ret_30m") or 0.0)
    sigma_5m = float(btc.get("sigma_5m") or 0.0)
    binance_price = float(btc.get("binance_price") or 0.0)
    cl_price = float(btc.get("current_price") or btc_price)
    binance_chainlink_divergence = signed_log_return(binance_price, cl_price)

    regime = (ctx_snap or {}).get("regime") or {}
    session_pnl = float(regime.get("session_pnl") or 0.0)
    closes_30min = float(regime.get("closes_30min") or 0.0)
    pnl_30min = float(regime.get("pnl_30min") or 0.0)
    wr30 = regime.get("wr_30min")
    wr_30min_known = 1.0 if wr30 is not None else 0.0
    wr_30min_filled = float(wr30) if wr30 is not None else 0.5

    return {
        "entry_edge": entry_edge,
        "entry_p_up": entry_p_up,
        "entry_price": entry_price,
        "entry_seconds_left": entry_seconds_left,
        "direction_up": direction_up,
        "time_frac": time_frac,
        "own_bid": own_bid,
        "own_ask": own_ask,
        "own_spread": own_spread,
        "own_bid_size_log": safe_log1p(own_bid_size),
        "own_ask_size_log": safe_log1p(own_ask_size),
        "opp_bid": opp_bid,
        "opp_spread": opp_spread,
        "book_imbalance": book_imbalance,
        "implied_p_own": implied_p_own,
        "btc_ret_30s": ret_30s,
        "btc_ret_60s": ret_60s,
        "btc_ret_30m": ret_30m,
        "sigma_5m": sigma_5m,
        "btc_distance_from_open": btc_distance_from_open,
        "binance_chainlink_divergence": binance_chainlink_divergence,
        "ret30s_align": ret_30s * direction_sign,
        "ret60s_align": ret_60s * direction_sign,
        "ret30m_align": ret_30m * direction_sign,
        "session_pnl": session_pnl,
        "closes_30min": closes_30min,
        "pnl_30min": pnl_30min,
        "wr_30min_filled": wr_30min_filled,
        "wr_30min_known": wr_30min_known,
        # metadata
        "_cid": open_evt.get("condition_id", ""),
        "_dir": direction,
        "_ts": float(open_evt.get("ts") or 0.0),
    }


def load_bundle(bundle_dir: Path):
    """Returns (try_enter_by_cid: dict[cid -> sorted list of (ts, snap)],
               opens: list, closes: list)."""
    try_enter_by_cid: dict[str, list] = defaultdict(list)
    opens, closes = [], []
    train_path = bundle_dir / "logs-training.jsonl"
    bad = 0
    if train_path.exists():
        with open(train_path) as f:
            for line in f:
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    bad += 1
                    continue
                if d.get("context") == "try_enter":
                    cid = d.get("condition_id")
                    ts = d.get("ts")
                    if cid and ts is not None:
                        try_enter_by_cid[cid].append((float(ts), d))
    for v in try_enter_by_cid.values():
        v.sort(key=lambda x: x[0])
    events_path = bundle_dir / "logs-training-events.jsonl"
    if events_path.exists():
        with open(events_path) as f:
            for line in f:
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ev = e.get("event")
                if ev == "position_opened":
                    opens.append(e)
                elif ev == "position_closed":
                    closes.append(e)
    if bad:
        print(f"  {bundle_dir.name}: skipped {bad} bad json lines")
    return try_enter_by_cid, opens, closes


def nearest_preceding_snap(snaps: list, ts: float) -> dict | None:
    """Binary search snaps (sorted by ts) for the latest one with ts <= target."""
    if not snaps:
        return None
    keys = [s[0] for s in snaps]
    idx = bisect.bisect_right(keys, ts) - 1
    if idx < 0:
        return snaps[0][1]  # fall back to first
    return snaps[idx][1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundles", default=DEFAULT_BUNDLE_GLOB)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--label-pnl", type=float, default=LABEL_PNL,
                    help="Positive label if close pnl > this.")
    ap.add_argument(
        "--repo-root",
        default=str(Path(__file__).resolve().parents[2]),
    )
    args = ap.parse_args()

    repo_root = Path(args.repo_root).resolve()
    bundles = sorted(Path(p) for p in glob.glob(str(repo_root / args.bundles)))
    print(f"repo_root={repo_root}")
    print(f"matched {len(bundles)} bundles:")
    for b in bundles:
        print(f"  {b.name}")

    rows = []
    n_open = n_unmatched_close = n_no_ctx = 0
    for bundle_id, bundle in enumerate(bundles):
        try_enter, opens, closes = load_bundle(bundle)
        # Build close lookup keyed by (cid, dir) sorted by ts
        close_by_pos: dict[tuple, list] = defaultdict(list)
        for c in closes:
            close_by_pos[(c["condition_id"], c["direction"])].append(c)
        for v in close_by_pos.values():
            v.sort(key=lambda c: c["ts"])

        for op in opens:
            n_open += 1
            cid = op.get("condition_id")
            direction = op.get("direction")
            ts = float(op.get("ts") or 0.0)
            # Find first close on same (cid, dir) at ts >= open_ts
            close = None
            for c in close_by_pos.get((cid, direction), []):
                if c["ts"] >= ts:
                    close = c
                    break
            if close is None:
                n_unmatched_close += 1
                continue
            ctx = nearest_preceding_snap(try_enter.get(cid, []), ts)
            if ctx is None:
                n_no_ctx += 1
            row = feature_row(op, ctx)
            row["pnl"] = float(close.get("pnl") or 0.0)
            row["label"] = 1 if row["pnl"] > args.label_pnl else 0
            row["_close_reason"] = close.get("reason", "")
            row["_bundle_id"] = bundle_id
            row["_bundle_name"] = bundle.name
            rows.append(row)

    print(f"\nopens: {n_open}; unmatched-close: {n_unmatched_close}; "
          f"no-context: {n_no_ctx}; rows: {len(rows)}")
    if not rows:
        raise SystemExit("No rows produced.")

    df = pd.DataFrame(rows)
    pos_rate = df["label"].mean()
    print(f"label positive rate: {pos_rate:.3f}  (n={len(df)})  "
          f"mean pnl={df['pnl'].mean():.2f}  total pnl={df['pnl'].sum():.2f}")
    print("\nlabel distribution by close reason:")
    print(df.groupby("_close_reason").agg(
        n=("label", "size"),
        win_rate=("label", "mean"),
        avg_pnl=("pnl", "mean"),
        total_pnl=("pnl", "sum"),
    ).round(3).sort_values("n", ascending=False))
    print("\nrows per bundle:")
    print(df.groupby("_bundle_name").agg(
        n=("label", "size"),
        win_rate=("label", "mean"),
        total_pnl=("pnl", "sum"),
    ).round(3))

    out_path = repo_root / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_path)
    print(f"\nwrote {out_path}  rows={len(df)}  cols={len(df.columns)}")


if __name__ == "__main__":
    main()
