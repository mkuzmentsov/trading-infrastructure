"""OHLCV normalization (§2.1).

Different venues report bars with different timestamp conventions, symbol naming,
and precision. Normalize to a single canonical form *at ingestion* so everything
downstream is venue-agnostic. The critical bit is stamping ``knowable_at`` = bar
close: a bar is not knowable until it closes (no lookahead).

ccxt reports the bar's *open* time, so close = open + interval duration.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

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

# Periods per year for annualizing vol/returns, per interval (§3.3 metrics).
PERIODS_PER_YEAR: dict[str, float] = {
    "1m": 365 * 24 * 60,
    "5m": 365 * 24 * 12,
    "15m": 365 * 24 * 4,
    "1h": 365 * 24,
    "4h": 365 * 6,
    "1d": 365,
}

# A few venue tickers that don't match the canonical base symbol.
_BASE_ALIASES = {"XBT": "BTC", "XDG": "DOGE"}


def normalize_symbol(raw: str, venue: VenueId | str = "") -> Symbol:
    """Map a venue-specific ticker to the canonical :class:`Symbol`.

    Handles ccxt unified symbols: 'BTC/USD', 'BTC/USDT', 'BTC/USDC:USDC' -> 'BTC'.
    """
    base = raw.split("/")[0].split(":")[0].strip().upper()
    base = _BASE_ALIASES.get(base, base)
    return Symbol(base)


def bar_from_ohlcv(
    row: list | tuple,
    symbol: Symbol,
    venue: VenueId,
    interval: str,
) -> Bar:
    """Build a canonical, close-time-stamped bar from a ccxt OHLCV row.

    Row is ``[open_time_ms, open, high, low, close, volume]``. ``ts`` and
    ``knowable_at`` are set to the bar *close* time.
    """
    duration = INTERVALS[interval]
    open_time = datetime.fromtimestamp(row[0] / 1000, tz=timezone.utc)
    close_time = open_time + duration
    return Bar(
        symbol=symbol,
        ts=close_time,
        open=float(row[1]),
        high=float(row[2]),
        low=float(row[3]),
        close=float(row[4]),
        volume=float(row[5]),
        venue=venue,
        knowable_at=close_time,
    )
