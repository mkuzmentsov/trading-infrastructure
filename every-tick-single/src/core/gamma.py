"""
Polymarket Gamma API: market discovery and token parsing.
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from typing import Optional

import requests

from config import BAR_SECONDS, COIN, GAMMA_API, log


_COIN_FULL = {"btc": "bitcoin", "eth": "ethereum", "sol": "solana",
              "xrp": "xrp", "doge": "dogecoin", "bnb": "bnb"}


def window_slug(window_start_ts: int) -> str:
    """Deterministic slug for the COIN UpDown market whose bar opens at
    `window_start_ts`. 5m/15m: {coin}-updown-{n}m-{ts}. Hourly (3600s):
    name-based ET slug ({fullname}-up-or-down-{month}-{d}-{yyyy}-{h}{am/pm}-et)
    — ET hour starts align with the 3600s grid (UTC offset is whole hours).
    Daily (86400s): noon-ET-to-noon-ET window, slug names the END date
    ({fullname}-up-or-down-on-{month}-{d}-{yyyy}), verified live 2026-07-31."""
    if BAR_SECONDS == 3600:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        dt = datetime.fromtimestamp(int(window_start_ts), ZoneInfo("America/New_York"))
        hour = dt.strftime("%I%p").lstrip("0").lower()
        return (f"{_COIN_FULL.get(COIN, COIN)}-up-or-down-"
                f"{dt.strftime('%B').lower()}-{dt.day}-{dt.year}-{hour}-et")
    if BAR_SECONDS == 86400:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        dt = datetime.fromtimestamp(next_window_start(int(window_start_ts)),
                                    ZoneInfo("America/New_York"))
        return (f"{_COIN_FULL.get(COIN, COIN)}-up-or-down-on-"
                f"{dt.strftime('%B').lower()}-{dt.day}-{dt.year}")
    return f"{COIN}-updown-{BAR_SECONDS // 60}m-{int(window_start_ts)}"


def grid_window_start(now_ts: float) -> int:
    """Start of the window containing now_ts. Epoch-aligned for 5m/15m/1h (ET
    offsets are whole hours, so the 3600 grid lines up). Daily markets are
    anchored at NOON ET (they resolve 12:00 PM ET; end=16:00Z in summer,
    17:00Z in winter), so the epoch-midnight grid is wrong for them — compute
    the most recent noon ET via zoneinfo, which also handles DST days
    (23h/25h windows) correctly."""
    if BAR_SECONDS != 86400:
        return int(now_ts // BAR_SECONDS * BAR_SECONDS)
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    et = ZoneInfo("America/New_York")
    dt = datetime.fromtimestamp(int(now_ts), et)
    d = dt.date() if dt.hour >= 12 else dt.date() - timedelta(days=1)
    return int(datetime(d.year, d.month, d.day, 12, 0, tzinfo=et).timestamp())


def next_window_start(ws: int) -> int:
    """Start of the window after the one starting at ws (== that window's
    end). DST-safe for daily: next noon ET by date, not ws+86400."""
    if BAR_SECONDS != 86400:
        return int(ws) + BAR_SECONDS
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    et = ZoneInfo("America/New_York")
    d = datetime.fromtimestamp(int(ws), et).date() + timedelta(days=1)
    return int(datetime(d.year, d.month, d.day, 12, 0, tzinfo=et).timestamp())


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


def fetch_btc_5m_market() -> Optional[dict]:
    """
    Fetch the current {COIN} Up/Down 5-minute market by slug (COIN env, default btc).
    Tries the current 5m boundary; if not found or already closed, tries the next one.
    """
    for offset_secs in [0, BAR_SECONDS]:
        ts   = (int(time.time()) // BAR_SECONDS) * BAR_SECONDS + offset_secs
        slug = window_slug(ts)
        try:
            data = _gamma_get({"slug": slug})
            market = (data[0] if isinstance(data, list) else data) if data else None
            if market and market.get("active") and not market.get("closed"):
                log.info("Found market: %s  (slug=%s)", market.get("question", ""), slug)
                return market
        except Exception as exc:
            log.debug("Slug %s not found: %s", slug, exc)
    return None


def fetch_market_for_window(window_start_ts: int) -> Optional[dict]:
    """Fetch the {COIN} Up/Down 5m market for an exact window by its
    deterministic slug ({coin}-updown-5m-{ts}). Used by the live maker's
    T−30s pre-discovery: the NEXT bar's slug is known before the bar starts,
    so at bar roll no Gamma call is needed."""
    slug = window_slug(window_start_ts)
    try:
        data = _gamma_get({"slug": slug})
        market = (data[0] if isinstance(data, list) else data) if data else None
        if market and market.get("active") and not market.get("closed"):
            log.info("Pre-discovered market: %s  (slug=%s)", market.get("question", ""), slug)
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
    # actual 5m event boundary. Prefer the event/window timestamps first.
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
    match = re.search(r"[a-z0-9]+-updown-(\d+)m-(\d+)", slug)
    if match:
        duration_secs = int(match.group(1)) * 60
        slug_start_ts = int(match.group(2))
        start_ts = start_ts or slug_start_ts
        end_ts = end_ts or (slug_start_ts + duration_secs)

    if start_ts and not end_ts:
        end_ts = start_ts + BAR_SECONDS

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
