"""Historical OHLCV ingestion via ccxt (§2.1, Phase 1).

Paginates ``fetch_ohlcv`` from ``start`` to ``end`` and returns canonical Bars.
Note the venue asymmetry observed in practice:

* **Binance**: honors ``since`` and paginates — years of history. Good *data* venue.
* **Kraken**: ignores ``since`` and returns only the most recent ~720 bars. Fine as
  a *trade* venue (§8) but shallow for backtest history; fetch elsewhere and trade
  on Kraken.
* **Hyperliquid**: ccxt paginates but the venue caps history (~5000 bars).

So data ingestion and trade routing are decoupled on purpose (§2.1).
"""

from __future__ import annotations

from datetime import datetime, timezone

from ..core.types import Bar, Symbol, VenueId
from .bars import INTERVALS, bar_from_ohlcv, normalize_symbol

# ccxt unified quote per venue for a base symbol. Kept tiny and explicit.
# Perp venues use a settle suffix ("BTC/USD:USD" etc.) so the market is the swap.
_QUOTE = {
    "binance": "USDT",            # spot (data only)
    "kraken": "USD",              # spot
    "krakenfutures": "USD:USD",   # USD-settled linear perpetual
    "hyperliquid": "USDC:USDC",   # USDC-settled perpetual
}


def _market_symbol(venue: str, base: str) -> str:
    quote = _QUOTE.get(venue, "USDT")
    return f"{base}/{quote}"


def fetch_ohlcv(
    venue: str,
    symbols: list[str],
    interval: str,
    start: datetime,
    end: datetime,
    *,
    limit: int = 1000,
) -> list[Bar]:
    """Fetch canonical Bars for ``symbols`` over [start, end]. Requires the ``venues`` extra."""
    import ccxt  # local import so the dependency is optional

    if interval not in INTERVALS:
        raise ValueError(f"unsupported interval {interval!r}; one of {list(INTERVALS)}")

    ex = getattr(ccxt, venue)({"enableRateLimit": True})
    step_ms = int(INTERVALS[interval].total_seconds() * 1000)
    end_ms = int(end.replace(tzinfo=timezone.utc).timestamp() * 1000)

    out: list[Bar] = []
    for base in symbols:
        canonical = normalize_symbol(base, venue)
        market = _market_symbol(venue, base)
        since = int(start.replace(tzinfo=timezone.utc).timestamp() * 1000)
        prev_last_ts: int | None = None
        while since < end_ms:
            rows = ex.fetch_ohlcv(market, interval, since=since, limit=limit)
            if not rows:
                break
            for row in rows:
                if row[0] > end_ms:
                    break
                out.append(bar_from_ohlcv(row, canonical, VenueId(venue), interval))
            last_ts = rows[-1][0]
            # Venues that ignore `since` (e.g. Kraken) return the same window each call;
            # stop once the last bar timestamp stops advancing.
            if last_ts == prev_last_ts:
                break
            prev_last_ts = last_ts
            since = last_ts + step_ms
            if last_ts >= end_ms:
                break
    return out


def fetch_to_store(
    store,
    venue: str,
    symbols: list[str],
    interval: str,
    start: datetime,
    end: datetime,
) -> int:
    """Fetch and persist to a point-in-time store. Returns the number of bars written."""
    bars = fetch_ohlcv(venue, symbols, interval, start, end)
    store.append_bars(bars, interval)
    return len(bars)
