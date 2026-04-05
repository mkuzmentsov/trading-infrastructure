"""
Polymarket CLOB client: order placement, balance, sizing, and trade queries.
"""
from __future__ import annotations

import os
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


def ensure_approvals(clob) -> None:
    """
    Check and set on-chain approvals required for trading.

    1. USDC collateral allowance — needed to buy tokens.
    2. CTF conditional token allowance — needed for limit sell orders.
       Without this, all limit sells fail with 'balance: 0'.
    """
    from py_clob_client.clob_types import AssetType, BalanceAllowanceParams

    # ── USDC collateral ───────────────────────────────────────────────────────
    try:
        data = clob.get_balance_allowance(
            params=BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
        )
        allowance = int(data.get("allowance", 0))
        if allowance < 1_000_000_000_000:   # < 1 million USDC
            log.info("USDC allowance low (%d) — updating ...", allowance)
            clob.update_balance_allowance(
                params=BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
            )
            log.info("USDC allowance updated")
        else:
            log.info("USDC allowance OK  (%d)", allowance)
    except Exception as exc:
        log.warning("USDC approval check failed: %s", exc)

    # CTF conditional token approval is done separately in ensure_ctf_approval()
    # because it requires a valid token_id (ERC-1155) unavailable at startup.


def ensure_ctf_approval(clob, token_id: str) -> None:
    """
    Set setApprovalForAll on the CTF Exchange for conditional tokens.
    Must be called with a valid token_id (ERC-1155 requirement).
    Idempotent — safe to call every startup.
    """
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
        log.warning("Balance fetch failed: %s", exc)
        return 0.0


def place_bet(
    clob,
    token_id: str,
    shares: int,
    price: float,
    condition_id: str = "",
    fee_rate_bps: int = 0,
) -> Optional[str]:
    """
    Place a GTC limit BUY order for `shares` tokens at `price`.

    Uses a limit order (not market FOK) so the order rests in the book if
    there is no immediate liquidity — solving the 'no match' problem.
    expiration must be 0 for GTC orders (non-zero is only valid for GTD).

    Returns order_id or None on failure.
    """
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
        if "does not exist" in str(exc).lower() or "No orderbook" in str(exc):
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
) -> Optional[str]:
    """
    Post a GTC limit sell order for `shares` at `price`.
    Returns order_id or None on failure.
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
        return resp.get("orderID") or resp.get("order_id") or None
    except Exception as exc:
        if "not enough balance" in str(exc).lower() or "balance is not enough" in str(exc).lower():
            raise   # let caller handle partial-fill retry
        log.error("Limit sell failed: %s", exc)
        return None


def cancel_order(clob, order_id: str) -> bool:
    """Cancel an open order by ID. Returns True on success."""
    try:
        log.info("CLOB cancel_order REQUEST  order_id=%s", order_id)
        resp = clob.cancel(order_id)
        log.info("CLOB cancel_order RESPONSE  %s", resp)
        return True
    except Exception as exc:
        log.warning("Cancel order %s failed: %s", order_id, exc)
        return False


def get_order_status(clob, order_id: str) -> str:
    """
    Return order status string: 'filled', 'open', 'cancelled', 'unknown'.
    """
    try:
        log.debug("CLOB get_order REQUEST  order_id=%s", order_id)
        resp = clob.get_order(order_id)
        log.debug("CLOB get_order RESPONSE  %s", resp)
        status = (resp.get("status") or "").lower()
        if status in ("matched", "filled"):
            return "filled"
        if status in ("cancelled", "canceled", "expired"):
            return "cancelled"
        if status in ("open", "live"):
            return "open"
        return status or "unknown"
    except Exception as exc:
        log.warning("get_order_status %s failed: %s", order_id, exc)
        return "unknown"
