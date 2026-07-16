"""
Polymarket CLOB client: order placement, startup balance, approvals.

Fill confirmation, token balances, and order status live on the User WebSocket
(see user_ws.py). This module is strictly write-side + one-shot startup queries.
"""
from __future__ import annotations

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
    # 2026-05-06: migrated to py_clob_client_v2 after Polymarket's CLOB v2 cutover
    # (~2026-04-30). The legacy py_clob_client v0.34.6 hardcodes EIP-712
    # CLOB_VERSION="1"; v2 server rejects every signature with
    # `order_version_mismatch`. See Polymarket/py-clob-client issues #335-337.
    from py_clob_client_v2 import ClobClient, ApiCreds

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
        # v2 renamed create_or_derive_api_creds → create_or_derive_api_key.
        client.set_api_creds(client.create_or_derive_api_key())
    return client


def ensure_approvals(clob) -> None:
    from py_clob_client_v2 import AssetType, BalanceAllowanceParams

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
    from py_clob_client_v2 import AssetType, BalanceAllowanceParams

    try:
        log.info("Setting CTF conditional token approval (token=%s) ...", token_id[:16])
        clob.update_balance_allowance(
            params=BalanceAllowanceParams(asset_type=AssetType.CONDITIONAL, token_id=token_id)
        )
        log.info("CTF token approval set")
    except Exception as exc:
        log.warning("CTF approval set failed: %s", exc)


def fetch_usdc_balance(clob=None) -> float:
    """One-shot USDC balance for startup logging. Runtime balance tracking lives
    in user_ws (trade events update token_shares; USDC delta is implicit)."""
    if DRY_RUN:
        return float(os.getenv("DRY_RUN_BALANCE", "100.0"))
    try:
        from py_clob_client_v2 import AssetType, BalanceAllowanceParams

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


def place_bet(
    clob,
    token_id: str,
    shares: float,
    price: float,
    condition_id: str = "",
    fee_rate_bps: int = 0,
) -> Optional[str]:
    from py_clob_client_v2 import OrderArgs, OrderType

    try:
        # v2 OrderArgsV2 dropped fee_rate_bps + nonce + taker — fees are server-side now.
        order_args = OrderArgs(
            token_id=token_id,
            price=price,
            size=shares,
            side="BUY",
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


def sign_buy_order(
    clob,
    token_id: str,
    shares: float,
    price: float,
    fee_rate_bps: int = 0,
):
    """Build + sign a buy order without posting it. CPU-bound (~100-300ms EIP-712).

    Returned signed order is single-use; each price level / size combo needs its own.
    `fee_rate_bps` kept in signature for compatibility with callers; v2 OrderArgsV2
    handles fees server-side, so the parameter is now ignored.
    """
    from py_clob_client_v2 import OrderArgs

    order_args = OrderArgs(
        token_id=token_id,
        price=price,
        size=shares,
        side="BUY",
        expiration=0,
    )
    log.debug(
        "CLOB create_order BUY REQUEST  token=%s  price=%s  shares=%s",
        token_id, price, shares,
    )
    signed = clob.create_order(order_args)
    log.info("CLOB create_order BUY RESPONSE  %s", signed)
    return signed


def post_signed_buy(clob, signed, order_type: str = "FAK") -> tuple[Optional[str], bool, Optional[float], Optional[float]]:
    """Returns (order_id, matched, avg_fill_price, filled_shares).

    FAK fills are DOLLAR-capped (makerAmount fixed at sign time): with price
    improvement the venue returns MORE shares than requested at a lower avg
    price. takingAmount/makingAmount in the response are the fill truth —
    settling on the quoted ask misprices every improved fill (measured live
    2026-07-16: 230 shares @ ~2.1c avg on a 62-share 5c-quoted order)."""
    from py_clob_client_v2 import OrderType

    try:
        ot = OrderType.GTC if str(order_type).upper() == "GTC" else OrderType.FAK
        resp = clob.post_order(signed, ot)
        log.info("CLOB post_order BUY %s RESPONSE  %s", ot, resp)
        order_id = resp.get("orderID") or resp.get("order_id") or None
        is_matched = str(resp.get("status", "")).lower() in ("matched", "filled")
        try:
            taking = float(resp.get("takingAmount") or 0)
            making = float(resp.get("makingAmount") or 0)
        except (TypeError, ValueError):
            taking = making = 0.0
        avg_px = (making / taking) if taking > 0 and making > 0 else None
        return order_id, is_matched, avg_px, (taking if taking > 0 else None)
    except Exception as exc:
        if "does not exist" in str(exc).lower() or "no orderbook" in str(exc).lower():
            raise
        log.error("Market buy failed: %s", exc)
        return None, False, None, None


def post_signed_buy_fak(clob, signed):
    return post_signed_buy(clob, signed, "FAK")


def place_market_buy(
    clob,
    token_id: str,
    shares: float,
    price: float,
    condition_id: str = "",
    fee_rate_bps: int = 0,
) -> tuple[Optional[str], bool, Optional[float], Optional[float]]:
    """Returns (order_id, matched, avg_fill_price, filled_shares)."""
    try:
        signed = sign_buy_order(clob, token_id, shares, price, fee_rate_bps)
    except Exception as exc:
        if "does not exist" in str(exc).lower() or "no orderbook" in str(exc).lower():
            raise
        log.error("Market buy failed: %s", exc)
        return None, False, None, None
    return post_signed_buy_fak(clob, signed)


def place_limit_sell(
    clob,
    token_id: str,
    shares: float,
    price: float,
    condition_id: str = "",
    fee_rate_bps: int = 0,
) -> tuple[Optional[str], bool]:
    """Return (order_id, is_immediately_matched).

    is_immediately_matched=True when Polymarket's response shows status='matched',
    meaning the sell was fully committed off-chain and settlement is in progress.
    """
    from py_clob_client_v2 import OrderArgs, OrderType

    try:
        # v2: fee_rate_bps no longer on OrderArgsV2 (server-side fees).
        order_args = OrderArgs(
            token_id=token_id,
            price=price,
            size=shares,
            side="SELL",
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


def sign_sell_order(
    clob,
    token_id: str,
    shares: float,
    price: float,
    fee_rate_bps: int = 0,
):
    """Build + sign a sell order without posting it. CPU-bound ~100-300ms (EIP-712).

    `price` is the MIN acceptable fill for FAK — walks bid book top-down to this floor.
    Raises "not enough balance" if CLOB-side reservation check fails.
    `fee_rate_bps` kept in signature for caller compatibility; v2 handles fees server-side.
    """
    from py_clob_client_v2 import OrderArgs

    order_args = OrderArgs(
        token_id=token_id,
        price=price,
        size=shares,
        side="SELL",
    )
    log.debug(
        "CLOB create_order SELL REQUEST  token=%s  price=%s  shares=%s",
        token_id, price, shares,
    )
    signed = clob.create_order(order_args)
    log.info("CLOB create_order SELL RESPONSE  %s", signed)
    return signed


def post_signed_sell_fak(clob, signed) -> tuple[Optional[str], bool]:
    from py_clob_client_v2 import OrderType

    try:
        resp = clob.post_order(signed, OrderType.FAK)
        log.info("CLOB post_order SELL FAK RESPONSE  %s", resp)
        order_id = resp.get("orderID") or resp.get("order_id") or None
        is_matched = str(resp.get("status", "")).lower() in ("matched", "filled")
        return order_id, is_matched
    except Exception as exc:
        if "not enough balance" in str(exc).lower() or "balance is not enough" in str(exc).lower():
            raise
        log.error("Market sell failed: %s", exc)
        return None, False


def place_market_sell(
    clob,
    token_id: str,
    shares: float,
    price: float,
    condition_id: str = "",
    fee_rate_bps: int = 0,
) -> tuple[Optional[str], bool]:
    """FAK sell: fill what's available down to `price`, kill the rest.

    `price` is the MIN acceptable fill price — the order walks the bid book
    from top down until it hits this floor or the book runs out.
    Returns (order_id, is_matched). Partial fills surface via user_ws.
    """
    try:
        signed = sign_sell_order(clob, token_id, shares, price, fee_rate_bps)
    except Exception as exc:
        if "not enough balance" in str(exc).lower() or "balance is not enough" in str(exc).lower():
            raise
        log.error("Market sell failed: %s", exc)
        return None, False
    return post_signed_sell_fak(clob, signed)


def place_limit_order(
    clob,
    token_id: str,
    side: str,
    shares: float,
    price: float,
) -> Optional[str]:
    """Signed GTC limit order posted POST-ONLY (maker path — every-tick
    live_book). post_only=True makes the exchange REJECT the order if it would
    cross (execute as taker) instead of filling it — a hard maker guarantee on
    top of the caller's never-cross price guard. A rejection returns None; the
    strategy simply skips (fill-or-skip by design). Returns the order id."""
    from py_clob_client_v2 import OrderArgs, OrderType

    try:
        order_args = OrderArgs(
            token_id=token_id,
            price=price,
            size=shares,
            side=side,
            expiration=0,
        )
        log.debug(
            "CLOB create_order %s REQUEST  token=%s  price=%s  shares=%s",
            side, token_id, price, shares,
        )
        signed = clob.create_order(order_args)
        log.info("CLOB create_order %s RESPONSE  %s", side, signed)
        resp = clob.post_order(signed, OrderType.GTC, post_only=True)
        log.info("CLOB post_order %s GTC post_only RESPONSE  %s", side, resp)
        return resp.get("orderID") or resp.get("order_id") or None
    except Exception as exc:
        log.error("GTC %s post-only limit failed (crossing rejected?): %s", side, exc)
        return None


def fetch_order_status(clob, order_id: str) -> Optional[dict]:
    """One-shot REST order lookup — reconciliation fallback for the live maker
    when user_ws misses a fill. Returns the raw order dict (expected keys:
    status, size_matched, price) or None on any failure."""
    try:
        return clob.get_order(order_id)
    except Exception as exc:
        log.debug("get_order %s failed: %s", order_id, exc)
        return None


def cancel_order(clob, order_id: str) -> bool:
    # v2 renamed cancel(order_id) → cancel_order(OrderPayload(orderID=...)).
    from py_clob_client_v2 import OrderPayload

    try:
        log.info("CLOB cancel_order REQUEST  order_id=%s", order_id)
        resp = clob.cancel_order(OrderPayload(orderID=order_id))
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
