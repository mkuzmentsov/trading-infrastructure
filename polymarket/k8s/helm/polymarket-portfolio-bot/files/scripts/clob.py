"""CLOB client, balance checks, order placement, price fetch."""
from __future__ import annotations

import logging
import math
import time
from typing import Optional

import requests

from config import (
    CHAIN_ID,
    CLOB_HOST,
    DRY_RUN,
    POLYMARKET_FUNDER,
    POLYMARKET_PK,
    POLYMARKET_SIGNATURE_TYPE,
)

logger = logging.getLogger(__name__)

_cached_clob_client = None


def get_clob_client():
    global _cached_clob_client
    if _cached_clob_client is not None:
        return _cached_clob_client
    from py_clob_client.client import ClobClient
    client = ClobClient(
        host=CLOB_HOST,
        chain_id=CHAIN_ID,
        key=POLYMARKET_PK,
        signature_type=POLYMARKET_SIGNATURE_TYPE,
        funder=POLYMARKET_FUNDER if POLYMARKET_FUNDER else None,
    )
    client.set_api_creds(client.create_or_derive_api_creds())
    logger.info(f"  CLOB client ready  address={client.get_address()}  sig_type={POLYMARKET_SIGNATURE_TYPE}")
    _cached_clob_client = client
    return client


def ensure_allowances() -> None:
    if DRY_RUN:
        return
    try:
        from py_clob_client.clob_types import AssetType, BalanceAllowanceParams
        clob = get_clob_client()
        result = clob.update_balance_allowance(params=BalanceAllowanceParams(asset_type=AssetType.COLLATERAL))
        logger.info(f"  update_balance_allowance: {result}")
    except Exception as e:
        logger.warning(f"  Allowance update failed: {e}")


def _is_active_order(order: dict) -> bool:
    status = str(order.get("status") or order.get("orderStatus") or "").lower()
    if not status:
        return True
    return status not in {"matched", "filled", "cancelled", "canceled", "expired"}


def _order_token_id(order: dict) -> str:
    return str(
        order.get("asset_id")
        or order.get("assetId")
        or order.get("token_id")
        or order.get("tokenId")
        or ""
    )


def _order_id(order: dict) -> str:
    return str(order.get("id") or order.get("orderID") or order.get("order_id") or "")


def cancel_active_orders_for_token(token_id: str) -> int:
    """Cancel active orders for a token so its balance is free for a replacement exit."""
    if DRY_RUN:
        return 0
    try:
        clob = get_clob_client()
        orders = clob.get_orders() or []
    except Exception as e:
        logger.warning(f"  get_orders failed before sell: {e}")
        return 0

    canceled = 0
    for order in orders:
        if not isinstance(order, dict) or not _is_active_order(order):
            continue
        if _order_token_id(order) != token_id:
            continue
        order_id = _order_id(order)
        if not order_id:
            continue
        try:
            logger.info(f"  Cancelling active order before SELL  token={token_id[:16]}… order_id={order_id}")
            resp = clob.cancel(order_id)
            logger.info(f"  cancel response: {resp}")
            canceled += 1
        except Exception as e:
            logger.warning(f"  Cancel order {order_id} failed: {e}")

    if canceled:
        # Let the exchange release reserved balance before reposting the exit.
        time.sleep(1.0)
    return canceled


def fetch_usdc_balance() -> float:
    if DRY_RUN:
        logger.info("  Balance: DRY RUN — simulated $500.00")
        return 500.0
    try:
        from py_clob_client.clob_types import AssetType, BalanceAllowanceParams
        clob = get_clob_client()
        data = clob.get_balance_allowance(params=BalanceAllowanceParams(asset_type=AssetType.COLLATERAL))
        bal  = float(data.get("balance", 0)) / 1_000_000
        logger.info(f"  Balance: ${bal:.2f} USDC")
        return bal
    except Exception as e:
        logger.warning(f"  Balance check failed: {e}")
        return 0.0


def fetch_current_price(token_id: str) -> Optional[float]:
    """Get the current midpoint price for a specific outcome token."""
    try:
        resp = requests.get(f"{CLOB_HOST}/midpoint", params={"token_id": token_id}, timeout=10)
        if resp.status_code == 200:
            return float(resp.json().get("mid") or 0)
    except Exception as e:
        logger.warning(f"  midpoint fetch failed: {e}")
    return None


def place_buy(token_id: str, limit_price: float, usdc_size: float, neg_risk: bool, label: str = "") -> Optional[str]:
    limit_price = round(min(max(limit_price, 0.01), 0.97), 4)
    if DRY_RUN:
        logger.info(f"  [DRY RUN] BUY {label} @ {limit_price:.3f}  ${usdc_size:.2f} USDC")
        return f"DRY-BUY-{int(time.time())}"
    try:
        from py_clob_client.clob_types import OrderArgs, OrderType, PartialCreateOrderOptions
        from py_clob_client.order_builder.constants import BUY
        clob = get_clob_client()
        size_shares = max(1.0, math.ceil(usdc_size / limit_price * 100) / 100)
        order = clob.create_order(
            OrderArgs(token_id=token_id, price=limit_price, size=size_shares, side=BUY),
            options=PartialCreateOrderOptions(neg_risk=neg_risk),
        )
        result = clob.post_order(order, OrderType.GTC)
        logger.info(f"  BUY post_order: {result}")
        if result and result.get("success"):
            return result.get("orderID") or result.get("order_id") or "unknown"
        logger.error(f"  BUY rejected: {result}")
        return None
    except Exception as e:
        logger.error(f"  BUY failed: {e}", exc_info=True)
        return None


def place_sell(token_id: str, size_shares: float, neg_risk: bool, label: str = "") -> Optional[str]:
    """Sell shares at a small discount to current midpoint to ensure fill."""
    mid = fetch_current_price(token_id) or 0.5
    limit_price = round(max(mid - 0.01, 0.01), 4)
    if DRY_RUN:
        logger.info(f"  [DRY RUN] SELL {label}  size={size_shares}  @ {limit_price:.3f}")
        return f"DRY-SELL-{int(time.time())}"
    try:
        from py_clob_client.clob_types import OrderArgs, OrderType, PartialCreateOrderOptions
        from py_clob_client.order_builder.constants import SELL
        clob = get_clob_client()
        canceled = cancel_active_orders_for_token(token_id)
        if canceled:
            logger.info(f"  Freed token balance by cancelling {canceled} active order(s) for {label or token_id[:16]}")
        size = max(1.0, math.floor(size_shares * 100) / 100)
        order = clob.create_order(
            OrderArgs(token_id=token_id, price=limit_price, size=size, side=SELL),
            options=PartialCreateOrderOptions(neg_risk=neg_risk),
        )
        result = clob.post_order(order, OrderType.GTC)
        logger.info(f"  SELL post_order: {result}")
        if result and result.get("success"):
            return result.get("orderID") or result.get("order_id") or "unknown"
        logger.error(f"  SELL rejected: {result}")
        return None
    except Exception as e:
        logger.error(f"  SELL failed: {e}", exc_info=True)
        return None
