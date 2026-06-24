"""WhiteBIT exchange tools — spot trading + balances + fee/market info.

Spot trading uses the v4 trade account: orders need the API key's "Trade"
permission and funds on the TRADE account (move from main with the WhiteBIT
transfer endpoint / UI). Markets are named like "BTC_USDT".

Crypto Lending (Smart-Flex earn) IS exposed: flexible-term lending on the main
balance via `/api/v4/main-account/smart-flex/*` (list plans / invest / withdraw /
close). The separate "Smart Staking" product still has no REST API (its
`*/smart-staking/*` paths 404) — browse that one at https://whitebit.com/staking.

Env vars:
    WHITEBIT_API_KEY
    WHITEBIT_API_SECRET
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import uuid
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

_BASE = "https://whitebit.com"


def _credentials_present() -> bool:
    return bool(
        os.environ.get("WHITEBIT_API_KEY") and os.environ.get("WHITEBIT_API_SECRET")
    )


def validate() -> dict[str, Any]:
    """Smoke-test WhiteBIT creds: signed main-account balance call.
    Raises on failure (HTTP 401 / `Invalid payload.` / `Unauthorized request.`)."""
    bal = _private("/api/v4/main-account/balance") or {}
    if isinstance(bal, dict) and "code" in bal:
        raise RuntimeError(f"WhiteBIT validate failed: {bal}")
    non_zero = 0
    if isinstance(bal, dict):
        for info in bal.values():
            try:
                if isinstance(info, dict) and float(info.get("main_balance") or 0) > 0:
                    non_zero += 1
            except (TypeError, ValueError):
                continue
    return {"asset_count": len(bal) if isinstance(bal, dict) else 0, "non_zero_assets": non_zero}


def _private(path: str, params: dict[str, Any] | None = None) -> Any:
    # nonceWindow is intentionally NOT sent — it requires the API key to have
    # the nonce-window option enabled, otherwise the request 400s with
    # "Invalid payload."
    api_key = os.environ["WHITEBIT_API_KEY"]
    secret = os.environ["WHITEBIT_API_SECRET"].encode()
    body: dict[str, Any] = {k: v for k, v in (params or {}).items() if v is not None}
    body["request"] = path
    body["nonce"] = int(time.time() * 1000)
    payload_json = json.dumps(body, separators=(",", ":"))
    payload_b64 = base64.b64encode(payload_json.encode()).decode()
    signature = hmac.new(secret, payload_b64.encode(), hashlib.sha512).hexdigest()
    headers = {
        "Content-Type": "application/json",
        "X-TXC-APIKEY": api_key,
        "X-TXC-PAYLOAD": payload_b64,
        "X-TXC-SIGNATURE": signature,
    }
    r = httpx.post(_BASE + path, content=payload_json, headers=headers, timeout=20)
    r.raise_for_status()
    return r.json()


def _public(path: str, params: dict[str, Any] | None = None) -> Any:
    r = httpx.get(_BASE + path, params=params or {}, timeout=20)
    r.raise_for_status()
    return r.json()


def register(mcp: FastMCP) -> int:
    if not _credentials_present():
        return 0

    @mcp.tool()
    def whitebit_get_main_balance(ticker: str | None = None) -> Any:
        """WhiteBIT main-account balances. Pass ``ticker`` (e.g. "BTC") for a
        single asset; omit for the full wallet. Returns dict keyed by asset."""
        params = {"ticker": ticker.upper()} if ticker else None
        return _private("/api/v4/main-account/balance", params)

    @mcp.tool()
    def whitebit_get_trade_balance(ticker: str | None = None) -> Any:
        """WhiteBIT trading-account balances. Requires the API key to have the
        "Trade" permission — otherwise returns code 4 (unauthorized)."""
        params = {"ticker": ticker.upper()} if ticker else None
        return _private("/api/v4/trade-account/balance", params)

    @mcp.tool()
    def whitebit_get_collateral_balance() -> Any:
        """WhiteBIT collateral-account (futures) balances. Requires the API key
        to have the "Trade" + "Margin" permissions."""
        return _private("/api/v4/collateral-account/balance")

    @mcp.tool()
    def whitebit_get_fee_schedule() -> Any:
        """WhiteBIT deposit/withdrawal fee + min/max schedule per asset.
        Useful for figuring out cross-exchange transfer costs."""
        return _private("/api/v4/main-account/fee")

    # ----- Spot trading (v4 trade account) ------------------------------

    @mcp.tool()
    def whitebit_place_limit_order(
        market: str,
        side: str,
        amount: float,
        price: float,
        post_only: bool = False,
        ioc: bool = False,
        client_order_id: str | None = None,
    ) -> Any:
        """Place a WhiteBIT spot LIMIT order.

        market: e.g. "BTC_USDT".  side: "buy" | "sell".
        amount: size in the BASE asset.  price: limit price.
        post_only: maker-only (rejected if it would take).  ioc: immediate-or-cancel.
        """
        params: dict[str, Any] = {
            "market": market.upper(),
            "side": side.lower(),
            "amount": str(amount),
            "price": str(price),
        }
        if post_only:
            params["postOnly"] = True
        if ioc:
            params["ioc"] = True
        if client_order_id:
            params["clientOrderId"] = client_order_id
        return _private("/api/v4/order/new", params)

    @mcp.tool()
    def whitebit_place_market_order(market: str, side: str, amount: float) -> Any:
        """Place a WhiteBIT spot MARKET order by BASE-asset amount (stock_market).

        market: e.g. "BTC_USDT".  side: "buy" | "sell".  amount: BASE asset size.
        """
        return _private(
            "/api/v4/order/stock_market",
            {"market": market.upper(), "side": side.lower(), "amount": str(amount)},
        )

    @mcp.tool()
    def whitebit_cancel_order(market: str, order_id: int) -> Any:
        """Cancel a WhiteBIT spot order by market + orderId."""
        return _private(
            "/api/v4/order/cancel", {"market": market.upper(), "orderId": order_id}
        )

    @mcp.tool()
    def whitebit_get_active_orders(market: str, limit: int = 100) -> Any:
        """Active (unfilled) WhiteBIT spot orders for a market (e.g. "BTC_USDT")."""
        return _private(
            "/api/v4/orders", {"market": market.upper(), "limit": min(max(limit, 1), 100)}
        )

    # ----- Crypto Lending (Smart-Flex earn) -----------------------------
    # Flexible-term lending on the MAIN balance. Funds earn interest and can be
    # withdrawn anytime (flex). Endpoints are signed; flex plans are open to all
    # authenticated keys (the fixed-term `smart/` plans are B2B-only and not
    # exposed here). A plan is identified by its `plan` UUID everywhere.

    @mcp.tool()
    def whitebit_list_lending_plans(
        ticker: str | None = None, limit: int = 100, offset: int = 0
    ) -> Any:
        """List WhiteBIT Crypto Lending (Smart-Flex) plans with their APR and
        the `plan` UUID needed to invest. `ticker` filters by asset (e.g. "USDT")."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if ticker:
            params["ticker"] = ticker.upper()
        return _private("/api/v4/main-account/smart-flex/plans", params)

    @mcp.tool()
    def whitebit_get_lending_investments(
        ticker: str | None = None,
        status: int | None = None,
        plan: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Any:
        """Your WhiteBIT Crypto Lending positions. `status`: 1=ACTIVE, 0=CLOSED.
        Filter by `ticker` or `plan` (UUID)."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if ticker:
            params["ticker"] = ticker.upper()
        if status is not None:
            params["investmentStatus"] = status
        if plan:
            params["plan"] = plan
        return _private("/api/v4/main-account/smart-flex/investments", params)

    @mcp.tool()
    def whitebit_lending_invest(
        plan: str, amount: float, with_reinvest: bool = False
    ) -> Any:
        """Invest (lend) `amount` into a WhiteBIT Smart-Flex plan by its `plan`
        UUID (from whitebit_list_lending_plans). Funds come from the MAIN balance.
        with_reinvest=True compounds interest automatically."""
        params: dict[str, Any] = {"plan": plan, "amount": str(amount)}
        if with_reinvest:
            params["withReinvest"] = True
        return _private("/api/v4/main-account/smart-flex/investments/invest", params)

    @mcp.tool()
    def whitebit_lending_withdraw(plan: str, amount: float) -> Any:
        """Withdraw `amount` from a WhiteBIT Smart-Flex lending position (by `plan`
        UUID) back to the main balance. Flex = available anytime."""
        return _private(
            "/api/v4/main-account/smart-flex/investments/withdraw",
            {"plan": plan, "amount": str(amount)},
        )

    @mcp.tool()
    def whitebit_lending_close(plan: str) -> Any:
        """Fully close a WhiteBIT Smart-Flex lending position (by `plan` UUID) and
        return all funds to the main balance."""
        return _private(
            "/api/v4/main-account/smart-flex/investments/close", {"plan": plan}
        )

    @mcp.tool()
    def whitebit_get_lending_payment_history(
        ticker: str | None = None, limit: int = 100, offset: int = 0
    ) -> Any:
        """Interest-payment history for WhiteBIT Crypto Lending (earnings accrued)."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if ticker:
            params["ticker"] = ticker.upper()
        return _private(
            "/api/v4/main-account/smart-flex/investments/payment-history", params
        )

    # ----- Funding: deposit / withdraw / internal transfer --------------

    @mcp.tool()
    def whitebit_get_deposit_address(ticker: str, network: str | None = None) -> Any:
        """WhiteBIT deposit address for `ticker` (e.g. "USDT"). `network` is
        required for multi-network assets (e.g. "ARBITRUM", "ERC20", "TRC20").
        Give this address to the SENDING venue to move funds INTO WhiteBIT."""
        params: dict[str, Any] = {"ticker": ticker.upper()}
        if network:
            params["network"] = network
        return _private("/api/v4/main-account/address", params)

    @mcp.tool()
    def whitebit_withdraw(
        ticker: str,
        amount: float,
        address: str,
        network: str | None = None,
        memo: str | None = None,
        unique_id: str | None = None,
        confirm: bool = False,
    ) -> Any:
        """Withdraw crypto from WhiteBIT (main balance) to `address`.

        amount must INCLUDE the network fee. `network` is required for
        multi-network assets (USDT defaults to ERC20). `memo` only for memoable
        coins. `unique_id` is auto-generated if omitted.

        Safety: confirm=False (default) returns the intended params WITHOUT
        sending. Set confirm=True to actually submit."""
        params: dict[str, Any] = {
            "ticker": ticker.upper(),
            "amount": str(amount),
            "address": address,
            "unique_id": unique_id or uuid.uuid4().hex,
        }
        if network:
            params["network"] = network
        if memo:
            params["memo"] = memo
        if not confirm:
            return {
                "dry_run": True,
                "would_withdraw": params,
                "warning": "Set confirm=True to submit. amount must include the network fee.",
            }
        return _private("/api/v4/main-account/withdraw", params)

    @mcp.tool()
    def whitebit_transfer(
        ticker: str, amount: float, from_account: str, to_account: str
    ) -> Any:
        """Move funds between WhiteBIT balances. from_account/to_account ∈
        {"main", "spot", "collateral"}. Trading uses "spot"; Crypto Lending uses
        "main" — so fund lending/withdrawals on main, and spot orders on spot."""
        return _private(
            "/api/v4/main-account/transfer",
            {
                "ticker": ticker.upper(),
                "amount": str(amount),
                "from": from_account.lower(),
                "to": to_account.lower(),
            },
        )

    @mcp.tool()
    def whitebit_smart_staking_info() -> dict[str, Any]:
        """WhiteBIT **Smart Staking** (the staking product) has no REST API as of
        2026-06 — browse it in the web UI. NOTE: WhiteBIT **Crypto Lending**
        (Smart-Flex) IS available via API — use `whitebit_list_lending_plans` /
        `whitebit_lending_invest` for that yield instead."""
        return {
            "smart_staking_available_via_api": False,
            "browse_url": "https://whitebit.com/staking",
            "lending_available_via_api": True,
            "lending_tools": [
                "whitebit_list_lending_plans",
                "whitebit_get_lending_investments",
                "whitebit_lending_invest",
                "whitebit_lending_withdraw",
                "whitebit_lending_close",
            ],
        }

    return 18
