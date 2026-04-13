"""
In-memory position and open sell-order state.

A "position" is a bought YES/NO token we haven't yet exited.
A "sell order" is a limit GTC order placed to exit the position.
A "pending buy" is a GTC limit buy order that hasn't been confirmed filled yet.

Only one position is tracked at a time (one active market).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Position:
    condition_id: str
    token_id: str
    direction: str           # "UP" or "DOWN"
    shares: int              # number of shares bought
    entry_price: float       # ask price paid per share
    entry_time: float        # time.time() at fill
    entry_edge: float = 0.0
    entry_p_up: float = 0.5
    entry_seconds_left: int = 0
    peak_bid: float = 0.0

    # Sell-order state (filled in after we post a GTC limit sell)
    sell_order_id: Optional[str] = None
    sell_price: float = 0.0  # price we're offering
    hold_to_expiry: bool = False  # True when position is too small to sell via limit order
    exit_reason: str = ""
    averaged: bool = False  # True after one average-down buy has been placed


@dataclass
class PendingBuy:
    order_id: str
    condition_id: str
    token_id: str
    direction: str       # "UP" or "DOWN"
    shares: int
    price: float
    placed_at: float     # time.time() when placed
    edge: float = 0.0
    p_up: float = 0.5
    seconds_left: int = 0


@dataclass
class PositionStore:
    position: Optional[Position] = None
    pending_buy: Optional[PendingBuy] = None
    held_positions: list[Position] = field(default_factory=list)

    def has_position(self) -> bool:
        return self.position is not None

    def has_pending_buy(self) -> bool:
        return self.pending_buy is not None

    def open(
        self,
        condition_id: str,
        token_id: str,
        direction: str,
        shares: int,
        entry_price: float,
        entry_time: float,
        entry_edge: float = 0.0,
        entry_p_up: float = 0.5,
        entry_seconds_left: int = 0,
    ) -> None:
        self.position = Position(
            condition_id=condition_id,
            token_id=token_id,
            direction=direction,
            shares=shares,
            entry_price=entry_price,
            entry_time=entry_time,
            entry_edge=entry_edge,
            entry_p_up=entry_p_up,
            entry_seconds_left=entry_seconds_left,
            peak_bid=entry_price,
        )

    def open_pending_buy(
        self,
        order_id: str,
        condition_id: str,
        token_id: str,
        direction: str,
        shares: int,
        price: float,
        edge: float = 0.0,
        p_up: float = 0.5,
        seconds_left: int = 0,
    ) -> None:
        self.pending_buy = PendingBuy(
            order_id=order_id,
            condition_id=condition_id,
            token_id=token_id,
            direction=direction,
            shares=shares,
            price=price,
            placed_at=time.time(),
            edge=edge,
            p_up=p_up,
            seconds_left=seconds_left,
        )

    def clear_pending_buy(self) -> None:
        self.pending_buy = None

    def close(self) -> None:
        self.position = None

    def park_current_position(self) -> None:
        if self.position:
            self.held_positions.append(self.position)
            self.position = None

    def attach_sell_order(self, order_id: str, price: float, reason: str = "") -> None:
        if self.position:
            self.position.sell_order_id = order_id
            self.position.sell_price = price
            self.position.exit_reason = reason

    def clear_sell_order(self) -> None:
        if self.position:
            self.position.sell_order_id = None
            self.position.sell_price = 0.0
            self.position.exit_reason = ""


# Singleton shared across modules
pos_store = PositionStore()
