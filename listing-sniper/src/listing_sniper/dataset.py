"""Historical listing dataset + the per-listing characterization metrics.

Two parts:
- ``binance_klines`` / ``first_day_closes`` — pull the first trading day of 1-minute closes for a
  symbol. Binance returns klines from the *first available bar*, so that bar IS the listing open —
  no need to parse the announced time for the historical study.
- ``listing_metrics`` — pure, tested: turn an open-anchored close series into the numbers that answer
  "pump then bleed?" (peak return, time-to-peak, drawdown-from-peak, returns at fixed horizons).

⚠ Survivorship: delisted tokens lose their Binance klines, so a klines-only sample is biased toward
survivors (the worst dumpers vanish). Treat results as an upper bound; see PLAN.md §4.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable

HttpGet = Callable[[str], object]
_SPOT = "https://api.binance.com/api/v3/klines"
_FUT = "https://fapi.binance.com/fapi/v1/klines"

_HORIZONS_MIN = {"ret_5m": 5, "ret_15m": 15, "ret_1h": 60, "ret_4h": 240, "ret_24h": 1440}


def _http_get_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read())


def binance_klines(symbol: str, interval: str = "1m", start_ms: int = 0, limit: int = 1000, *,
                   futures: bool = False, http: HttpGet = _http_get_json) -> list:
    base = _FUT if futures else _SPOT
    q = urllib.parse.urlencode({"symbol": symbol, "interval": interval,
                                "startTime": start_ms, "limit": limit})
    try:
        rows = http(f"{base}?{q}")
    except urllib.error.HTTPError as e:
        if e.code == 400:          # invalid/nonexistent symbol — expected while probing quotes
            return []
        raise                       # 418/429 rate-limit etc. must surface
    return rows if isinstance(rows, list) else []


def first_day_closes(symbol: str, *, futures: bool = False, minutes: int = 1440,
                     http: HttpGet = _http_get_json):
    """(listing_open_ms, list[close]) for the first ``minutes`` of trading, or (None, []) if the
    symbol has no klines (never listed / delisted-and-purged)."""
    rows = binance_klines(symbol, "1m", 0, 1000, futures=futures, http=http)
    if not rows:
        return None, []
    listing_ms = int(rows[0][0])
    closes = [float(r[4]) for r in rows]
    while len(closes) < minutes and len(rows) == 1000:
        nxt = int(rows[-1][0]) + 60_000
        rows = binance_klines(symbol, "1m", nxt, 1000, futures=futures, http=http)
        closes += [float(r[4]) for r in rows]
    return listing_ms, closes[:minutes]


def listing_metrics(closes) -> dict:
    """Open-anchored first-day metrics. ``closes`` = 1-minute closes starting at the listing open.

    peak_ret/time_to_peak_min describe the pump; dd_from_peak the bleed after it; ret_* the path at
    fixed horizons; ``dumped_from_open`` flags the classic 'spike then below open within the hour'.
    """
    xs = [float(c) for c in closes if c == c and float(c) > 0]  # finite, positive
    n = len(xs)
    if n < 2:
        return {}
    o = xs[0]
    peak_i = max(range(n), key=lambda i: xs[i])
    peak = xs[peak_i]
    after = xs[peak_i:]
    out = {
        "open": o,
        "n_bars": n,
        "peak_ret": peak / o - 1.0,
        "time_to_peak_min": peak_i,                       # 1m bars -> minutes
        "dd_from_peak": min(after) / peak - 1.0,          # <= 0, the post-peak bleed
        "end_ret": xs[-1] / o - 1.0,
    }
    for name, m in _HORIZONS_MIN.items():
        out[name] = (xs[m] / o - 1.0) if m < n else float("nan")
    # classic pattern: spiked >=20% at some point AND back below open within the first hour
    hi_1h = max(xs[: min(60, n)])
    lo_after_60 = xs[59] if n > 59 else xs[-1]
    out["dumped_from_open"] = (hi_1h / o - 1.0 >= 0.20) and (lo_after_60 <= o)
    return out
