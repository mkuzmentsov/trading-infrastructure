"""
Polymarket CLOB client: order placement, balance, sizing, and trade queries.
"""
from __future__ import annotations

import math
import os
from typing import Any, Optional

from config import (
    CHAIN_ID,
    CLOB_HOST,
    DRY_RUN,
    POLYMARKET_API_KEY,
    POLYMARKET_API_PASSPHRASE,
    POLYMARKET_API_SECRET,
    POLYMARKET_FUNDER,
    POLYMARKET_PK,
    SIGNATURE_TYPE,
    log,
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


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _order_view(resp: Any) -> dict:
    if not isinstance(resp, dict):
        return {}
    order = resp.get("order")
    if isinstance(order, dict):
        merged = dict(order)
        merged.update(resp)
        return merged
    return resp


def _first_number(data: dict, *keys: str) -> float | None:
    for key in keys:
        if key in data:
            val = _as_float(data.get(key))
            if val is not None:
                return val
    return None


def ensure_approvals(clob) -> None:
    from py_clob_client.clob_types import AssetType, BalanceAllowanceParams

    try:
        data = clob.get_balance_allowance(
            params=BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
        )
        allowance = int(data.get("allowance", 0))
        if allowance < 1_000_000_000_000:
            log.info("USDC allowance low (%d) — updating ...", allowance)
            clob.update_balance_allowance(
                params=BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
            )
            log.info("USDC allowance updated")
        else:
            log.info("USDC allowance OK  (%d)", allowance)
    except Exception as exc:
        log.warning("USDC approval check failed: %s", exc)


def ensure_ctf_approval(clob, token_id: str) -> None:
    from py_clob_client.clob_types import AssetType, BalanceAllowanceParams

    try:
        log.info("Setting CTF conditional token approval (token=%s) ...", token_id[:16])
        clob.update_balance_allowance(
            params=BalanceAllowanceParams(asset_type=AssetType.CONDITIONAL, token_id=token_id)
        )
        log.info("CTF token approval set")
    except Exception as exc:
        log.warning("CTF approval set failed: %s", exc)


def fetch_usdc_balance(clob=None) -> float:
    if DRY_RUN:
        return float(os.getenv("DRY_RUN_BALANCE", "100.0"))
    try:
        from py_clob_client.clob_types import AssetType, BalanceAllowanceParams

        client = clob or build_clob_client()
        data = client.get_balance_allowance(
            params=BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
        )
        bal = float(data.get("balance", 0)) / 1_000_000
        log.info("Balance: $%.2f USDC", bal)
        return bal
    except Exception as exc:
        log.warning("Balance fetch failed: %s", exc)
        return 0.0


def fetch_token_balance(clob, token_id: str) -> float:
    """Fetch conditional token balance in whole-share units (6 decimals on-chain)."""
    try:
        from py_clob_client.clob_types import AssetType, BalanceAllowanceParams

        data = clob.get_balance_allowance(
            params=BalanceAllowanceParams(asset_type=AssetType.CONDITIONAL, token_id=token_id)
        )
        bal = float(data.get("balance", 0)) / 1_000_000
        log.info("Token balance  token=%s  balance=%.6f", token_id[:16], bal)
        return bal
    except Exception as exc:
        log.warning("Token balance fetch failed for %s: %s", token_id[:16], exc)
        return 0.0


def place_bet(
    clob,
    token_id: str,
    shares: int,
    price: float,
    condition_id: str = "",
    fee_rate_bps: int = 0,
) -> Optional[str]:
    from py_clob_client.clob_types import OrderArgs, OrderType

    try:
        order_args = OrderArgs(
            token_id=token_id,
            price=price,
            size=shares,
            side="BUY",
            fee_rate_bps=fee_rate_bps,
            expiration=0,
        )
        log.debug(
            "CLOB create_order BUY REQUEST  token=%s  price=%s  shares=%s",
            token_id, price, shares,
        )
        signed = clob.create_order(order_args)
        log.info("CLOB create_order BUY RESPONSE  %s", signed)
        resp = clob.post_order(signed, OrderType.GTC)
        log.info("CLOB post_order BUY GTC RESPONSE  %s", resp)
        return resp.get("orderID") or resp.get("order_id") or None
    except Exception as exc:
        if "does not exist" in str(exc).lower() or "no orderbook" in str(exc).lower():
            raise
        log.error("Order failed: %s", exc)
        return None


def has_trade_on_market(clob, condition_id: str) -> bool:
    from py_clob_client.clob_types import TradeParams

    log.info("CLOB get_trades REQUEST  market=%s", condition_id)
    result = clob.get_trades(TradeParams(market=condition_id))
    if result is None:
        result = []
    log.info("CLOB get_trades RESPONSE  market=%s  count=%d", condition_id, len(result))
    return len(result) > 0


def place_limit_sell(
    clob,
    token_id: str,
    shares: int,
    price: float,
    condition_id: str = "",
    fee_rate_bps: int = 0,
) -> tuple[Optional[str], bool]:
    """Return (order_id, is_immediately_matched).

    is_immediately_matched=True when Polymarket's response shows status='matched',
    meaning the sell was fully committed off-chain and settlement is in progress.
    In that case the caller should close the position immediately without re-querying
    token balance, which lags behind off-chain state during settlement.
    """
    from py_clob_client.clob_types import OrderArgs, OrderType

    try:
        order_args = OrderArgs(
            token_id=token_id,
            price=price,
            size=shares,
            side="SELL",
            fee_rate_bps=fee_rate_bps,
        )
        log.debug("CLOB create_order SELL REQUEST  token=%s  price=%s  shares=%s", token_id, price, shares)
        signed = clob.create_order(order_args)
        log.info("CLOB create_order SELL RESPONSE  %s", signed)
        resp = clob.post_order(signed, OrderType.GTC)
        log.info("CLOB post_order SELL GTC RESPONSE  %s", resp)
        order_id = resp.get("orderID") or resp.get("order_id") or None
        is_matched = str(resp.get("status", "")).lower() in ("matched", "filled")
        return order_id, is_matched
    except Exception as exc:
        if "not enough balance" in str(exc).lower() or "balance is not enough" in str(exc).lower():
            raise
        log.error("Limit sell failed: %s", exc)
        return None, False


def cancel_order(clob, order_id: str) -> bool:
    try:
        log.info("CLOB cancel_order REQUEST  order_id=%s", order_id)
        resp = clob.cancel(order_id)
        log.info("CLOB cancel_order RESPONSE  %s", resp)
        if isinstance(resp, dict):
            canceled = resp.get("canceled") or []
            not_canceled = resp.get("not_canceled") or {}
            if order_id in canceled:
                return True
            if order_id in not_canceled:
                return False
            if canceled or not_canceled:
                return False
        return True
    except Exception as exc:
        log.warning("Cancel order %s failed: %s", order_id, exc)
        return False


def get_order_details(clob, order_id: str) -> dict:
    try:
        log.debug("CLOB get_order REQUEST  order_id=%s", order_id)
        resp = clob.get_order(order_id)
        log.debug("CLOB get_order RESPONSE  %s", resp)
        return _order_view(resp)
    except Exception as exc:
        log.warning("get_order_details %s failed: %s", order_id, exc)
        return {}


def get_order_status(clob, order_id: str) -> str:
    resp = get_order_details(clob, order_id)
    status = str(resp.get("status") or "").lower()
    if status in ("matched", "filled"):
        return "filled"
    if status in ("cancelled", "canceled", "expired"):
        return "cancelled"
    if status in ("open", "live"):
        return "open"
    return status or "unknown"


def get_order_fill_info(clob, order_id: str, fallback_price: float, fallback_shares: int) -> tuple[str, int, float]:
    """Return (status, matched_whole_shares, avg_price) for an order."""
    resp = get_order_details(clob, order_id)
    status = str(resp.get("status") or "").lower()
    if status in ("matched", "filled"):
        norm_status = "filled"
    elif status in ("cancelled", "canceled", "expired"):
        norm_status = "cancelled"
    elif status in ("open", "live"):
        norm_status = "open"
    else:
        norm_status = status or "unknown"

    matched = _first_number(
        resp,
        "size_matched",
        "sizeMatched",
        "matched_size",
        "matchedSize",
        "filled_size",
        "filledSize",
        "original_size",
        "originalSize",
        "size",
        "makingAmount",
    )
    if matched is None:
        matched_shares = fallback_shares if norm_status == "filled" else 0
    else:
        matched_shares = max(0, int(math.floor(matched)))

    avg_price = _first_number(
        resp,
        "avg_price",
        "avgPrice",
        "average_price",
        "averagePrice",
        "price",
    )
    if avg_price is None or avg_price <= 0:
        avg_price = fallback_price

    return norm_status, matched_shares, float(avg_price)
