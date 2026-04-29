"""
Polymarket Gamma API: market discovery and token parsing.
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import requests

from config import BAR_DURATION_SECS, GAMMA_API, log

_ET_ZONE = ZoneInfo("America/New_York")
_MONTHS = (
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
)


def _gamma_get(params: dict):
    """GET /markets from Gamma API with full request/response logging."""
    url = f"{GAMMA_API}/markets"
    log.info("Gamma API REQUEST  url=%s  params=%s", url, params)
    try:
        r = requests.get(url, params=params, timeout=15)
        log.info("Gamma API RESPONSE status=%d  url=%s  body=%s", r.status_code, r.url, r.text)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        log.warning("Gamma API ERROR (params=%s): %s", params, exc)
        return None


def _hourly_slug(boundary_ts: int) -> str:
    """Hourly Binance-resolved Up/Down slug.

    Boundary ts is the UTC start of the bar; market slugs use ET-localized
    dates and 12-hour clock with am/pm. Example: 2026-04-29T10:00:00Z (=
    6 AM EDT) → ``bitcoin-up-or-down-april-29-2026-6am-et``.
    """
    dt_et = datetime.fromtimestamp(boundary_ts, tz=timezone.utc).astimezone(_ET_ZONE)
    month = _MONTHS[dt_et.month - 1]
    hour_24 = dt_et.hour
    ampm = "am" if hour_24 < 12 else "pm"
    hour_12 = hour_24 % 12
    if hour_12 == 0:
        hour_12 = 12
    return f"bitcoin-up-or-down-{month}-{dt_et.day}-{dt_et.year}-{hour_12}{ampm}-et"


def _quarter_hour_slug(boundary_ts: int) -> str:
    """Original Chainlink-resolved 5m/15m slug: ``btc-updown-{N}m-{boundary_ts}``."""
    minutes = max(1, BAR_DURATION_SECS // 60)
    return f"btc-updown-{minutes}m-{boundary_ts}"


def _build_slug(boundary_ts: int) -> str:
    if BAR_DURATION_SECS == 3600:
        return _hourly_slug(boundary_ts)
    return _quarter_hour_slug(boundary_ts)


def fetch_btc_bar_market() -> Optional[dict]:
    """Fetch the current BTC Up/Down market for the configured bar duration.

    Tries the current bar boundary first; if not found or already closed,
    falls back to the next boundary.
    """
    for offset_secs in (0, BAR_DURATION_SECS):
        ts = (int(time.time()) // BAR_DURATION_SECS) * BAR_DURATION_SECS + offset_secs
        slug = _build_slug(ts)
        try:
            data = _gamma_get({"slug": slug})
            market = (data[0] if isinstance(data, list) else data) if data else None
            if market and market.get("active") and not market.get("closed"):
                log.info("Found market: %s  (slug=%s)", market.get("question", ""), slug)
                return market
        except Exception as exc:
            log.debug("Slug %s not found: %s", slug, exc)
    return None


def _parse_ts(value) -> int:
    if value in (None, ""):
        return 0
    if isinstance(value, (int, float)):
        ts = int(value)
        return ts // 1000 if ts > 10_000_000_000 else ts
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return 0
        if raw.isdigit():
            ts = int(raw)
            return ts // 1000 if ts > 10_000_000_000 else ts
        try:
            if raw.endswith("Z"):
                raw = raw[:-1] + "+00:00"
            dt = datetime.fromisoformat(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = dt.astimezone(timezone.utc)
            return int(dt.timestamp())
        except ValueError:
            return 0
    return 0


def get_market_window(market: dict) -> tuple[int, int]:
    start_ts = 0
    end_ts = 0
    primary_event = {}
    events = market.get("events")
    if isinstance(events, list) and events and isinstance(events[0], dict):
        primary_event = events[0]

    # `startDate` is often the market metadata creation time rather than the
    # actual bar event boundary. Prefer the event/window timestamps first.
    for source in (market, primary_event):
        for key in (
            "eventStartTime",
            "event_start_time",
            "gameStartTime",
            "startTime",
            "start_time",
        ):
            start_ts = max(start_ts, _parse_ts(source.get(key)))
        for key in ("endDate", "end_date", "gameEndTime", "endTime", "end_time"):
            end_ts = max(end_ts, _parse_ts(source.get(key)))

    if not start_ts:
        for source in (market, primary_event):
            for key in ("startDate", "start_date"):
                start_ts = max(start_ts, _parse_ts(source.get(key)))

    slug = str(market.get("slug") or market.get("market_slug") or "")
    # 5m/15m slug encodes start_ts directly. Hourly slugs use ET dates and rely
    # on the API-provided eventStartTime/endDate above.
    match = re.search(r"btc-updown-(\d+)m-(\d+)", slug)
    if match:
        duration_secs = int(match.group(1)) * 60
        slug_start_ts = int(match.group(2))
        start_ts = start_ts or slug_start_ts
        end_ts = end_ts or (slug_start_ts + duration_secs)

    if start_ts and not end_ts:
        end_ts = start_ts + BAR_DURATION_SECS

    return start_ts, end_ts


def get_up_down_tokens(market: dict) -> tuple[Optional[dict], Optional[dict]]:
    """
    Parse the market's outcomes/outcomePrices/clobTokenIds fields (all JSON strings)
    and return (up_token, down_token) as dicts with keys: outcome, price, token_id.
    """
    try:
        outcomes  = json.loads(market.get("outcomes",      "[]"))
        prices    = json.loads(market.get("outcomePrices", "[]"))
        token_ids = json.loads(market.get("clobTokenIds",  "[]"))
    except (json.JSONDecodeError, TypeError):
        return None, None

    tokens = [
        {"outcome": outcomes[i], "price": float(prices[i]), "token_id": token_ids[i]}
        for i in range(len(outcomes))
        if i < len(prices) and i < len(token_ids)
    ]

    up, down = None, None
    for tok in tokens:
        label = tok["outcome"].lower()
        if "up" in label:
            up = tok
        elif "down" in label:
            down = tok
    # Fallback: index order (Up=0, Down=1 per Polymarket convention)
    if up is None and len(tokens) >= 2:
        up, down = tokens[0], tokens[1]
    return up, down


def compute_edge(p_model: float, p_market: float, direction: str) -> float:
    """
    Edge for betting on `direction` outcome.
    direction='up'   → p_model is P(UP)
    direction='down' → p_model is 1 - P(UP)
    """
    p_our = p_model if direction == "up" else 1.0 - p_model
    return p_our - p_market
