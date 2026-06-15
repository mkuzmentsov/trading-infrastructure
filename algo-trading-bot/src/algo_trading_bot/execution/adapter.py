"""Execution adapter protocol (§2.6).

The *only* thing that differs between backtest and live on the output side. A
backtest uses a fill-simulator adapter (applies friction, returns synthetic fills);
live uses a venue adapter (places real orders, receives real fills). Same OMS, same
decision path drives both (NFR1).
"""

from __future__ import annotations

from typing import Protocol

from ..core.types import Fill, Order, Position, Symbol


class ExecutionAdapter(Protocol):
    """Order I/O against a venue (or a simulator)."""

    def place(self, order: Order) -> None: ...
    def cancel(self, client_id: str) -> None: ...
    def open_orders(self) -> list[Order]: ...
    def positions(self) -> dict[Symbol, Position]: ...
    def poll_fills(self) -> list[Fill]: ...
