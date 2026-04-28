"""Replay entry model on a held-out bundle.

For each `position_opened` event, score with the trained model and compare
"keep all trades" (baseline = what the bot actually did) vs "gate at thr X".
PnL comes from the matched `position_closed` event.

Usage:
    python3 ai/pm_btc_entry/replay_entry_model.py BUNDLE_PATH [--thresholds 0.4,0.5,0.55]
"""
from __future__ import annotations

import argparse
from pathlib import Path

import lightgbm as lgb
import pandas as pd

from prepare_entry_dataset import FEATURE_COLUMNS, feature_row, load_bundle, nearest_preceding_snap

DEFAULT_MODEL = "polymarket/k8s/helm/polymarket-btc-bot/files/model/pm_btc_entry_smart_model.txt"


def build_rows(bundle_dir: Path) -> pd.DataFrame:
    try_enter, opens, closes = load_bundle(bundle_dir)
    close_by_pos: dict = {}
    for c in closes:
        key = (c["condition_id"], c["direction"])
        close_by_pos.setdefault(key, []).append(c)
    for v in close_by_pos.values():
        v.sort(key=lambda c: c["ts"])

    rows = []
    for op in opens:
        cid = op["condition_id"]; direction = op["direction"]
        ts = float(op.get("ts") or 0.0)
        close = None
        for c in close_by_pos.get((cid, direction), []):
            if c["ts"] >= ts:
                close = c; break
        if close is None:
            continue
        ctx = nearest_preceding_snap(try_enter.get(cid, []), ts)
        row = feature_row(op, ctx)
        row["pnl"] = float(close.get("pnl") or 0.0)
        row["_close_reason"] = close.get("reason", "")
        row["_entry_price"] = float(op.get("entry_price") or 0.0)
        row["_entry_edge"] = float(op.get("entry_edge") or 0.0)
        rows.append(row)
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("bundle", help="Path to bundle directory.")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--thresholds", default="0.30,0.40,0.45,0.50,0.55,0.60,0.65,0.70")
    ap.add_argument(
        "--repo-root", default=str(Path(__file__).resolve().parents[2]),
    )
    args = ap.parse_args()

    repo_root = Path(args.repo_root).resolve()
    bundle_path = Path(args.bundle)
    if not bundle_path.is_absolute():
        bundle_path = repo_root / bundle_path
    print(f"bundle: {bundle_path.name}")

    df = build_rows(bundle_path)
    if df.empty:
        raise SystemExit("No matched entries found in bundle.")
    n = len(df)
    actual_pnl = df["pnl"].sum()
    actual_wr = (df["pnl"] > 0).mean()
    print(f"\nactual: n={n}  pnl=${actual_pnl:.2f}  WR={actual_wr:.2%}  "
          f"avg=${actual_pnl/n:.2f}")
    print("by close reason:")
    print(df.groupby("_close_reason").agg(
        n=("pnl", "size"),
        wr=("pnl", lambda s: (s > 0).mean()),
        total_pnl=("pnl", "sum"),
        avg_pnl=("pnl", "mean"),
    ).round(3).sort_values("n", ascending=False))

    booster = lgb.Booster(model_file=str(repo_root / args.model))
    X = df[FEATURE_COLUMNS].astype(float).values
    df["_p"] = booster.predict(X)

    print(f"\nmodel score distribution: "
          f"min={df['_p'].min():.3f} median={df['_p'].median():.3f} "
          f"mean={df['_p'].mean():.3f} max={df['_p'].max():.3f}")

    thresholds = [float(t) for t in args.thresholds.split(",")]
    print("\nthreshold sweep:")
    print(f"{'thr':>5} {'kept':>5} {'frac':>5} {'WR':>5} "
          f"{'kept_pnl':>9} {'skip_pnl':>9} {'avg':>6} {'delta':>7}")
    for thr in thresholds:
        keep = df["_p"] >= thr
        n_kept = int(keep.sum())
        kept_pnl = float(df.loc[keep, "pnl"].sum())
        skip_pnl = float(df.loc[~keep, "pnl"].sum())
        wr = float((df.loc[keep, "pnl"] > 0).mean()) if n_kept else float("nan")
        avg = kept_pnl / n_kept if n_kept else float("nan")
        delta = kept_pnl - actual_pnl
        print(f"{thr:>5.2f} {n_kept:>5d} {n_kept/n:>5.2f} {wr:>5.2f} "
              f"{kept_pnl:>9.2f} {skip_pnl:>9.2f} {avg:>6.2f} {delta:>+7.2f}")

    print("\nSkipped trades (would-be losers caught at thr=0.50):")
    skipped = df[df["_p"] < 0.50].sort_values("pnl")
    if len(skipped):
        print(skipped[["_dir", "_entry_price", "_entry_edge", "_p", "pnl",
                       "_close_reason"]].head(20).to_string(index=False))
    print("\nKept trades that lost (model false positives at thr=0.50):")
    fp = df[(df["_p"] >= 0.50) & (df["pnl"] < 0)].sort_values("pnl")
    if len(fp):
        print(fp[["_dir", "_entry_price", "_entry_edge", "_p", "pnl",
                  "_close_reason"]].head(20).to_string(index=False))


if __name__ == "__main__":
    main()
