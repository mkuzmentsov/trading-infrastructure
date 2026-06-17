"""Data source protocol — the *only* thing that differs between backtest and live
on the input side (§2, §3.1).

A historical source replays stored bars in time order; a live source streams from
a venue. Both yield the same :class:`Bar`/:class:`FundingPoint` objects, so every
downstream layer is identical in both modes (NFR1).
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable, Iterator, Protocol

from ..core.types import Bar, FundingPoint, Symbol
from .store import PointInTimeStore


class DataSource(Protocol):
    """Yields point-in-time-correct market data in non-decreasing ``knowable_at`` order."""

    def stream(self) -> Iterator[Bar | FundingPoint]:
        """Live: blocks for new data. Backtest: iterates the snapshot to exhaustion."""
        ...


class HistoricalSource:
    """Replays a stored snapshot. Backbone of the backtest (§3.1).

    Emits bars strictly ordered by ``knowable_at`` so the engine never sees the future.
    """

    def __init__(
        self,
        store: PointInTimeStore,
        symbols: Iterable[Symbol],
        start: datetime,
        end: datetime,
        interval: str,
        venue: str | None = None,
    ) -> None:
        self.store = store
        self.symbols = [Symbol(s) for s in symbols]
        self.start = start
        self.end = end
        self.interval = interval
        self.venue = venue

    def stream(self) -> Iterator[Bar | FundingPoint]:
        yield from self.store.read_ordered(
            self.symbols, self.start, self.end, self.interval, venue=self.venue
        )


class LiveSource:
    """Streams live bars/funding from the active venue adapter (§2.1)."""

    def __init__(self, symbols: Iterable[Symbol]) -> None:
        self.symbols = list(symbols)

    def stream(self) -> Iterator[Bar | FundingPoint]:
        raise NotImplementedError("wire to the active venue adapter's market feed")
