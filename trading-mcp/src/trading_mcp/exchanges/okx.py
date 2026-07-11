"""OKX exchange tools — spot + USDT-settled perps (balances / book / funding / trade).

OKX's V5 REST API needs THREE credentials (key, secret, and a user-chosen
passphrase set when the API key is created). Signed requests carry an
HMAC-SHA256 signature, base64-encoded, over

    prehash = timestamp + method + requestPath + body

where ``timestamp`` is an ISO-8601 UTC string with millisecond precision
(e.g. "2020-12-08T09:08:57.715Z") — NOT a millisecond epoch — ``requestPath``
includes the query string for GETs, and ``body`` is the raw JSON body ("" for
GET). See ``_sign``.

Instruments use a dashed format OKX-native: spot "BTC-USDT", USDT perp
"BTC-USDT-SWAP". The helpers ``_spot_inst`` / ``_swap_inst`` accept the usual
"BTCUSDT" / "BTC-USDT" / "BTC" shorthands and normalize.

Note on perp size: OKX ``sz`` for a SWAP order is in CONTRACTS, not the base
coin (one BTC-USDT-SWAP contract = 0.01 BTC, per the instrument's ctVal). Size
spot/margin orders in the base coin as usual.

Env vars:
    OKX_API_KEY
    OKX_API_SECRET
    OKX_API_PASSPHRASE
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import urllib.parse
from datetime import datetime, timezone
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

_BASE = "https://www.okx.com"

# Quote assets tried (longest first) when splitting a joined symbol like
# "BTCUSDT" into "BTC-USDT". USDT/USDC before USD so they win the suffix match.
_QUOTES = ("USDT", "USDC", "USD", "BTC", "ETH")


def _credentials_present() -> bool:
    return bool(
        os.environ.get("OKX_API_KEY")
        and os.environ.get("OKX_API_SECRET")
        and os.environ.get("OKX_API_PASSPHRASE")
    )


def _spot_inst(symbol: str) -> str:
    """Normalize a symbol to an OKX spot instId, e.g. "BTCUSDT" -> "BTC-USDT"."""
    s = symbol.upper()
    if "-" in s:
        return s
    for q in _QUOTES:
        if s.endswith(q) and len(s) > len(q):
            return f"{s[:-len(q)]}-{q}"
    return s


def _swap_inst(symbol: str) -> str:
    """Normalize a symbol to an OKX USDT-perp instId, e.g. "BTC" ->
    "BTC-USDT-SWAP", "BTCUSDT" -> "BTC-USDT-SWAP"."""
    s = symbol.upper()
    if s.endswith("-SWAP"):
        return s
    if "-" in s:
        return f"{s}-SWAP"
    for q in _QUOTES:
        if s.endswith(q) and len(s) > len(q):
            return f"{s[:-len(q)]}-{q}-SWAP"
    return f"{s}-USDT-SWAP"


def _sign(message: str, secret: str) -> str:
    mac = hmac.new(secret.encode(), message.encode(), hashlib.sha256)
    return base64.b64encode(mac.digest()).decode()


def _request(
    method: str,
    path: str,
    params: dict[str, Any] | None = None,
    signed: bool = True,
) -> Any:
    """Call an OKX V5 endpoint. `path` like "/api/v5/account/balance".

    For GET, `params` ride in the (sorted, url-encoded) query string, which is
    folded into BOTH the URL and the signature's requestPath. For POST they
    become the JSON body, which is folded into the signature's `body`. Raises
    RuntimeError if OKX returns a non-"0" code."""
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

    request_path = path + query
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if signed:
        now = datetime.now(timezone.utc)
        ts = now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        message = ts + method + request_path + body
        headers.update(
            {
                "OK-ACCESS-KEY": os.environ["OKX_API_KEY"],
                "OK-ACCESS-SIGN": _sign(message, os.environ["OKX_API_SECRET"]),
                "OK-ACCESS-TIMESTAMP": ts,
                "OK-ACCESS-PASSPHRASE": os.environ["OKX_API_PASSPHRASE"],
            }
        )

    r = httpx.request(method, url, headers=headers, content=content, timeout=20)
    r.raise_for_status()
    payload = r.json()
    if str(payload.get("code")) != "0":
        raise RuntimeError(f"OKX error: {payload.get('code')} {payload.get('msg')}")
    return payload.get("data")


def _funding_apr(rate: float, fund_time: Any, next_time: Any) -> tuple[float, float]:
    """Return (interval_hours, apr) for an OKX funding rate. OKX funds on a
    variable cycle (usually 8h, some 4h); derive the interval from the
    funding/next-funding timestamps and annualize."""
    interval_h = 8.0
    try:
        diff_ms = float(next_time) - float(fund_time)
        if diff_ms > 0:
            interval_h = diff_ms / 3_600_000
    except (TypeError, ValueError):
        pass
    apr = rate * (24 / interval_h) * 365
    return interval_h, apr


def validate() -> dict[str, Any]:
    """Smoke-test OKX creds: signed trading-account balance call. Raises on a
    bad signature / passphrase (code != "0")."""
    data = _request("GET", "/api/v5/account/balance") or []
    acct = data[0] if isinstance(data, list) and data else {}
    details = acct.get("details") or []
    return {
        "total_eq_usd": acct.get("totalEq"),
        "asset_count": len(details),
    }


def register(mcp: FastMCP) -> int:
    if not _credentials_present():
        return 0

    # ----- Balances -----------------------------------------------------

    @mcp.tool()
    def okx_get_balances() -> list[dict[str, Any]]:
        """OKX trading-account balances (nonzero only): available + frozen and
        USD equity per coin."""
        data = _request("GET", "/api/v5/account/balance") or []
        acct = data[0] if isinstance(data, list) and data else {}
        out = []
        for d in acct.get("details") or []:
            try:
                avail = float(d.get("availBal") or 0)
                frozen = float(d.get("frozenBal") or 0)
            except (TypeError, ValueError):
                continue
            if avail + frozen > 0:
                out.append(
                    {
                        "coin": d.get("ccy"),
                        "available": avail,
                        "frozen": frozen,
                        "total": avail + frozen,
                        "eq_usd": d.get("eqUsd"),
                    }
                )
        return out

    # ----- Market data (public) -----------------------------------------

    @mcp.tool()
    def okx_get_orderbook(symbol: str, limit: int = 10) -> dict[str, Any]:
        """OKX SPOT order book: best bid/ask, spread (bps), top levels.
        symbol e.g. "BTCUSDT" or "BTC-USDT". Short/sell fills at the bid."""
        inst = _spot_inst(symbol)
        data = _request(
            "GET",
            "/api/v5/market/books",
            {"instId": inst, "sz": limit},
            signed=False,
        ) or []
        book = data[0] if isinstance(data, list) and data else {}
        bids = [[float(l[0]), float(l[1])] for l in (book.get("bids") or [])]
        asks = [[float(l[0]), float(l[1])] for l in (book.get("asks") or [])]
        bb = bids[0][0] if bids else None
        ba = asks[0][0] if asks else None
        return {
            "symbol": inst,
            "best_bid": bb,
            "best_ask": ba,
            "spread_bps": (ba - bb) / bb * 1e4 if bb and ba else None,
            "bids": bids[:limit],
            "asks": asks[:limit],
        }

    @mcp.tool()
    def okx_get_funding_rate(symbol: str) -> dict[str, Any]:
        """OKX USDT-perp funding rate + computed APR for one symbol (e.g. "BTC"
        or "BTCUSDT"). OKX has no single all-symbols funding endpoint, so this is
        per-instrument. Interval is derived from the funding timestamps (usually
        8h) and APR = rate × (24/interval_h) × 365."""
        inst = _swap_inst(symbol)
        data = _request(
            "GET", "/api/v5/public/funding-rate", {"instId": inst}, signed=False
        ) or []
        row = data[0] if isinstance(data, list) and data else {}
        try:
            rate = float(row.get("fundingRate") or 0)
        except (TypeError, ValueError):
            rate = 0.0
        interval_h, apr = _funding_apr(
            rate, row.get("fundingTime"), row.get("nextFundingTime")
        )
        return {
            "coin": inst.split("-")[0],
            "symbol": inst,
            "funding_rate": row.get("fundingRate"),
            "interval_h": interval_h,
            "hourly": rate / interval_h if interval_h else None,
            "apr": apr,
            "next_funding_rate": row.get("nextFundingRate"),
        }

    @mcp.tool()
    def okx_get_perp_positions() -> Any:
        """Current OKX SWAP (perp) positions: instId, side (posSide/pos sign),
        size, avg entry, margin, unrealized PnL."""
        return _request("GET", "/api/v5/account/positions", {"instType": "SWAP"})

    # ----- Trading ------------------------------------------------------

    @mcp.tool()
    def okx_place_spot_order(
        symbol: str,
        side: str,
        order_type: str = "limit",
        size: float | None = None,
        price: float | None = None,
        td_mode: str = "cash",
    ) -> Any:
        """Place an OKX SPOT order (trade/order).

        symbol: e.g. "BTCUSDT" / "BTC-USDT".  side: "buy" | "sell".
        order_type: "limit" (needs price) | "market".
        size: order quantity. In base asset for limit / sell-market; for a spot
            market BUY, OKX defaults sz to the QUOTE amount (tgtCcy).
        td_mode: "cash" (spot, default) | "cross" | "isolated" (margin).
        """
        params: dict[str, Any] = {
            "instId": _spot_inst(symbol),
            "tdMode": td_mode.lower(),
            "side": side.lower(),
            "ordType": order_type.lower(),
            "sz": str(size) if size is not None else None,
        }
        if price is not None:
            params["px"] = str(price)
        return _request("POST", "/api/v5/trade/order", params)

    @mcp.tool()
    def okx_place_perp_order(
        symbol: str,
        side: str,
        order_type: str = "limit",
        size: float | None = None,
        price: float | None = None,
        reduce_only: bool = False,
        td_mode: str = "cross",
    ) -> Any:
        """Place an OKX USDT-SWAP (perp) order (trade/order).

        symbol: e.g. "BTC" / "BTCUSDT" (normalized to "...-USDT-SWAP").
        side: "buy" | "sell".  order_type: "limit" (needs price) | "market".
        size: quantity in CONTRACTS, not the base coin (one BTC-USDT-SWAP
            contract = 0.01 BTC; check the instrument's ctVal).
        reduce_only: True = only reduce/close an existing position.
        td_mode: "cross" (default) | "isolated".
        """
        params: dict[str, Any] = {
            "instId": _swap_inst(symbol),
            "tdMode": td_mode.lower(),
            "side": side.lower(),
            "ordType": order_type.lower(),
            "sz": str(size) if size is not None else None,
        }
        if price is not None:
            params["px"] = str(price)
        if reduce_only:
            params["reduceOnly"] = True
        return _request("POST", "/api/v5/trade/order", params)

    # ----- Funding: deposit / withdraw ----------------------------------

    @mcp.tool()
    def okx_get_deposit_address(coin: str, chain: str | None = None) -> Any:
        """OKX deposit address(es) for `coin` (e.g. "USDT"). OKX returns one row
        per network; `chain` (OKX-native "USDT-TRC20", "USDT-ERC20", …) filters
        to a single network. Give this address to the SENDING venue to move
        funds INTO OKX (funding account)."""
        data = _request(
            "GET", "/api/v5/asset/deposit-address", {"ccy": coin.upper()}
        ) or []
        rows = data if isinstance(data, list) else []
        if chain:
            want = chain.upper()
            rows = [r for r in rows if (r.get("chain") or "").upper() == want]
        return rows

    @mcp.tool()
    def okx_withdraw(
        coin: str,
        address: str,
        amount: float,
        chain: str,
        fee: float | None = None,
        confirm: bool = False,
    ) -> Any:
        """Withdraw crypto from OKX (funding account) to an on-chain `address`.

        coin: e.g. "USDT".  chain: OKX-native network string, either full
        ("USDT-TRC20") or the bare network ("TRC20", auto-prefixed with the
        coin).  amount: gross size.  fee: OKX REQUIRES an explicit network fee;
        if omitted it is looked up from asset/currencies (minFee for that chain).

        Safety: confirm=False (default) returns the intended params (and the
        resolved fee) WITHOUT sending. Set confirm=True to actually submit."""
        ccy = coin.upper()
        okx_chain = chain if "-" in chain else f"{ccy}-{chain.upper()}"

        resolved_fee = fee
        if resolved_fee is None:
            currencies = _request(
                "GET", "/api/v5/asset/currencies", {"ccy": ccy}
            ) or []
            for c in currencies if isinstance(currencies, list) else []:
                if (c.get("chain") or "").upper() == okx_chain.upper():
                    resolved_fee = c.get("minFee")
                    break

        params: dict[str, Any] = {
            "ccy": ccy,
            "amt": str(amount),
            "dest": "4",  # 4 = on-chain withdrawal
            "toAddr": address,
            "chain": okx_chain,
            "fee": str(resolved_fee) if resolved_fee is not None else None,
        }
        if not confirm:
            return {
                "dry_run": True,
                "would_withdraw": params,
                "resolved_fee": resolved_fee,
                "warning": (
                    "Set confirm=True to submit. OKX requires an explicit 'fee'; "
                    "the network fee is charged on top of 'amt'."
                ),
            }
        if resolved_fee is None:
            return {
                "error": "Could not resolve a network fee for this chain; pass fee explicitly.",
                "chain": okx_chain,
            }
        return _request("POST", "/api/v5/asset/withdrawal", params)

    # ----- Earn (Simple Earn / Savings) ---------------------------------

    @mcp.tool()
    def okx_list_earn_products(coin: str | None = None) -> Any:
        """OKX Simple Earn Flexible (savings) estimated lending rates per coin
        (public lending-rate-summary). Flexible savings is instantly redeemable,
        so it suits a hedge leg."""
        params: dict[str, Any] = {}
        if coin:
            params["ccy"] = coin.upper()
        return _request(
            "GET", "/api/v5/finance/savings/lending-rate-summary", params, signed=False
        )

    @mcp.tool()
    def okx_get_earn_assets() -> Any:
        """Current OKX Simple Earn Flexible (savings) holdings: per-coin amount,
        earnings and current rate."""
        return _request("GET", "/api/v5/finance/savings/balance")

    @mcp.tool()
    def okx_find_best_earn_rates(
        coin: str | None = None, top_n: int = 10
    ) -> dict[str, Any]:
        """Rank OKX Simple Earn Flexible products by estimated APR (highest
        first)."""
        rows = okx_list_earn_products(coin=coin)

        def _apr(p: dict[str, Any]) -> float:
            for k in ("estRate", "estApy", "rate", "avgRate"):
                v = p.get(k)
                if v is not None:
                    try:
                        return float(str(v).replace("%", ""))
                    except (TypeError, ValueError):
                        continue
            return 0.0

        items = sorted(
            rows if isinstance(rows, list) else [], key=_apr, reverse=True
        )[:top_n]
        return {"top": [
            {"coin": p.get("ccy"), "est_rate": _apr(p), "apr_frac": _apr(p),
             "raw": p}
            for p in items
        ]}

    @mcp.tool()
    def okx_earn_subscribe(
        coin: str, amount: float, rate: float = 0.01
    ) -> Any:
        """Subscribe to OKX Simple Earn Flexible (savings/purchase-redempt,
        side="purchase"). `rate` is the minimum annual lending rate you accept
        (fraction, e.g. 0.01 = 1%); OKX rejects fills below it."""
        return _request("POST", "/api/v5/finance/savings/purchase-redempt", {
            "ccy": coin.upper(), "amt": str(amount),
            "side": "purchase", "rate": str(rate),
        })

    @mcp.tool()
    def okx_earn_redeem(coin: str, amount: float) -> Any:
        """Redeem from OKX Simple Earn Flexible (savings/purchase-redempt,
        side="redempt"). Flexible savings redeems instantly."""
        return _request("POST", "/api/v5/finance/savings/purchase-redempt", {
            "ccy": coin.upper(), "amt": str(amount),
            "side": "redempt", "rate": "0.01",
        })

    return 13
