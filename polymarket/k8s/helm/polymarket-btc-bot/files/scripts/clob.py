"""
Polymarket CLOB client: order placement, balance, sizing, and trade queries.
"""
from __future__ import annotations

import os
import time
from typing import Optional

from config import (
    BET_SIZE_MAX, BET_SIZE_MIN, CHAIN_ID, CLOB_HOST,
    DRY_RUN, POLYMARKET_API_KEY, POLYMARKET_API_PASSPHRASE,
    POLYMARKET_API_SECRET, POLYMARKET_FUNDER, POLYMARKET_PK,
    SIGNATURE_TYPE, log,
)


def build_clob_client():
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import ApiCreds
    creds = None
    if POLYMARKET_API_KEY:
        creds = ApiCreds(
            api_key=POLYMARKET_API_KEY,
            api_secret=POLYMARKET_API_SECRET,
            api_passphrase=POLYMARKET_API_PASSPHRASE,
        )
    client = ClobClient(
        host=CLOB_HOST,
        key=POLYMARKET_PK,
        chain_id=CHAIN_ID,
        creds=creds,
        signature_type=SIGNATURE_TYPE,
        funder=POLYMARKET_FUNDER or None,
    )
    if not POLYMARKET_API_KEY:
        client.set_api_creds(client.create_or_derive_api_creds())
    return client


def fetch_usdc_balance(clob=None) -> float:
    """Fetch available USDC balance from Polymarket (6-decimal ERC-20)."""
    if DRY_RUN:
        return float(os.getenv("DRY_RUN_BALANCE", "100.0"))
    try:
        from py_clob_client.clob_types import AssetType, BalanceAllowanceParams
        client = clob or build_clob_client()
        data = client.get_balance_allowance(params=BalanceAllowanceParams(asset_type=AssetType.COLLATERAL))
        bal  = float(data.get("balance", 0)) / 1_000_000
        log.info("Balance: $%.2f USDC", bal)
        return bal
    except Exception as exc:
        log.warning("Balance fetch failed: %s — using BET_SIZE_MIN", exc)
        return 0.0


def kelly_size(edge: float, market_price: float, balance: float) -> float:
    """
    True quarter-Kelly: bet = balance × 0.25 × f*
    Clamped to [BET_SIZE_MIN, BET_SIZE_MAX].
    """
    if market_price <= 0 or market_price >= 1 or balance <= 0:
        return BET_SIZE_MIN
    b = (1.0 / market_price) - 1.0
    p = market_price + edge
    q = 1.0 - p
    f_kelly = max(0.0, (p * b - q) / b)
    size = balance * 0.25 * f_kelly
    return round(max(BET_SIZE_MIN, min(BET_SIZE_MAX, size)), 2)


def place_bet(clob, token: dict, size_usdc: float, condition_id: str = "", fee_rate_bps: int = 0) -> Optional[str]:
    """
    Buy the given token for `size_usdc` USDC.
    token dict must have keys: token_id, price.
    Returns order_id or None on failure.
    """
    from py_clob_client.clob_types import MarketOrderArgs, OrderType
    token_id = token.get("token_id")
    if not token_id:
        log.warning("No token_id in token dict: %s", token)
        return None
    try:
        order_args = MarketOrderArgs(token_id=token_id, amount=size_usdc, fee_rate_bps=fee_rate_bps)
        log.debug(
            "CLOB create_market_order REQUEST  token_id=%s  amount=%s  fee_rate_bps=%s",
            token_id, size_usdc, fee_rate_bps,
        )
        signed = clob.create_market_order(order_args)
        log.info("CLOB create_market_order RESPONSE  signed=%s", signed)
        log.info("CLOB post_order REQUEST  order_type=FOK  signed=%s", signed)
        resp   = clob.post_order(signed, OrderType.FOK)
        log.info("CLOB post_order RESPONSE  %s", resp)
        order_id = resp.get("orderID") or resp.get("order_id", "")
        return order_id
    except Exception as exc:
        log.error("Order failed: %s", exc)
        return None


def has_trade_on_market(clob, condition_id: str) -> bool:
    from py_clob_client.clob_types import TradeParams
    log.info("CLOB get_trades REQUEST  market=%s", condition_id)
    result = clob.get_trades(TradeParams(market=condition_id))
    if result is None:
        result = []
    log.info("CLOB get_trades RESPONSE  market=%s  count=%d  data=%s", condition_id, len(result), result)
    return len(result) > 0
