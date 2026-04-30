from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parents[1]
_BOT_DIR = Path(__file__).resolve().parents[3]
for _path in (str(_SCRIPTS_DIR), str(_BOT_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

# Export YAML → env BEFORE strategies/config/math_signal are imported, so
# their module-level env reads (MIN_EDGE, TAKE_PROFIT, etc.) pick up the
# replay config instead of whatever env the shell had.
from backtest import apply_yaml_to_env  # noqa: E402

_yaml_arg = next((a for a in sys.argv[1:] if not a.startswith("-")), None)
if _yaml_arg and Path(_yaml_arg).is_file():
    apply_yaml_to_env(_yaml_arg)

from bundle_backtest import (  # noqa: E402
    BundleBacktestRunner,
    _build_market_timeline,
    _iter_jsonl,
    _next_market_close_from_timeline,
    _resolve_events_path,
)


def _is_external_position_close(event: dict) -> bool:
    if event.get("tracked_position") is False:
        return True
    if event.get("market_start_ts") is None and "redemption" in str(event.get("reason", "")):
        return True
    return False


def _load_actual_rows(log_dir: str, ignore_external_positions: bool = True) -> list[dict]:
    events_path = _resolve_events_path(log_dir)
    timeline = _build_market_timeline(log_dir)
    closes_by_cid: dict[str, dict] = {}
    opens: list[dict] = []

    for event in _iter_jsonl(events_path):
        if event.get("event") == "position_opened":
            opens.append(event)
        elif event.get("event") == "position_closed":
            if ignore_external_positions and _is_external_position_close(event):
                continue
            cid = str(event.get("condition_id", ""))
            if cid:
                prev = closes_by_cid.get(cid)
                if prev is None or float(event.get("ts", 0.0)) > float(prev.get("ts", 0.0)):
                    closes_by_cid[cid] = event

    rows: list[dict] = []
    for event in sorted(opens, key=lambda item: float(item.get("ts", 0.0))):
        cid = str(event.get("condition_id", ""))
        if not cid:
            continue
        market_start_ts = int(event.get("market_start_ts") or 0)
        market_end_ts = int(event.get("market_end_ts") or 0)
        bar_open = float(event.get("bar_open") or 0.0)
        close_event = closes_by_cid.get(cid)

        if close_event is not None:
            close_price = float(close_event.get("exit_price") or 0.0)
            actual_pnl = float(close_event.get("pnl", 0.0) or 0.0)
            actual_close_ts = float(close_event.get("ts", 0.0))
            actual_note = "closed_event"
        else:
            close_price, next_point = _next_market_close_from_timeline(timeline, market_start_ts)
            if close_price is None or next_point is None or bar_open <= 0:
                actual_pnl = None
                actual_close_ts = 0.0
                actual_note = "incomplete_bundle"
            else:
                direction = str(event.get("direction", ""))
                entry = float(event.get("entry_price", 0.0) or 0.0)
                shares = float(event.get("shares", 0.0) or 0.0)
                won = (direction == "UP" and close_price >= bar_open) or (direction == "DOWN" and close_price < bar_open)
                actual_pnl = ((1.0 if won else 0.0) - entry) * shares
                actual_close_ts = float(next_point["market_start_ts"])
                actual_note = "hold_to_expiry"

        rows.append(
            {
                "condition_id": cid,
                "question": str(event.get("question", "")),
                "market_start_ts": market_start_ts,
                "market_end_ts": market_end_ts,
                "btc_open": bar_open,
                "btc_close": close_price if close_event is not None else (close_price if close_price is not None else None),
                "direction": str(event.get("direction", "")),
                "entry_price": float(event.get("entry_price", 0.0) or 0.0),
                "shares": int(event.get("shares", 0) or 0),
                "actual_pnl": actual_pnl,
                "actual_close_ts": actual_close_ts,
                "actual_note": actual_note,
            }
        )
    return rows


def _build_market_lookup(log_dir: str) -> dict[str, dict]:
    timeline = _build_market_timeline(log_dir)
    return {str(point["condition_id"]): point for point in timeline if point.get("condition_id")}


def _fmt(value: object, ndigits: int = 2) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.{ndigits}f}"
    return str(value)


def _render_ascii_chart(
    points: list[tuple[float, float]],
    *,
    height: int = 16,
    width: int = 72,
    start_balance: float = 100.0,
) -> str:
    """Render a cumulative balance curve as ASCII.

    points: list of (ts, balance) pairs ordered by ts.
    """
    if not points:
        return "(no trades)"

    balances = [p[1] for p in points]
    lo = min(start_balance, min(balances))
    hi = max(start_balance, max(balances))
    if hi - lo < 1e-6:
        hi = lo + 1.0

    n = len(points)
    cols = min(width, max(n, 10))
    grid = [[" "] * cols for _ in range(height)]

    # Sample balances across cols (nearest point)
    sampled: list[float] = []
    for c in range(cols):
        idx = int(round(c * (n - 1) / max(cols - 1, 1))) if n > 1 else 0
        sampled.append(balances[idx])

    def _row_for(val: float) -> int:
        frac = (val - lo) / (hi - lo)
        row = int(round((1.0 - frac) * (height - 1)))
        return max(0, min(height - 1, row))

    # Zero-baseline (starting balance) reference row
    base_row = _row_for(start_balance)
    for c in range(cols):
        grid[base_row][c] = "·"

    for c, val in enumerate(sampled):
        r = _row_for(val)
        grid[r][c] = "█" if val >= start_balance else "▒"

    lines: list[str] = []
    for r in range(height):
        prefix = ""
        if r == 0:
            prefix = f"{hi:7.2f} │"
        elif r == height - 1:
            prefix = f"{lo:7.2f} │"
        elif r == base_row:
            prefix = f"{start_balance:7.2f} ┤"
        else:
            prefix = "        │"
        lines.append(prefix + "".join(grid[r]))

    ts_start = points[0][0]
    ts_end = points[-1][0]
    t0 = datetime.fromtimestamp(ts_start, timezone.utc).strftime("%m-%d %H:%M")
    t1 = datetime.fromtimestamp(ts_end, timezone.utc).strftime("%m-%d %H:%M")
    footer = "        └" + "─" * cols
    label = f"         {t0}" + " " * max(1, cols - len(t0) - len(t1)) + t1
    lines.append(footer)
    lines.append(label)
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay vs actual report for a PM BTC bundle")
    parser.add_argument("yaml_path", help="Strategy YAML path, e.g. pm_btc_3.yaml")
    parser.add_argument("log_dir", help="Bundle directory, e.g. pm-btc-logs_pm-btc-3_20260419_101700")
    parser.add_argument("--ignore-external-positions", action="store_true", default=True)
    args = parser.parse_args()

    runner = BundleBacktestRunner(args.yaml_path)
    result = runner.run_direct_strategy(args.log_dir)
    replay_by_cid = {t.condition_id: t for t in result.trades}
    actual_rows = _load_actual_rows(args.log_dir, ignore_external_positions=args.ignore_external_positions)
    market_lookup = _build_market_lookup(args.log_dir)
    timeline = _build_market_timeline(args.log_dir)

    matched = 0
    actual_total = 0.0
    for row in actual_rows:
        if row["actual_pnl"] is not None:
            actual_total += float(row["actual_pnl"])
        if row["condition_id"] in replay_by_cid:
            matched += 1

    print(f"Replay total: {result.total_pnl:.2f} USDC on {len(result.trades)} trades")
    print(f"Actual total: {actual_total:.2f} USDC on {len(actual_rows)} markets")
    print(f"Matched markets: {matched}")
    print()
    print(
        "Replay Market | BTC Open | BTC Close | Outcome | Replay Dir | Replay Entry | Replay Shares | Replay PnL | Real PnL | Actual Dir | Actual Entry | Actual PnL | Actual Note"
    )
    actual_by_cid = {row["condition_id"]: row for row in actual_rows}
    for t in result.trades:
        market = market_lookup.get(t.condition_id, {})
        market_open = float(market.get("bar_open") or 0.0)
        next_close, _ = _next_market_close_from_timeline(timeline, int(market.get("market_start_ts") or 0))
        market_outcome = "UP" if (next_close is not None and market_open > 0 and next_close >= market_open) else ("DOWN" if next_close is not None else "incomplete_bundle")
        real_pnl = None
        if next_close is not None and market_open > 0:
            real_pnl = ((1.0 if market_outcome == t.direction else 0.0) - t.entry_price) * t.shares
        actual_row = actual_by_cid.get(t.condition_id)
        actual_dir = actual_row["direction"] if actual_row else "-"
        actual_entry = actual_row["entry_price"] if actual_row else None
        actual_pnl = actual_row["actual_pnl"] if actual_row else None
        actual_note = actual_row["actual_note"] if actual_row else "replay_only"
        print(
            " | ".join(
                [
                    t.question,
                    _fmt(market_open),
                    _fmt(next_close),
                    market_outcome,
                    t.direction,
                    _fmt(t.entry_price),
                    _fmt(t.shares, 0),
                    _fmt(t.pnl),
                    _fmt(real_pnl),
                    actual_dir,
                    _fmt(actual_entry),
                    _fmt(actual_pnl),
                    actual_note,
                ]
            )
        )

    actual_only = [row for row in actual_rows if row["condition_id"] not in replay_by_cid]
    if actual_only:
        print()
        print("Actual-only markets:")
        for row in actual_only:
            print(f"{row['question']} | {row['direction']} @ {row['entry_price']:.2f} | pnl={_fmt(row['actual_pnl'])} | {row['actual_note']}")

    # ── Summary + cumulative-balance curve ────────────────────────────────────
    trades_sorted = sorted(result.trades, key=lambda t: float(getattr(t, "ts", 0.0) or 0.0))
    START_BALANCE = 100.0
    balance = START_BALANCE
    curve: list[tuple[float, float]] = []
    wins = 0
    for t in trades_sorted:
        balance += float(t.pnl)
        curve.append((float(getattr(t, "ts", 0.0) or 0.0), balance))
        if t.pnl > 0:
            wins += 1

    if trades_sorted:
        ts_start = float(getattr(trades_sorted[0], "ts", 0.0) or 0.0)
        ts_end = float(getattr(trades_sorted[-1], "ts", 0.0) or 0.0)
        span_secs = max(ts_end - ts_start, 1.0)
        span_hrs = span_secs / 3600.0
        trades_per_hr = len(trades_sorted) / span_hrs
        trades_per_day = trades_per_hr * 24.0
        wr = wins / len(trades_sorted)
        pnl_per_day = (balance - START_BALANCE) * (86400.0 / span_secs)

        print()
        print("─" * 80)
        print(
            f"Summary: {len(trades_sorted)} trades over {span_hrs:.1f}h "
            f"({trades_per_hr:.2f}/hr, {trades_per_day:.1f}/day)  "
            f"WR={wr:.1%}  PnL={balance - START_BALANCE:+.2f} USDC  "
            f"~${pnl_per_day:+.1f}/day"
        )
        print(f"Final balance: ${balance:.2f}  (start ${START_BALANCE:.2f})")
        print()
        print("Cumulative PnL:")
        print(_render_ascii_chart(curve, start_balance=START_BALANCE))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
