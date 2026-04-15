"""Gamma API market discovery and Google News RSS fetch."""
from __future__ import annotations

import json
import logging
import time
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import requests

from config import GAMMA_API, MIN_DAYS_TO_CLOSE, MIN_MARKET_VOLUME
from models import Market, Outcome

logger = logging.getLogger(__name__)


def fetch_markets(offset: int = 0, limit: int = 100) -> tuple:
    try:
        resp = requests.get(
            f"{GAMMA_API}/markets",
            params={"active": "true", "closed": "false", "limit": limit, "offset": offset,
                    "order": "volume24hr", "ascending": "false"},
            timeout=15,
        )
        resp.raise_for_status()
    except Exception as e:
        logger.error(f"  Failed to fetch markets: {e}")
        return [], 0

    now = datetime.now(timezone.utc)
    raw = resp.json()
    markets: list = []
    skipped_tokens = skipped_vol = skipped_expiry = 0

    for m in raw:
        try:
            token_ids = m.get("clobTokenIds") or []
            if isinstance(token_ids, str):
                token_ids = json.loads(token_ids)
            if len(token_ids) < 2:
                skipped_tokens += 1
                continue

            labels_raw = m.get("outcomes") or []
            if isinstance(labels_raw, str):
                labels_raw = json.loads(labels_raw)
            prices_raw = m.get("outcomePrices") or []
            if isinstance(prices_raw, str):
                prices_raw = json.loads(prices_raw)
            while len(labels_raw) < len(token_ids):
                labels_raw.append(f"Outcome {len(labels_raw)}")
            while len(prices_raw) < len(token_ids):
                prices_raw.append("0.5")

            outcomes = [
                Outcome(label=str(labels_raw[i]), price=float(prices_raw[i]), token_id=str(token_ids[i]))
                for i in range(len(token_ids))
            ]
            if all(o.price < 0.01 or o.price > 0.99 for o in outcomes):
                skipped_tokens += 1
                continue

            vol_24h = float(m.get("volume24hr") or m.get("volume24Hr") or m.get("volumeNum") or 0)
            if vol_24h < MIN_MARKET_VOLUME:
                skipped_vol += 1
                continue

            end_date_str = m.get("endDate", "")
            days_to_close = 9999.0
            if end_date_str:
                try:
                    end_dt = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
                    days_to_close = (end_dt - now).total_seconds() / 86400.0
                except Exception:
                    skipped_expiry += 1
                    continue
                if days_to_close < MIN_DAYS_TO_CLOSE:
                    skipped_expiry += 1
                    continue

            markets.append(Market(
                condition_id  = m.get("conditionId") or m.get("id", ""),
                question      = m.get("question", ""),
                description   = (m.get("description") or "")[:400],
                volume_24h    = vol_24h,
                end_date      = end_date_str,
                days_to_close = days_to_close,
                neg_risk      = bool(m.get("negRisk") or m.get("neg_risk") or False),
                min_size      = float(m.get("orderMinSize") or m.get("minOrderSize") or 1.0),
                outcomes      = outcomes,
            ))
        except Exception as e:
            logger.warning(f"  Skipping market (parse error): {e}")

    logger.info(
        f"  Fetched {len(raw)} markets — kept {len(markets)} "
        f"(skipped: no_tokens={skipped_tokens} vol={skipped_vol} expiry={skipped_expiry})"
    )
    return markets, len(raw)


_NEWS_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)


def fetch_news(query: str, max_results: int = 4) -> str:
    """Google News RSS search. No API key, no rate-limits in practice.
    Returns a newline-joined digest of recent items, or '' on failure."""
    q   = urllib.parse.quote_plus(query)
    url = f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
    try:
        resp = requests.get(url, headers={"User-Agent": _NEWS_UA}, timeout=10)
        resp.raise_for_status()
    except Exception as e:
        logger.warning(f"  News fetch failed ('{query[:40]}'): {e}")
        return ""

    try:
        root  = ET.fromstring(resp.content)
        items = root.findall(".//item")
    except ET.ParseError as e:
        logger.warning(f"  News parse failed ('{query[:40]}'): {e}")
        return ""

    lines: list[str] = []
    for it in items[:max_results]:
        title = (it.findtext("title") or "").strip()
        date  = (it.findtext("pubDate") or "?").strip()
        desc  = _strip_html((it.findtext("description") or "").strip())
        lines.append(f"[{date[:16]}] {title} — {desc[:180]}")
    return "\n".join(lines)


def _strip_html(s: str) -> str:
    import re
    return re.sub(r"<[^>]+>", " ", s).replace("&nbsp;", " ").strip()
