"""Event types for the event-driven core (§3.1).

The engine processes one event at a time, in timestamp order, *exactly as live*.
Backtest and live differ only in who produces these events (a historical replayer
vs. live venue feeds) and who consumes the resulting orders (a fill simulator vs.
a venue adapter). Same decision code path either way (NFR1).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .types import Bar, Fill, FundingPoint, Order


@dataclass(frozen=True, slots=True)
class MarketEvent:
    """New market data is knowable. Triggers feature update -> strategies -> arbitration."""

    bar: Bar


@dataclass(frozen=True, slots=True)
class FundingEvent:
    point: FundingPoint


@dataclass(frozen=True, slots=True)
class OrderEvent:
    """An order the OMS wants placed (or canceled). Consumed by the execution adapter."""

    order: Order
    cancel: bool = False


@dataclass(frozen=True, slots=True)
class FillEvent:
    """An order (partially) filled. Updates positions, NAV, and stop state."""

    fill: Fill


@dataclass(frozen=True, slots=True)
class TimerEvent:
    """Wall-clock / scheduled tick: heartbeat, retrain check, drift check (§2.7)."""

    ts: datetime
    kind: str  # "heartbeat" | "retrain" | "drift_check" | ...


Event = MarketEvent | FundingEvent | OrderEvent | FillEvent | TimerEvent
