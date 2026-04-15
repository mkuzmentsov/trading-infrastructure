"""Live position fetching from the Polymarket data-api."""
from __future__ import annotations

import logging

import requests

from config import DATA_API, PORTFOLIO_WALLET
from models import HeldPosition

logger = logging.getLogger(__name__)


def fetch_held_positions() -> list:
    """Fetch live holdings from the Polymarket data-api /positions endpoint."""
    if not PORTFOLIO_WALLET:
        logger.warning("  No wallet address configured — cannot fetch positions")
        return []
    try:
        resp = requests.get(
            f"{DATA_API}/positions",
            params={"user": PORTFOLIO_WALLET, "sizeThreshold": 0.1, "limit": 200},
            timeout=15,
        )
        resp.raise_for_status()
        raw = resp.json()
    except Exception as e:
        logger.warning(f"  data-api /positions failed: {e}")
        return []

    positions = []
    for p in raw:
        try:
            size = float(p.get("size") or 0)
            if size <= 0:
                continue
            positions.append(HeldPosition(
                condition_id  = p.get("conditionId", ""),
                token_id      = p.get("asset", ""),
                outcome       = p.get("outcome", ""),
                question      = p.get("title", ""),
                size_shares   = size,
                avg_price     = float(p.get("avgPrice") or 0),
                current_price = float(p.get("curPrice") or p.get("currentPrice") or 0),
                cash_pnl      = float(p.get("cashPnl") or 0),
                percent_pnl   = float(p.get("percentPnl") or 0),
                end_date      = p.get("endDate", "") or "",
                redeemable    = bool(p.get("redeemable") or False),
                neg_risk      = bool(p.get("negativeRisk") or p.get("negRisk") or False),
            ))
        except Exception as e:
            logger.warning(f"  Skipping malformed position: {e}")
    logger.info(f"  Loaded {len(positions)} held position(s) from data-api")
    return positions
