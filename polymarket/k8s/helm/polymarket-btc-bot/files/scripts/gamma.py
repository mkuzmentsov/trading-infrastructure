"""
Polymarket Gamma API: market discovery and token parsing.
"""
from __future__ import annotations

import json
import time
from typing import Optional

import requests

from config import GAMMA_API, log


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
    Fetch the current BTC Up/Down 5-minute market by slug.
    Tries the current 5m boundary; if not found or already closed, tries the next one.
    """
    for offset_secs in [0, 300]:
        ts   = (int(time.time()) // 300) * 300 + offset_secs
        slug = f"btc-updown-5m-{ts}"
        try:
            data = _gamma_get({"slug": slug})
            market = (data[0] if isinstance(data, list) else data) if data else None
            if market and market.get("active") and not market.get("closed"):
                log.info("Found market: %s  (slug=%s)", market.get("question", ""), slug)
                return market
        except Exception as exc:
            log.debug("Slug %s not found: %s", slug, exc)
    return None


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
