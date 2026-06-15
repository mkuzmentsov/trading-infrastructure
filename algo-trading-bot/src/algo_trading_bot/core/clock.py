"""Clock abstraction so 'now' is the same concept in backtest and live (NFR1).

In live, ``now()`` is wall time. In backtest, it is the timestamp of the event
currently being processed — which makes point-in-time enforcement trivial: any
data whose ``knowable_at`` is after ``clock.now()`` is the future and must not be
visible (§2.1, §2.2).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...


class WallClock:
    """Live clock."""

    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class SimClock:
    """Backtest clock, advanced by the engine to each event's timestamp."""

    def __init__(self, start: datetime) -> None:
        self._now = start

    def now(self) -> datetime:
        return self._now

    def advance_to(self, ts: datetime) -> None:
        if ts < self._now:
            raise ValueError(f"clock cannot go backwards: {ts} < {self._now}")
        self._now = ts
