#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path


NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")


@dataclass(frozen=True)
class Params:
    min_btc_distance: float
    min_book_divergence: float
    max_entry_price: float
    min_edge: float


@dataclass
class Result:
    pnl: float = 0.0
    trades: int = 0
    wins: int = 0
    losses: int = 0

    def add_trade(self, pnl: float, won: bool) -> None:
        self.pnl += pnl
        self.trades += 1
        self.wins += int(won)
        self.losses += int(not won)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Replay BTC bot entry filters over pm-btc-logs_* bundles with resolution-style settlement."
    )
    parser.add_argument(
        "path",
        help="Directory containing pm-btc-logs_* bundles, or a single bundle directory.",
    )
    parser.add_argument("--min-btc-distance", default="0.0004,0.00035,0.0003,0.00025,0.0002")
    parser.add_argument("--min-book-divergence", default="0.04,0.035,0.03")
    parser.add_argument("--max-entry-price", default="0.60,0.55,0.50")
    parser.add_argument("--min-edge", default="0.04,0.045,0.05")
    parser.add_argument("--max-entry-spread", type=float, default=0.04)
    parser.add_argument("--min-entry-price", type=float, default=0.05)
    parser.add_argument("--top", type=int, default=12, help="Number of ranked parameter sets to print")
    parser.add_argument(
        "--show-bundles",
        action="store_true",
        help="Show per-bundle breakdown for ranked rows",
    )
    return parser.parse_args()


def parse_float_list(raw: str) -> list[float]:
    return [float(part.strip()) for part in raw.split(",") if part.strip()]


def to_number(value: object, default: float | None = None) -> float | None:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        match = NUMBER_RE.search(value)
        if match:
            return float(match.group(0))
    return default


def resolve_bundles(path_arg: str) -> list[Path]:
    root = Path(path_arg)
    if root.name.startswith("pm-btc-logs_") and root.is_dir():
        return [root]
    bundles = sorted(path for path in root.iterdir() if path.is_dir() and path.name.startswith("pm-btc-logs_"))
    if not bundles:
        raise FileNotFoundError(f"No pm-btc-logs_* bundles found under {root}")
    return bundles


def load_outcomes(bundle: Path) -> dict[str, str]:
    path = bundle / "logs-training.jsonl"
    last_by_market: dict[str, dict] = {}
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            market = (
                record.get("market")
                or record.get("market_slug")
                or record.get("market_name")
                or record.get("question")
                or record.get("condition_id")
            )
            if market:
                last_by_market[str(market)] = record

    outcomes: dict[str, str] = {}
    for market, record in last_by_market.items():
        btc = record.get("btc") or {}
        bar_open = to_number(record.get("bar_open"), to_number(btc.get("bar_open")))
        current_price = to_number(record.get("current_price"), to_number(btc.get("current_price")))
        if bar_open is None or current_price is None:
            continue
        if current_price > bar_open:
            outcomes[market] = "UP"
        elif current_price < bar_open:
            outcomes[market] = "DOWN"
    return outcomes


def infer_btc_distance(record: dict) -> float | None:
    signal = record.get("signal") or {}
    debug = signal.get("debug") or {}
    btc = record.get("btc") or {}
    btc_distance = to_number(record.get("btc_distance"), to_number(debug.get("btc_distance")))
    if btc_distance is not None:
        return abs(btc_distance)
    bar_open = to_number(record.get("bar_open"), to_number(btc.get("bar_open")))
    current_price = to_number(record.get("current_price"), to_number(btc.get("current_price")))
    if bar_open and current_price and bar_open > 0 and current_price > 0:
        return abs(math.log(current_price / bar_open))
    return None


def infer_book_divergence(record: dict, action: str, price: float) -> float | None:
    signal = record.get("signal") or {}
    debug = signal.get("debug") or {}
    book_divergence = to_number(record.get("book_divergence"), to_number(debug.get("book_divergence")))
    if book_divergence is not None:
        return book_divergence
    p_up = to_number(signal.get("p_up"))
    if p_up is None:
        return None
    return (p_up - price) if action == "BUY_UP" else ((1.0 - p_up) - price)


def evaluate_bundle(bundle: Path, params: Params, max_entry_spread: float, min_entry_price: float) -> Result:
    path = bundle / "logs-training.jsonl"
    outcomes = load_outcomes(bundle)
    result = Result()
    seen_markets: set[str] = set()

    if not path.is_file():
        return result

    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue

            market = (
                record.get("market")
                or record.get("market_slug")
                or record.get("market_name")
                or record.get("question")
                or record.get("condition_id")
            )
            if not market or market in seen_markets or market not in outcomes:
                continue

            signal = record.get("signal") or {}
            action = signal.get("action")
            if action not in ("BUY_UP", "BUY_DOWN"):
                continue

            price = to_number(signal.get("price"))
            size = to_number(signal.get("size"))
            edge = to_number(signal.get("edge"))
            if None in (price, size, edge):
                continue
            if price < min_entry_price or price > params.max_entry_price:
                continue
            if edge < params.min_edge:
                continue

            debug = signal.get("debug") or {}
            spread = to_number(record.get("chosen_spread"))
            if spread is None:
                if action == "BUY_UP":
                    spread = to_number(debug.get("spread_up"), 0.0)
                else:
                    spread = to_number(debug.get("spread_down"), 0.0)
            if spread is not None and spread > max_entry_spread:
                continue

            btc_distance = infer_btc_distance(record)
            if btc_distance is None or btc_distance < params.min_btc_distance:
                continue

            book_divergence = infer_book_divergence(record, action, price)
            if book_divergence is None or book_divergence < params.min_book_divergence:
                continue

            shares = int(size)
            if shares <= 0:
                continue

            winner = outcomes[market]
            won = (winner == "UP" and action == "BUY_UP") or (winner == "DOWN" and action == "BUY_DOWN")
            pnl = shares * (1.0 - price) if won else -shares * price
            result.add_trade(pnl, won)
            seen_markets.add(str(market))

    return result


def main() -> None:
    args = parse_args()
    bundles = resolve_bundles(args.path)

    grid = [
        Params(min_btc_distance, min_book_divergence, max_entry_price, min_edge)
        for min_btc_distance in parse_float_list(args.min_btc_distance)
        for min_book_divergence in parse_float_list(args.min_book_divergence)
        for max_entry_price in parse_float_list(args.max_entry_price)
        for min_edge in parse_float_list(args.min_edge)
    ]

    ranked: list[tuple[Result, Params, dict[str, Result]]] = []
    for params in grid:
        total = Result()
        per_bundle: dict[str, Result] = {}
        for bundle in bundles:
            bundle_result = evaluate_bundle(
                bundle=bundle,
                params=params,
                max_entry_spread=args.max_entry_spread,
                min_entry_price=args.min_entry_price,
            )
            per_bundle[bundle.name] = bundle_result
            total.pnl += bundle_result.pnl
            total.trades += bundle_result.trades
            total.wins += bundle_result.wins
            total.losses += bundle_result.losses
        ranked.append((total, params, per_bundle))

    ranked.sort(
        key=lambda row: (
            round(row[0].pnl, 8),
            row[0].wins - row[0].losses,
            -row[0].trades,
            row[1].min_btc_distance,
            row[1].min_book_divergence,
            -row[1].max_entry_price,
            row[1].min_edge,
        ),
        reverse=True,
    )

    print(f"bundles: {[bundle.name for bundle in bundles]}")
    print("note: replay uses first eligible entry per market and settles at bar outcome; it is not a full exit-path simulation.")

    for index, (total, params, per_bundle) in enumerate(ranked[: args.top], start=1):
        print(
            f"\n#{index} pnl={total.pnl:.2f} trades={total.trades} wins={total.wins} losses={total.losses} "
            f"minBtcDistance={params.min_btc_distance:.5f} minBookDivergence={params.min_book_divergence:.3f} "
            f"maxEntryPrice={params.max_entry_price:.2f} minEdge={params.min_edge:.3f}"
        )
        if args.show_bundles:
            for bundle_name in sorted(per_bundle):
                bundle_result = per_bundle[bundle_name]
                print(
                    f"  {bundle_name}: pnl={bundle_result.pnl:.2f} trades={bundle_result.trades} "
                    f"wins={bundle_result.wins} losses={bundle_result.losses}"
                )


if __name__ == "__main__":
    main()
