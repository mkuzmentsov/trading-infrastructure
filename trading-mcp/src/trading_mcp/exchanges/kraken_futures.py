"""Kraken Futures tools — perps (account / positions / funding / trade).

This is a SEPARATE API from Kraken spot (``kraken.py``): different host
(``futures.kraken.com``), different keys, and a different signing scheme.

Env vars:
    KRAKEN_FUTURES_API_KEY
    KRAKEN_FUTURES_API_SECRET   (base64, as futures.kraken.com displays it)

Auth (per Kraken Futures REST docs): Authent =
    base64( HMAC-SHA512( b64decode(secret), SHA256(postData + nonce + path) ) )
where ``path`` is the endpoint WITHOUT the ``/derivatives`` base prefix and
``postData`` is the URL-encoded query string. Params ride in the query string
for GET and POST alike (body stays empty), matching Kraken's reference client.

Symbols: linear USD-settled perpetuals are ``PF_<COIN>USD`` (BTC → XBT), e.g.
``PF_XBTUSD``, ``PF_ETHUSD`` — the right leg for a long-spot / short-perp carry.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import threading
import time
import urllib.parse
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

# Base already includes /derivatives; the signing path is what comes AFTER it.
_BASE = "https://futures.kraken.com/derivatives"

_nonce_lock = threading.Lock()
_last_nonce = 0


def _credentials_present() -> bool:
    return bool(
        os.environ.get("KRAKEN_FUTURES_API_KEY")
        and os.environ.get("KRAKEN_FUTURES_API_SECRET")
    )


def _nonce() -> str:
    """Strictly-increasing nonce (ms clock, bumped if called twice in a ms)."""
    global _last_nonce
    with _nonce_lock:
        n = int(time.time() * 1000)
        if n <= _last_nonce:
            n = _last_nonce + 1
        _last_nonce = n
        return str(n)


def _sign(path: str, post_data: str, nonce: str, secret_b64: str) -> str:
    sha = hashlib.sha256((post_data + nonce + path).encode()).digest()
    mac = hmac.new(base64.b64decode(secret_b64), sha, hashlib.sha512)
    return base64.b64encode(mac.digest()).decode()


def _request(
    method: str,
    path: str,
    params: dict[str, Any] | None = None,
    public: bool = False,
) -> dict[str, Any]:
    """Call a Kraken Futures endpoint. `path` is the part after /derivatives,
    e.g. "/api/v3/accounts". Raises on Kraken-side errors."""
    clean = {k: v for k, v in (params or {}).items() if v is not None}
    post_data = urllib.parse.urlencode(clean)
    url = _BASE + path + (f"?{post_data}" if post_data else "")
    headers = {"Accept": "application/json"}
    if not public:
        nonce = _nonce()
        headers.update(
            {
                "APIKey": os.environ["KRAKEN_FUTURES_API_KEY"],
                "Nonce": nonce,
                "Authent": _sign(
                    path, post_data, nonce, os.environ["KRAKEN_FUTURES_API_SECRET"]
                ),
            }
        )
    r = httpx.request(method, url, headers=headers, timeout=20)
    r.raise_for_status()
    payload = r.json()
    if payload.get("result") == "error" or payload.get("errors"):
        raise RuntimeError(
            f"Kraken Futures error: {payload.get('error') or payload.get('errors')}"
        )
    return payload


def _pf_symbol(coin: str) -> str:
    """Coin → linear USD perpetual symbol. "BTC" → "PF_XBTUSD". Pass-through if
    an explicit PF_/PI_/FI_ symbol is already given."""
    c = coin.upper()
    if c.startswith(("PF_", "PI_", "FI_", "FF_")):
        return c
    if c == "BTC":
        c = "XBT"
    return f"PF_{c}USD"


def _ticker_apr(t: dict[str, Any]) -> float | None:
    """Annualized funding APR from a ticker. Kraken applies funding hourly, so
    APR ≈ relativeFundingRate × 24 × 365. Falls back to fundingRate / markPrice."""
    rel = t.get("relativeFundingRate")
    try:
        if rel is not None:
            return float(rel) * 24 * 365
    except (TypeError, ValueError):
        pass
    try:
        fr = float(t.get("fundingRate"))
        mark = float(t.get("markPrice") or 0)
        if mark:
            return fr / mark * 24 * 365
    except (TypeError, ValueError):
        pass
    return None


def validate() -> dict[str, Any]:
    """Smoke-test futures creds: signed accounts call. Raises on bad signature."""
    payload = _request("GET", "/api/v3/accounts")
    accounts = payload.get("accounts") or {}
    flex = accounts.get("flex") or {}
    return {
        "account_types": list(accounts.keys()),
        "flex_portfolio_value": flex.get("portfolioValue"),
        "flex_available_margin": flex.get("availableMargin"),
    }


def register(mcp: FastMCP) -> int:
    if not _credentials_present():
        return 0

    # ----- Account -------------------------------------------------------

    @mcp.tool()
    def kraken_futures_get_accounts() -> dict[str, Any]:
        """All Kraken Futures wallets: balances, margin, portfolio value
        (the `flex` multi-collateral account is the usual one)."""
        return _request("GET", "/api/v3/accounts").get("accounts", {})

    @mcp.tool()
    def kraken_futures_get_open_positions() -> dict[str, Any]:
        """Current open futures positions (symbol, side, size, entry, funding)."""
        return _request("GET", "/api/v3/openpositions")

    @mcp.tool()
    def kraken_futures_get_open_orders() -> dict[str, Any]:
        """Working (unfilled) Kraken Futures orders."""
        return _request("GET", "/api/v3/openorders")

    # ----- Market data (public) -----------------------------------------

    @mcp.tool()
    def kraken_futures_get_tickers(coin: str | None = None) -> dict[str, Any]:
        """Kraken Futures tickers: mark price, funding rate + computed funding
        APR, open interest. With `coin` set (e.g. "BTC", "ETH" or a full
        "PF_XBTUSD"), returns just that linear perpetual."""
        payload = _request("GET", "/api/v3/tickers", public=True)
        tickers = payload.get("tickers") or []
        if coin:
            want = _pf_symbol(coin)
            t = next(
                (x for x in tickers if (x.get("symbol") or "").upper() == want), None
            )
            if not t:
                return {"symbol": want, "error": "not found in tickers"}
            return {**t, "funding_apr": _ticker_apr(t)}
        return {
            "tickers": [
                {**t, "funding_apr": _ticker_apr(t)}
                for t in tickers
                if (t.get("symbol") or "").startswith("PF_")
            ]
        }

    @mcp.tool()
    def kraken_futures_get_funding_rate(coin: str) -> dict[str, Any]:
        """Current + recent historical funding for a coin's linear perpetual.
        `coin` like "BTC"/"ETH" (→ PF_XBTUSD) or a full PF_ symbol."""
        symbol = _pf_symbol(coin)
        hist = _request(
            "GET",
            "/api/v4/historicalfundingrates",
            {"symbol": symbol},
            public=True,
        )
        rates = hist.get("rates") or []
        return {
            "symbol": symbol,
            "recent": rates[-5:],
            "count": len(rates),
        }

    @mcp.tool()
    def kraken_futures_get_instruments() -> dict[str, Any]:
        """Tradeable Kraken Futures instruments (symbols, tick/contract size,
        max leverage). Use to confirm a symbol before trading."""
        payload = _request("GET", "/api/v3/instruments", public=True)
        return {
            "perpetuals": [
                {
                    "symbol": i.get("symbol"),
                    "tradeable": i.get("tradeable"),
                    "maxLeverage": (i.get("marginLevels") or [{}])[0].get("maxLeverage")
                    if i.get("marginLevels")
                    else i.get("maxLeverage"),
                    "contractSize": i.get("contractSize"),
                    "tickSize": i.get("tickSize"),
                }
                for i in (payload.get("instruments") or [])
                if (i.get("symbol") or "").startswith("PF_")
            ]
        }

    @mcp.tool()
    def kraken_futures_get_orderbook(coin: str) -> dict[str, Any]:
        """Kraken Futures order book for a coin's linear perp: best bid/ask, spread
        (bps), top levels. Short fills at the bid. coin like "BTC" (→ PF_XBTUSD)."""
        symbol = _pf_symbol(coin)
        ob = _request("GET", "/api/v3/orderbook", {"symbol": symbol}, public=True).get(
            "orderBook", {}
        )
        # Kraken Futures returns both sides ASCENDING (lowest price first). Best
        # bid is the highest price; best ask is the lowest. Sort bids descending
        # so bids[0] / bids[:10] are the real top-of-book.
        bids = sorted(
            ([float(p), float(q)] for p, q in (ob.get("bids") or [])),
            key=lambda b: b[0], reverse=True,
        )
        asks = [[float(p), float(q)] for p, q in (ob.get("asks") or [])]
        bb = bids[0][0] if bids else None
        ba = asks[0][0] if asks else None
        return {
            "symbol": symbol,
            "best_bid": bb,
            "best_ask": ba,
            "spread_bps": (ba - bb) / bb * 1e4 if bb and ba else None,
            "bids": bids[:10],
            "asks": asks[:10],
        }

    # ----- Trading -------------------------------------------------------

    @mcp.tool()
    def kraken_futures_place_order(
        coin: str,
        side: str,
        size: float,
        order_type: str = "lmt",
        limit_price: float | None = None,
        reduce_only: bool = False,
        cli_ord_id: str | None = None,
    ) -> dict[str, Any]:
        """Place a Kraken Futures order (sendorder).

        coin: "BTC"/"ETH" (→ PF_XBTUSD) or a full PF_ symbol.
        side: "buy" | "sell".
        size: order quantity in the contract's units.
        order_type: "lmt" (needs limit_price) | "mkt" | "post" (post-only).
        reduce_only: True = only reduce/close an existing position.
        """
        params: dict[str, Any] = {
            "orderType": order_type.lower(),
            "symbol": _pf_symbol(coin),
            "side": side.lower(),
            "size": size,
        }
        if limit_price is not None:
            params["limitPrice"] = limit_price
        if reduce_only:
            params["reduceOnly"] = "true"
        if cli_ord_id:
            params["cliOrdId"] = cli_ord_id
        return _request("POST", "/api/v3/sendorder", params)

    @mcp.tool()
    def kraken_futures_cancel_order(
        order_id: str | None = None, cli_ord_id: str | None = None
    ) -> dict[str, Any]:
        """Cancel a Kraken Futures order by order_id (or cli_ord_id)."""
        if not order_id and not cli_ord_id:
            return {"error": "provide order_id or cli_ord_id"}
        params = {"order_id": order_id} if order_id else {"cliOrdId": cli_ord_id}
        return _request("POST", "/api/v3/cancelorder", params)

    @mcp.tool()
    def kraken_futures_cancel_all_orders(coin: str | None = None) -> dict[str, Any]:
        """Cancel all working orders, optionally only for one coin's perpetual."""
        params = {"symbol": _pf_symbol(coin)} if coin else None
        return _request("POST", "/api/v3/cancelallorders", params)

    @mcp.tool()
    def kraken_futures_set_leverage(coin: str, leverage: float) -> dict[str, Any]:
        """Set the max leverage preference for a coin's linear perpetual
        (leveragepreferences). Lower = more conservative margin."""
        return _request(
            "PUT",
            "/api/v3/leveragepreferences",
            {"symbol": _pf_symbol(coin), "maxLeverage": leverage},
        )

    return 11
