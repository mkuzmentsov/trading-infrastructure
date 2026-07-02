"""MEXC exchange tools — spot trading + balances + market/funding data.

Two separate APIs live here:

  * SPOT v3 (``https://api.mexc.com``) — Binance-style signed REST. The API key
    rides in the ``X-MEXC-APIKEY`` header; signed calls append an HMAC-SHA256
    ``signature`` over the URL-encoded query string (params + ``timestamp`` ms,
    optional ``recvWindow``). MEXC takes params in the QUERY STRING even for
    POST, so the signed helper builds one query string for every verb.
  * FUTURES (``https://contract.mexc.com``) — PUBLIC MARKET DATA ONLY.
    IMPORTANT: MEXC has DISABLED futures order placement over the API for most
    accounts, so there is deliberately NO perp order tool here — only read-only
    funding / market endpoints. Trade MEXC perps in the web UI.

Symbols: spot markets are like "BTCUSDT"; futures contracts are like
"SUI_USDT" (underscore).

Env vars:
    MEXC_API_KEY
    MEXC_API_SECRET
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time
import urllib.parse
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

_BASE = "https://api.mexc.com"
_FUTURES_BASE = "https://contract.mexc.com"


def _credentials_present() -> bool:
    return bool(os.environ.get("MEXC_API_KEY") and os.environ.get("MEXC_API_SECRET"))


def _raise_on_error(payload: Any) -> Any:
    """MEXC returns ``{"code":..., "msg":...}`` on error; success responses have
    no error code (or code 200/0). Raise RuntimeError on anything else."""
    if isinstance(payload, dict) and "code" in payload:
        code = payload.get("code")
        if code not in (0, 200, "0", "200", None):
            raise RuntimeError(f"MEXC error: {payload}")
    return payload


def _signed(
    method: str, path: str, params: dict[str, Any] | None = None
) -> Any:
    """Call a signed MEXC spot v3 endpoint. Params (GET or POST alike) ride in
    the query string; ``timestamp`` + ``recvWindow`` are added and the whole
    query string is HMAC-SHA256 signed. Raises on MEXC-side errors."""
    api_key = os.environ["MEXC_API_KEY"]
    secret = os.environ["MEXC_API_SECRET"].encode()
    clean = {k: v for k, v in (params or {}).items() if v is not None}
    clean["timestamp"] = int(time.time() * 1000)
    clean["recvWindow"] = 5000
    query = urllib.parse.urlencode(clean)
    signature = hmac.new(secret, query.encode(), hashlib.sha256).hexdigest()
    url = f"{_BASE}{path}?{query}&signature={signature}"
    headers = {"X-MEXC-APIKEY": api_key, "Content-Type": "application/json"}
    r = httpx.request(method, url, headers=headers, timeout=20)
    r.raise_for_status()
    return _raise_on_error(r.json())


def _public(path: str, params: dict[str, Any] | None = None) -> Any:
    """Unauthenticated MEXC spot v3 market-data call."""
    clean = {k: v for k, v in (params or {}).items() if v is not None}
    r = httpx.get(f"{_BASE}{path}", params=clean, timeout=20)
    r.raise_for_status()
    return _raise_on_error(r.json())


def _futures_public(path: str, params: dict[str, Any] | None = None) -> Any:
    """Unauthenticated MEXC futures (contract) market-data call."""
    clean = {k: v for k, v in (params or {}).items() if v is not None}
    r = httpx.get(f"{_FUTURES_BASE}{path}", params=clean, timeout=20)
    r.raise_for_status()
    return r.json()


def validate() -> dict[str, Any]:
    """Smoke-test MEXC creds: signed account call. Raises on bad signature."""
    acct = _signed("GET", "/api/v3/account") or {}
    balances = acct.get("balances") or []
    nonzero = 0
    for b in balances:
        try:
            if float(b.get("free") or 0) + float(b.get("locked") or 0) > 0:
                nonzero += 1
        except (TypeError, ValueError):
            continue
    return {"can_trade": acct.get("canTrade"), "nonzero_balances": nonzero}


def register(mcp: FastMCP) -> int:
    if not _credentials_present():
        return 0

    # ----- Account -------------------------------------------------------

    @mcp.tool()
    def mexc_get_balances() -> dict[str, Any]:
        """MEXC spot account: nonzero balances (free + locked per asset)."""
        acct = _signed("GET", "/api/v3/account") or {}
        balances = []
        for b in acct.get("balances") or []:
            try:
                free = float(b.get("free") or 0)
                locked = float(b.get("locked") or 0)
            except (TypeError, ValueError):
                continue
            if free + locked > 0:
                balances.append(
                    {"asset": b.get("asset"), "free": free, "locked": locked}
                )
        return {"can_trade": acct.get("canTrade"), "balances": balances}

    # ----- Market data (public) -----------------------------------------

    @mcp.tool()
    def mexc_get_orderbook(symbol: str, limit: int = 10) -> dict[str, Any]:
        """MEXC SPOT order book: best bid/ask, spread (bps), top levels. symbol
        e.g. "SUI" (auto-suffixed to USDT) or a full "SUIUSDT"."""
        sym = symbol.upper() if symbol.upper().endswith("USDT") else f"{symbol.upper()}USDT"
        ob = _public("/api/v3/depth", {"symbol": sym, "limit": min(max(limit, 1), 5000)})
        bids = [[float(p), float(q)] for p, q in (ob.get("bids") or [])]
        asks = [[float(p), float(q)] for p, q in (ob.get("asks") or [])]
        bb = bids[0][0] if bids else None
        ba = asks[0][0] if asks else None
        return {
            "symbol": sym,
            "best_bid": bb,
            "best_ask": ba,
            "spread_bps": (ba - bb) / bb * 1e4 if bb and ba else None,
            "bids": bids[:limit],
            "asks": asks[:limit],
        }

    @mcp.tool()
    def mexc_get_funding_rates() -> dict[str, Any]:
        """MEXC futures funding rates across all perpetuals (PUBLIC, read-only).
        MEXC funding is 8h, so apr = fundingRate × 3 × 365. Sorted by apr desc.
        NOTE: futures ORDER placement is disabled via the MEXC API — this is
        market data only."""
        payload = _futures_public("/api/v1/contract/funding_rate")
        data = payload.get("data") if isinstance(payload, dict) else None
        # Some MEXC deployments return a summary object rather than a list.
        if isinstance(data, dict):
            data = [data]
        rows = []
        for d in data or []:
            symbol = d.get("symbol") or ""
            try:
                fr = float(d.get("fundingRate"))
            except (TypeError, ValueError):
                continue
            rows.append(
                {
                    "coin": symbol.split("_")[0],
                    "symbol": symbol,
                    "funding_rate": fr,
                    "apr": fr * 3 * 365,
                    "collect_cycle": d.get("collectCycle"),
                }
            )
        rows.sort(key=lambda x: x["apr"], reverse=True)
        return {"count": len(rows), "rates": rows}

    @mcp.tool()
    def mexc_get_funding_rate(coin: str) -> dict[str, Any]:
        """MEXC futures current funding for one coin's USDT perpetual (PUBLIC).
        coin like "BTC"/"SUI" (→ BTC_USDT) or a full "BTC_USDT" contract."""
        contract = coin.upper() if "_" in coin else f"{coin.upper()}_USDT"
        payload = _futures_public(f"/api/v1/contract/funding_rate/{contract}")
        d = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(d, dict):
            return {"symbol": contract, "error": "not found", "raw": payload}
        try:
            fr = float(d.get("fundingRate"))
        except (TypeError, ValueError):
            fr = None
        return {
            "coin": contract.split("_")[0],
            "symbol": contract,
            "funding_rate": fr,
            "apr": fr * 3 * 365 if fr is not None else None,
            "collect_cycle": d.get("collectCycle"),
            "next_settle_time": d.get("nextSettleTime"),
        }

    # ----- Spot trading -------------------------------------------------

    @mcp.tool()
    def mexc_place_spot_order(
        symbol: str,
        side: str,
        type: str = "LIMIT",
        quantity: float | None = None,
        quote_order_qty: float | None = None,
        price: float | None = None,
    ) -> dict[str, Any]:
        """Place a MEXC spot order (signed POST /api/v3/order).

        symbol: e.g. "BTCUSDT".  side: "BUY" | "SELL".
        type: "LIMIT" (needs quantity + price) | "MARKET".
        quantity: size in the BASE asset.
        quote_order_qty: MARKET-buy by QUOTE amount instead of base quantity.
        """
        params: dict[str, Any] = {
            "symbol": symbol.upper(),
            "side": side.upper(),
            "type": type.upper(),
        }
        if quantity is not None:
            params["quantity"] = quantity
        if quote_order_qty is not None:
            params["quoteOrderQty"] = quote_order_qty
        if price is not None:
            params["price"] = price
        return _signed("POST", "/api/v3/order", params)

    # ----- Funding: deposit / withdraw ----------------------------------

    @mcp.tool()
    def mexc_get_deposit_address(coin: str, network: str | None = None) -> Any:
        """MEXC deposit address for `coin` (e.g. "USDT"). `network` selects the
        chain for multi-network assets (e.g. "Arbitrum One(ARB)", "TRC20").
        Give this address to the SENDING venue to move funds INTO MEXC."""
        params: dict[str, Any] = {"coin": coin.upper()}
        if network:
            params["network"] = network
        return _signed("GET", "/api/v3/capital/deposit/address", params)

    @mcp.tool()
    def mexc_withdraw(
        coin: str,
        address: str,
        amount: float,
        network: str | None = None,
        confirm: bool = False,
    ) -> Any:
        """Withdraw crypto from MEXC spot to `address`.

        `network` is required for multi-network assets. `amount` is the amount
        to send (MEXC deducts its withdrawal fee on top).

        Safety: confirm=False (default) returns the intended params WITHOUT
        sending. Set confirm=True to actually submit."""
        params: dict[str, Any] = {
            "coin": coin.upper(),
            "address": address,
            "amount": amount,
        }
        if network:
            params["network"] = network
        if not confirm:
            return {
                "dry_run": True,
                "would_withdraw": params,
                "warning": "Set confirm=True to submit. MEXC deducts its withdrawal fee on top of amount.",
            }
        return _signed("POST", "/api/v3/capital/withdraw", params)

    return 7
