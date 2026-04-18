from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

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
