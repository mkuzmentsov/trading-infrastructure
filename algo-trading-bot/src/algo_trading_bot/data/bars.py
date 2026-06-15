"""OHLCV normalization (§2.1).

Different venues report bars with different timestamp conventions (open-time vs
close-time), symbol naming, and precision. Normalize to a single canonical form
*at ingestion* so everything downstream is venue-agnostic. The critical bit is
stamping ``knowable_at`` = bar close (a bar is not knowable until it closes).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from ..core.types import Bar, Symbol, VenueId

# Canonical bar intervals -> their duration. Drives knowable_at and resampling.
INTERVALS: dict[str, timedelta] = {
    "1m": timedelta(minutes=1),
    "5m": timedelta(minutes=5),
    "15m": timedelta(minutes=15),
    "1h": timedelta(hours=1),
    "4h": timedelta(hours=4),
    "1d": timedelta(days=1),
}


def normalize_symbol(raw: str, venue: VenueId) -> Symbol:
    """Map a venue-specific ticker to the canonical :class:`Symbol`."""
    raise NotImplementedError("e.g. Kraken 'XBT/USD' and HL 'BTC' -> Symbol('BTC')")


def to_bar(raw: dict, symbol: Symbol, venue: VenueId, interval: str, open_time: datetime) -> Bar:
    """Build a canonical, close-time-stamped bar from a raw venue payload.

    ``knowable_at`` is set to the close time: open_time + interval duration.
    """
    duration = INTERVALS[interval]
    close_time = open_time + duration
    raise NotImplementedError("map raw OHLCV fields; set ts=close_time, knowable_at=close_time")
