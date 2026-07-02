"""Bitget exchange tools — spot + USDT-M perps (balances / book / funding / trade).

Bitget's V2 REST API needs THREE credentials (key, secret, and a user-chosen
passphrase set when the API key is created). Signed requests are authenticated
with an HMAC-SHA256 signature over ``timestamp + method + path + query + body``,
base64-encoded (see ``_sign``). Markets are named without a separator:
spot "BTCUSDT", USDT-M perp "BTCUSDT" under productType "USDT-FUTURES".

Env vars:
    BITGET_API_KEY
    BITGET_API_SECRET
    BITGET_API_PASSPHRASE
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import urllib.parse
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

_BASE = "https://api.bitget.com"


def _credentials_present() -> bool:
    return bool(
        os.environ.get("BITGET_API_KEY")
        and os.environ.get("BITGET_API_SECRET")
        and os.environ.get("BITGET_API_PASSPHRASE")
    )


def _sign(message: str, secret: str) -> str:
    mac = hmac.new(secret.encode(), message.encode(), hashlib.sha256)
    return base64.b64encode(mac.digest()).decode()


def _request(
    method: str,
    path: str,
    params: dict[str, Any] | None = None,
    signed: bool = True,
) -> Any:
    """Call a Bitget V2 endpoint. `path` like "/api/v2/spot/account/assets".

    For GET, `params` ride in the (sorted, url-encoded) query string; for POST
    they become the JSON body. Both the query string and body are folded into
    the signature. Raises RuntimeError if Bitget returns a non-"00000" code."""
    method = method.upper()
    clean = {k: v for k, v in (params or {}).items() if v is not None}

    query = ""
    body = ""
    if method == "GET":
        if clean:
            query = "?" + urllib.parse.urlencode(sorted(clean.items()))
        url = _BASE + path + query
        content = None
    else:
        body = json.dumps(clean, separators=(",", ":")) if clean else ""
        url = _BASE + path
        content = body

    headers: dict[str, str] = {"Content-Type": "application/json", "locale": "en-US"}
    if signed:
        ts = str(int(time.time() * 1000))
        message = ts + method + path + query + body
        headers.update(
            {
                "ACCESS-KEY": os.environ["BITGET_API_KEY"],
                "ACCESS-SIGN": _sign(message, os.environ["BITGET_API_SECRET"]),
                "ACCESS-TIMESTAMP": ts,
                "ACCESS-PASSPHRASE": os.environ["BITGET_API_PASSPHRASE"],
            }
        )

    r = httpx.request(method, url, headers=headers, content=content, timeout=20)
    r.raise_for_status()
    payload = r.json()
    if str(payload.get("code")) != "00000":
        raise RuntimeError(f"Bitget error: {payload.get('code')} {payload.get('msg')}")
    return payload.get("data")


def validate() -> dict[str, Any]:
    """Smoke-test Bitget creds: signed spot account assets call. Raises on a
    bad signature / passphrase (code != "00000")."""
    assets = _request("GET", "/api/v2/spot/account/assets") or []
    non_zero = 0
    for a in assets if isinstance(assets, list) else []:
        try:
            if float(a.get("available") or 0) + float(a.get("frozen") or 0) > 0:
                non_zero += 1
        except (TypeError, ValueError):
            continue
    return {
        "asset_count": len(assets) if isinstance(assets, list) else 0,
        "non_zero_assets": non_zero,
    }


def register(mcp: FastMCP) -> int:
    if not _credentials_present():
        return 0

    # ----- Balances -----------------------------------------------------

    @mcp.tool()
    def bitget_get_balances() -> list[dict[str, Any]]:
        """Bitget spot account balances (nonzero only): available + frozen per
        coin."""
        assets = _request("GET", "/api/v2/spot/account/assets") or []
        out = []
        for a in assets if isinstance(assets, list) else []:
            try:
                avail = float(a.get("available") or 0)
                frozen = float(a.get("frozen") or 0)
            except (TypeError, ValueError):
                continue
            if avail + frozen > 0:
                out.append(
                    {
                        "coin": a.get("coin"),
                        "available": avail,
                        "frozen": frozen,
                        "total": avail + frozen,
                    }
                )
        return out

    # ----- Market data (public) -----------------------------------------

    @mcp.tool()
    def bitget_get_orderbook(symbol: str, limit: int = 10) -> dict[str, Any]:
        """Bitget SPOT order book: best bid/ask, spread (bps), top levels.
        symbol e.g. "BTCUSDT". Short fills at the bid."""
        sym = symbol.upper()
        data = _request(
            "GET",
            "/api/v2/spot/market/orderbook",
            {"symbol": sym, "type": "step0", "limit": limit},
            signed=False,
        ) or {}
        bids = [[float(p), float(q)] for p, q in (data.get("bids") or [])]
        asks = [[float(p), float(q)] for p, q in (data.get("asks") or [])]
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
    def bitget_get_funding_rates() -> list[dict[str, Any]]:
        """Bitget USDT-M perp funding rates + computed APR (funding is 8h, so
        APR = rate × 3 × 365), mark price, open interest. Sorted by APR desc."""
        data = _request(
            "GET",
            "/api/v2/mix/market/tickers",
            {"productType": "USDT-FUTURES"},
            signed=False,
        ) or []
        out = []
        for t in data if isinstance(data, list) else []:
            sym = t.get("symbol") or ""
            try:
                apr = float(t.get("fundingRate")) * 3 * 365
            except (TypeError, ValueError):
                apr = None
            out.append(
                {
                    "coin": sym[:-4] if sym.endswith("USDT") else sym,
                    "symbol": sym,
                    "funding_rate": t.get("fundingRate"),
                    "apr": apr,
                    "mark_px": t.get("markPrice"),
                    "open_interest": t.get("holdingAmount") or t.get("openInterest"),
                }
            )
        out.sort(key=lambda x: x["apr"] if x["apr"] is not None else -1e9, reverse=True)
        return out

    @mcp.tool()
    def bitget_get_perp_positions() -> Any:
        """Current Bitget USDT-M perp positions (symbol, side, size, entry,
        margin, unrealized PnL)."""
        return _request(
            "GET",
            "/api/v2/mix/position/all-position",
            {"productType": "USDT-FUTURES", "marginCoin": "USDT"},
        )

    # ----- Trading ------------------------------------------------------

    @mcp.tool()
    def bitget_place_spot_order(
        symbol: str,
        side: str,
        order_type: str = "limit",
        size: float | None = None,
        price: float | None = None,
        force: str = "gtc",
    ) -> Any:
        """Place a Bitget SPOT order.

        symbol: e.g. "BTCUSDT".  side: "buy" | "sell".
        order_type: "limit" (needs price) | "market".
        size: order quantity (base asset for limit / sell-market; quote for
            buy-market, per Bitget rules).  force: "gtc" | "post_only" | "ioc"
            | "fok".
        """
        params: dict[str, Any] = {
            "symbol": symbol.upper(),
            "side": side.lower(),
            "orderType": order_type.lower(),
            "size": str(size) if size is not None else None,
            "force": force.lower(),
        }
        if price is not None:
            params["price"] = str(price)
        return _request("POST", "/api/v2/spot/trade/place-order", params)

    @mcp.tool()
    def bitget_place_perp_order(
        symbol: str,
        side: str,
        order_type: str = "limit",
        size: float | None = None,
        price: float | None = None,
        reduce_only: bool = False,
        margin_coin: str = "USDT",
    ) -> Any:
        """Place a Bitget USDT-M perp order (crossed margin).

        symbol: e.g. "BTCUSDT".  side: "buy" | "sell".
        order_type: "limit" (needs price) | "market".
        size: order quantity in the base coin.
        reduce_only: True = only reduce/close an existing position.
        """
        params: dict[str, Any] = {
            "symbol": symbol.upper(),
            "productType": "USDT-FUTURES",
            "marginMode": "crossed",
            "marginCoin": margin_coin.upper(),
            "side": side.lower(),
            "orderType": order_type.lower(),
            "size": str(size) if size is not None else None,
        }
        if price is not None:
            params["price"] = str(price)
        if reduce_only:
            params["reduceOnly"] = "YES"
        return _request("POST", "/api/v2/mix/order/place-order", params)

    # ----- Funding: deposit / withdraw ----------------------------------

    @mcp.tool()
    def bitget_get_deposit_address(coin: str, chain: str | None = None) -> Any:
        """Bitget deposit address for `coin` (e.g. "USDT"). `chain` is required
        for multi-network assets (e.g. "ERC20", "TRC20", "ARBITRUMONE"). Give
        this address to the SENDING venue to move funds INTO Bitget."""
        params: dict[str, Any] = {"coin": coin.upper()}
        if chain:
            params["chain"] = chain
        return _request("GET", "/api/v2/spot/wallet/deposit-address", params)

    @mcp.tool()
    def bitget_withdraw(
        coin: str,
        address: str,
        amount: float,
        chain: str,
        confirm: bool = False,
    ) -> Any:
        """Withdraw crypto from Bitget (spot wallet) to an on-chain `address`.

        coin: e.g. "USDT".  chain: required (e.g. "TRC20", "ERC20"). amount is
        the gross size (network fee is deducted by Bitget).

        Safety: confirm=False (default) returns the intended params WITHOUT
        sending. Set confirm=True to actually submit."""
        params: dict[str, Any] = {
            "coin": coin.upper(),
            "transferType": "on_chain",
            "address": address,
            "chain": chain,
            "size": str(amount),
        }
        if not confirm:
            return {
                "dry_run": True,
                "would_withdraw": params,
                "warning": "Set confirm=True to submit. Bitget deducts the network fee from the amount.",
            }
        return _request("POST", "/api/v2/spot/wallet/withdrawal", params)

    # ----- Earn (Savings) ------------------------------------------------

    @mcp.tool()
    def bitget_list_earn_products(
        coin: str | None = None, filter: str = "available"
    ) -> Any:
        """Bitget Savings products + APY. filter: "available" | "held" | "all".
        Prefer periodType "flexible" for an instantly-redeemable hedge leg."""
        params: dict[str, Any] = {"filter": filter}
        if coin:
            params["coin"] = coin.upper()
        return _request("GET", "/api/v2/earn/savings/product", params)

    @mcp.tool()
    def bitget_get_earn_assets(period_type: str = "flexible") -> Any:
        """Current Bitget Savings holdings. period_type: "flexible" | "fixed"."""
        return _request(
            "GET", "/api/v2/earn/savings/assets", {"periodType": period_type}
        )

    @mcp.tool()
    def bitget_find_best_earn_rates(
        coin: str | None = None, top_n: int = 10
    ) -> dict[str, Any]:
        """Rank Bitget Savings products by APY (highest first)."""
        products = bitget_list_earn_products(coin=coin, filter="available")

        def _apy(p: dict[str, Any]) -> float:
            best = 0.0
            for tier in (p.get("apyList") or []):
                for k in ("currentApy", "apy", "rate"):
                    v = tier.get(k)
                    if v is not None:
                        try:
                            best = max(best, float(str(v).replace("%", "")))
                        except (TypeError, ValueError):
                            pass
            for k in ("apy", "advanceRate", "currentApy"):
                v = p.get(k)
                if v is not None:
                    try:
                        best = max(best, float(str(v).replace("%", "")))
                    except (TypeError, ValueError):
                        pass
            return best

        rows = products if isinstance(products, list) else (products or {}).get("resultList") or []
        ranked = sorted(rows, key=_apy, reverse=True)[:top_n]
        return {"top": [
            {"coin": p.get("coin"), "productId": p.get("productId"),
             "periodType": p.get("periodType"), "apy_pct": _apy(p),
             "apr_frac": _apy(p) / 100, "status": p.get("status")}
            for p in ranked
        ]}

    @mcp.tool()
    def bitget_earn_subscribe(
        product_id: str, amount: float, period_type: str = "flexible"
    ) -> Any:
        """Subscribe to a Bitget Savings product. Use "flexible" so the hedge
        stays instantly redeemable."""
        return _request("POST", "/api/v2/earn/savings/subscribe", {
            "productId": product_id, "periodType": period_type, "amount": str(amount),
        })

    @mcp.tool()
    def bitget_earn_redeem(
        product_id: str, amount: float, period_type: str = "flexible", order_id: str | None = None
    ) -> Any:
        """Redeem from a Bitget Savings product."""
        params: dict[str, Any] = {
            "productId": product_id, "periodType": period_type, "amount": str(amount),
        }
        if order_id:
            params["orderId"] = order_id
        return _request("POST", "/api/v2/earn/savings/redeem", params)

    return 13
