"""Live-style market sources for the paper/live runner (§2.1, §9 Phase 6–7).

Two sources, both feeding the *same* engine path as the backtest (NFR1):

* :func:`replay_source` — stream stored historical bars through the live runner at a
  configurable speed. No network or API keys; deterministic. The default for local /
  Docker demos and for testing the live wiring.
* :func:`ccxt_poll_source` — poll a venue for newly *closed* bars (real live data).
  Used with ``--source live``. The most-recent row from ccxt may still be forming, so
  we emit the second-to-last (last fully-closed) bar.
"""

from __future__ import annotations

import time
from typing import Iterator

from ..core.types import Bar, Symbol
from .bars import INTERVALS, bar_from_ohlcv, normalize_symbol
from .fetch import _market_symbol


def replay_source(
    bars: list[Bar], speed: float = 20.0, max_bars: int | None = None
) -> Iterator[Bar]:
    """Replay ``bars`` in order, sleeping 1/speed seconds between them (0 = as fast as
    possible). Lets you watch the live engine run deterministically off stored data."""
    delay = 1.0 / speed if speed and speed > 0 else 0.0
    for i, bar in enumerate(bars):
        if max_bars is not None and i >= max_bars:
            return
        yield bar
        if delay:
            time.sleep(delay)


def ccxt_poll_source(
    venue: str,
    symbols: list[str],
    interval: str,
    *,
    max_bars: int | None = None,
    poll_seconds: float | None = None,
) -> Iterator[Bar]:
    """Poll ``venue`` for newly-closed bars and yield them. Requires the ``venues`` extra."""
    import ccxt

    ex = getattr(ccxt, venue)({"enableRateLimit": True})
    if poll_seconds is None:
        poll_seconds = min(INTERVALS[interval].total_seconds(), 60.0)

    last_seen: dict[str, int] = {}
    emitted = 0
    while True:
        for base in symbols:
            market = _market_symbol(venue, base)
            rows = ex.fetch_ohlcv(market, interval, limit=2)
            if len(rows) < 2:
                continue
            closed = rows[-2]  # rows[-1] may still be forming
            if last_seen.get(base) == closed[0]:
                continue
            last_seen[base] = closed[0]
            yield bar_from_ohlcv(closed, normalize_symbol(base, venue), venue, interval)
            emitted += 1
            if max_bars is not None and emitted >= max_bars:
                return
        time.sleep(poll_seconds)
