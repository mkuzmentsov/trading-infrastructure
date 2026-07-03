from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from math_signal import Signal
from positions import Position


@dataclass
class StrategyContext:
    cash_amount: float
    seconds_left: int
    bar_open: float
    current_price: float
    ret_30s: float
    ret_60s: float
    ret_30m: float
    sigma_5m: float
    up_bid: float
    up_ask: float
    up_bid_size: float
    up_ask_size: float
    down_bid: float
    down_ask: float
    down_bid_size: float
    down_ask_size: float
    book_events: int
    feed_price_age: float
    feed_up_age: float
    feed_down_age: float
    binance_price: float
    binance_age: float
    ml_p_up: float | None
    # Optional — populated by replays/live for strategies that need the raw
    # snapshot dict or an in-bar history window (e.g. v2 velocity features).
    condition_id: str = ""
    ts: float = 0.0
    raw_snapshot: dict[str, Any] = field(default_factory=dict)
    prior_snapshots: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class PositionDecision:
    signal: Signal | None = None
    current_side_edge: float = 0.0
    exit_reason: str = ""
    action: str = ""


class Strategy(Protocol):
    name: str

    def startup_details(self) -> list[str]:
        ...

    def entry_order_mode(self) -> str:
        ...

    def entry_hold_to_expiry(self) -> bool:
        ...

    def evaluate_entry(self, ctx: StrategyContext) -> Signal:
        ...

    def evaluate_position(self, ctx: StrategyContext, pos: Position, current_bid: float, now: float) -> PositionDecision:
        ...
