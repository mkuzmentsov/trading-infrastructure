"""Replay a bundle and report per-trade max profit / max loss + final PnL.

For each replay trade, walks post-entry snapshots of the same bar and tracks
the best and worst unrealized PnL the bot would have seen if it had tried to
sell at the bid of its side. "final" is the realized PnL from the replay
(hold-to-expiry for ml-entry).
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parents[1]
_BOT_DIR = Path(__file__).resolve().parents[3]
for _path in (str(_SCRIPTS_DIR), str(_BOT_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from backtest import apply_yaml_to_env, load_snapshots  # noqa: E402

_yaml_arg = next((a for a in sys.argv[1:] if not a.startswith("-")), None)
if _yaml_arg and Path(_yaml_arg).is_file():
    apply_yaml_to_env(_yaml_arg)

from bundle_backtest import BundleBacktestRunner  # noqa: E402


def _side_bid(snap: dict, direction: str) -> float:
    pm = snap.get("pm") or {}
    key = "up_bid" if direction == "UP" else "down_bid"
    return float(pm.get(key) or 0.0)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("yaml_path")
    parser.add_argument("log_dir")
    args = parser.parse_args()

    runner = BundleBacktestRunner(yaml_path=args.yaml_path)
    result = runner.run_direct_strategy(args.log_dir)

    snapshots = load_snapshots(args.log_dir)
    by_cid: dict[str, list[dict]] = defaultdict(list)
    for snap in snapshots:
        cid = str(snap.get("condition_id") or "")
        if cid:
            by_cid[cid].append(snap)
    for rows in by_cid.values():
        rows.sort(key=lambda s: float(s.get("ts") or 0.0))

    print(f"Replay total: {result.total_pnl:+.2f} USDC on {len(result.trades)} trades")
    print()
    header = (
        f"{'#':>2}  {'market_short':30s}  {'dir':>4s}  "
        f"{'entry':>5s}  {'shares':>6s}  {'max_bid':>7s}  {'min_bid':>7s}  "
        f"{'max_prof':>8s}  {'max_loss':>8s}  {'final':>7s}  outcome"
    )
    print(header)
    print("-" * len(header))

    totals = {"max_prof": 0.0, "max_loss": 0.0, "final": 0.0}
    for i, t in enumerate(result.trades, start=1):
        rows = by_cid.get(t.condition_id, [])
        post = [s for s in rows if float(s.get("ts") or 0.0) >= t.ts]
        bids = [b for b in (_side_bid(s, t.direction) for s in post) if b > 0]
        if not bids:
            bids = [t.entry_price]
        max_bid = max(bids)
        min_bid = min(bids)
        max_prof = (max_bid - t.entry_price) * t.shares
        max_loss = (min_bid - t.entry_price) * t.shares
        final = t.pnl
        totals["max_prof"] += max_prof
        totals["max_loss"] += max_loss
        totals["final"] += final

        short = (t.question[:30]) if t.question else t.condition_id[:10]
        print(
            f"{i:>2}  {short:30s}  {t.direction:>4s}  "
            f"{t.entry_price:>5.2f}  {t.shares:>6d}  {max_bid:>7.2f}  {min_bid:>7.2f}  "
            f"{max_prof:>+8.2f}  {max_loss:>+8.2f}  {final:>+7.2f}  {t.exit_reason}"
        )

    print("-" * len(header))
    print(
        f"                                                  totals:                         "
        f"{totals['max_prof']:>+8.2f}  {totals['max_loss']:>+8.2f}  {totals['final']:>+7.2f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
