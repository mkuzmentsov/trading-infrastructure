"""Bybit exchange tools — Unified account (balances / spot + perp trade / funding).

Uses the Bybit V5 REST API directly (raw httpx + manual signing, no SDK). One
Unified Trading Account (UTA) holds spot, linear perps and collateral together,
so ``accountType=UNIFIED`` is the account used throughout.

Auth (Bybit V5): every signed request sends the headers
    X-BAPI-API-KEY      = api key
    X-BAPI-TIMESTAMP    = current time in ms (as a string)
    X-BAPI-RECV-WINDOW  = "5000"
    X-BAPI-SIGN         = hex HMAC-SHA256(secret, message)
where ``message = timestamp + api_key + recv_window + payload`` and ``payload``
is the raw query string (GET) or the raw JSON body string (POST). The SAME
string that is signed is the one actually sent on the wire. Responses wrap data
as ``{"retCode":0,"retMsg":"OK","result":{...}}`` — a non-zero retCode raises.

Symbols are exchange-native, e.g. "BTCUSDT" (spot) / "BTCUSDT" (linear perp).

Env vars:
    BYBIT_API_KEY
    BYBIT_API_SECRET
"""

from __future__ import annotations

import base64  # noqa: F401  (kept for parity with sibling exchange modules)
import hashlib
import hmac
import json
import os
import time
import urllib.parse
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

_BASE = "https://api.bybit.com"
_RECV_WINDOW = "5000"


def _credentials_present() -> bool:
    return bool(
        os.environ.get("BYBIT_API_KEY") and os.environ.get("BYBIT_API_SECRET")
    )


def _sign(timestamp: str, api_key: str, payload: str, secret: str) -> str:
    """Bybit V5 signature: hex HMAC-SHA256 over
    timestamp + api_key + recv_window + payload."""
    message = timestamp + api_key + _RECV_WINDOW + payload
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()


def _request(
    method: str,
    path: str,
    params: dict[str, Any] | None = None,
    signed: bool = True,
) -> dict[str, Any]:
    """Call a Bybit V5 endpoint, e.g. "/v5/account/wallet-balance".

    GET: params become a sorted, urlencoded query string that is BOTH appended
    to the URL and signed. POST: params become a compact JSON body that is BOTH
    sent as the request body and signed. Returns ``result``; raises RuntimeError
    on a non-zero retCode."""
    clean = {k: v for k, v in (params or {}).items() if v is not None}
    method = method.upper()
    headers = {"Accept": "application/json"}
    if method == "GET":
        payload = urllib.parse.urlencode(sorted(clean.items()))
        url = _BASE + path + (f"?{payload}" if payload else "")
        content: str | None = None
    else:
        payload = json.dumps(clean, separators=(",", ":"))
        url = _BASE + path
        content = payload
        headers["Content-Type"] = "application/json"

    if signed:
        api_key = os.environ["BYBIT_API_KEY"]
        timestamp = str(int(time.time() * 1000))
        headers.update(
            {
                "X-BAPI-API-KEY": api_key,
                "X-BAPI-TIMESTAMP": timestamp,
                "X-BAPI-RECV-WINDOW": _RECV_WINDOW,
                "X-BAPI-SIGN": _sign(
                    timestamp, api_key, payload, os.environ["BYBIT_API_SECRET"]
                ),
            }
        )

    r = httpx.request(method, url, headers=headers, content=content, timeout=20)
    r.raise_for_status()
    data = r.json()
    if data.get("retCode") != 0:
        raise RuntimeError(
            f"Bybit error {data.get('retCode')}: {data.get('retMsg')}"
        )
    return data.get("result") or {}


def validate() -> dict[str, Any]:
    """Smoke-test Bybit creds: signed UNIFIED wallet-balance call.
    Raises on a bad signature / permission error."""
    result = _request(
        "GET", "/v5/account/wallet-balance", {"accountType": "UNIFIED"}
    )
    account = (result.get("list") or [{}])[0]
    coins = account.get("coin") or []
    return {
        "account_type": account.get("accountType") or "UNIFIED",
        "coin_count": len(coins),
        "total_equity": account.get("totalEquity"),
    }


def register(mcp: FastMCP) -> int:
    if not _credentials_present():
        return 0

    # ----- Account -------------------------------------------------------

    @mcp.tool()
    def bybit_get_balances() -> dict[str, Any]:
        """Bybit UNIFIED account wallet balance: total equity plus a per-coin
        list trimmed to coins with a non-zero wallet balance."""
        result = _request(
            "GET", "/v5/account/wallet-balance", {"accountType": "UNIFIED"}
        )
        account = (result.get("list") or [{}])[0]
        coins = []
        for c in account.get("coin") or []:
            try:
                if float(c.get("walletBalance") or 0) != 0:
                    coins.append(c)
            except (TypeError, ValueError):
                continue
        return {
            "account_type": account.get("accountType"),
            "total_equity": account.get("totalEquity"),
            "total_available_balance": account.get("totalAvailableBalance"),
            "coins": coins,
        }

    @mcp.tool()
    def bybit_get_perp_positions() -> dict[str, Any]:
        """Open Bybit linear (USDT-settled) perp positions: symbol, side, size,
        entry, leverage, unrealised PnL."""
        return _request(
            "GET",
            "/v5/position/list",
            {"category": "linear", "settleCoin": "USDT"},
        )

    # ----- Market data (public) -----------------------------------------

    @mcp.tool()
    def bybit_get_orderbook(symbol: str, limit: int = 10) -> dict[str, Any]:
        """Bybit SPOT order book for `symbol` (e.g. "BTCUSDT"): best bid/ask,
        spread (bps), top levels. Short/sell fills at the bid."""
        sym = symbol.upper()
        result = _request(
            "GET",
            "/v5/market/orderbook",
            {"category": "spot", "symbol": sym, "limit": limit},
            signed=False,
        )
        bids = [[float(p), float(q)] for p, q in (result.get("b") or [])]
        asks = [[float(p), float(q)] for p, q in (result.get("a") or [])]
        bb = bids[0][0] if bids else None
        ba = asks[0][0] if asks else None
        return {
            "symbol": sym,
            "best_bid": bb,
            "best_ask": ba,
            "spread_bps": (ba - bb) / bb * 1e4 if bb and ba else None,
            "bids": bids,
            "asks": asks,
        }

    @mcp.tool()
    def bybit_get_funding_rates() -> dict[str, Any]:
        """Bybit linear (USDT) perp funding across all symbols, sorted by APR
        desc. Bybit funds every 8h (3×/day), so hourly = fundingRate/8 and
        apr = fundingRate × 3 × 365. Also returns mark price + open interest."""
        result = _request(
            "GET", "/v5/market/tickers", {"category": "linear"}, signed=False
        )
        out = []
        for t in result.get("list") or []:
            sym = t.get("symbol") or ""
            fr = t.get("fundingRate")
            if fr in (None, ""):
                continue
            try:
                fr_f = float(fr)
            except (TypeError, ValueError):
                continue
            out.append(
                {
                    "coin": sym.replace("USDT", ""),
                    "symbol": sym,
                    "hourly": fr_f / 8,
                    "apr": fr_f * 3 * 365,
                    "mark_px": t.get("markPrice"),
                    "open_interest": t.get("openInterest"),
                }
            )
        out.sort(key=lambda x: x["apr"], reverse=True)
        return {"funding_rates": out}

    # ----- Trading -------------------------------------------------------

    @mcp.tool()
    def bybit_place_spot_order(
        symbol: str,
        side: str,
        order_type: str = "Limit",
        qty: float | None = None,
        price: float | None = None,
    ) -> dict[str, Any]:
        """Place a Bybit SPOT order (order/create, category="spot").

        symbol: e.g. "BTCUSDT".  side: "Buy" | "Sell".
        order_type: "Limit" (needs price) | "Market".
        qty: order quantity (base asset; for a spot Market buy this is quote).
        """
        params: dict[str, Any] = {
            "category": "spot",
            "symbol": symbol.upper(),
            "side": side.capitalize(),
            "orderType": order_type.capitalize(),
        }
        if qty is not None:
            params["qty"] = str(qty)
        if price is not None:
            params["price"] = str(price)
        return _request("POST", "/v5/order/create", params)

    @mcp.tool()
    def bybit_place_perp_order(
        symbol: str,
        side: str,
        order_type: str = "Limit",
        qty: float | None = None,
        price: float | None = None,
        reduce_only: bool = False,
    ) -> dict[str, Any]:
        """Place a Bybit linear PERP order (order/create, category="linear").

        symbol: e.g. "BTCUSDT".  side: "Buy" | "Sell".
        order_type: "Limit" (needs price) | "Market".  qty: contracts (base).
        reduce_only: True = only reduce/close an existing position.
        """
        params: dict[str, Any] = {
            "category": "linear",
            "symbol": symbol.upper(),
            "side": side.capitalize(),
            "orderType": order_type.capitalize(),
        }
        if qty is not None:
            params["qty"] = str(qty)
        if price is not None:
            params["price"] = str(price)
        if reduce_only:
            params["reduceOnly"] = True
        return _request("POST", "/v5/order/create", params)

    # ----- Funding: deposit / withdraw ----------------------------------

    @mcp.tool()
    def bybit_get_deposit_address(coin: str, chain: str | None = None) -> dict[str, Any]:
        """Bybit deposit address for `coin` (e.g. "USDT"). `chain` selects the
        network for multi-network assets (e.g. "ARBI", "ETH", "TRX"). Give this
        address to the SENDING venue to move funds INTO Bybit."""
        params: dict[str, Any] = {"coin": coin.upper()}
        if chain:
            params["chainType"] = chain
        return _request("GET", "/v5/asset/deposit/query-address", params)

    @mcp.tool()
    def bybit_withdraw(
        coin: str,
        address: str,
        amount: float,
        chain: str,
        confirm: bool = False,
    ) -> dict[str, Any]:
        """Withdraw crypto from Bybit to `address` (asset/withdraw/create).

        coin: e.g. "USDT".  chain: network (e.g. "ARBI", "ETH", "TRX").
        amount: quantity to send.

        Safety: confirm=False (default) returns the intended params WITHOUT
        sending. Set confirm=True to actually submit."""
        params: dict[str, Any] = {
            "coin": coin.upper(),
            "chain": chain,
            "address": address,
            "amount": str(amount),
            "timestamp": int(time.time() * 1000),
        }
        if not confirm:
            return {
                "dry_run": True,
                "would_withdraw": params,
                "warning": "set confirm=True to submit",
            }
        return _request("POST", "/v5/asset/withdraw/create", params)

    # ----- Earn (Savings) ------------------------------------------------

    @mcp.tool()
    def bybit_list_earn_products(
        coin: str | None = None, category: str = "FlexibleSaving"
    ) -> dict[str, Any]:
        """Bybit Earn products + estimated APR. category: "FlexibleSaving"
        (instant, preferred for a hedge) or "OnChain"."""
        params: dict[str, Any] = {"category": category}
        if coin:
            params["coin"] = coin.upper()
        return _request("GET", "/v5/earn/product", params)

    @mcp.tool()
    def bybit_get_earn_positions(category: str = "FlexibleSaving") -> dict[str, Any]:
        """Current Bybit Earn holdings for a category."""
        return _request("GET", "/v5/earn/position", {"category": category})

    @mcp.tool()
    def bybit_find_best_earn_rates(
        coin: str | None = None, top_n: int = 10
    ) -> dict[str, Any]:
        """Rank Bybit Earn products by estimated APR (highest first)."""
        result = bybit_list_earn_products(coin=coin, category="FlexibleSaving")

        def _apr(p: dict[str, Any]) -> float:
            v = p.get("estimateApr")
            if v is None:
                return 0.0
            try:
                raw = str(v).strip()
                f = float(raw.replace("%", ""))
                return f / 100 if ("%" in raw or f > 1) else f
            except (TypeError, ValueError):
                return 0.0

        items = sorted(result.get("list") or [], key=_apr, reverse=True)[:top_n]
        return {"top": [
            {"coin": p.get("coin"), "productId": p.get("productId"),
             "estimateApr": p.get("estimateApr"), "apr_frac": _apr(p),
             "category": p.get("category"), "status": p.get("status"),
             "minStakeAmount": p.get("minStakeAmount")}
            for p in items
        ]}

    @mcp.tool()
    def bybit_earn_subscribe(
        product_id: str, coin: str, amount: float, account_type: str = "UNIFIED"
    ) -> dict[str, Any]:
        """Stake into a Bybit Earn product (earn-place-order, Stake). Use a
        FlexibleSaving product so the hedge stays instantly redeemable."""
        return _request("POST", "/v5/earn/place-order", {
            "category": "FlexibleSaving", "orderType": "Stake",
            "accountType": account_type, "amount": str(amount),
            "coin": coin.upper(), "productId": product_id,
            "orderLinkId": f"mcp{int(time.time() * 1000)}",
        })

    @mcp.tool()
    def bybit_earn_redeem(
        product_id: str, coin: str, amount: float, account_type: str = "UNIFIED"
    ) -> dict[str, Any]:
        """Redeem from a Bybit Earn product (earn-place-order, Redeem)."""
        return _request("POST", "/v5/earn/place-order", {
            "category": "FlexibleSaving", "orderType": "Redeem",
            "accountType": account_type, "amount": str(amount),
            "coin": coin.upper(), "productId": product_id,
            "orderLinkId": f"mcp{int(time.time() * 1000)}",
        })

    return 13
