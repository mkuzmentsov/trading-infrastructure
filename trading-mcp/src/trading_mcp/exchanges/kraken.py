"""Kraken exchange tools — spot trading + Earn (read + allocate/deallocate).

Env vars:
    KRAKEN_API_KEY
    KRAKEN_API_SECRET   (base64-encoded private key, as Kraken displays it)

The key must have the "Create & modify orders" permission for the trading tools,
and "Earn" permissions for allocate/deallocate.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time
import urllib.parse
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

_BASE = "https://api.kraken.com"


def _credentials_present() -> bool:
    return bool(os.environ.get("KRAKEN_API_KEY") and os.environ.get("KRAKEN_API_SECRET"))


def validate() -> dict[str, Any]:
    """Smoke-test Kraken creds: signed Balance call.
    Raises on failure (HMAC mismatch -> EAPI:Invalid signature; nonce -> EAPI:Invalid nonce)."""
    bal = _private("/0/private/Balance") or {}
    return {"asset_count": len(bal), "non_zero_assets": sum(1 for v in bal.values() if float(v or 0) > 0)}


def _sign(path: str, body: dict[str, Any], secret_b64: str) -> str:
    postdata = urllib.parse.urlencode(body)
    sha256 = hashlib.sha256((str(body["nonce"]) + postdata).encode()).digest()
    mac = hmac.new(base64.b64decode(secret_b64), path.encode() + sha256, hashlib.sha512)
    return base64.b64encode(mac.digest()).decode()


def _private(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    api_key = os.environ["KRAKEN_API_KEY"]
    secret = os.environ["KRAKEN_API_SECRET"]
    body: dict[str, Any] = {k: v for k, v in (params or {}).items() if v is not None}
    body["nonce"] = str(int(time.time() * 1000))
    headers = {
        "API-Key": api_key,
        "API-Sign": _sign(path, body, secret),
        "Content-Type": "application/x-www-form-urlencoded",
    }
    r = httpx.post(_BASE + path, data=body, headers=headers, timeout=20)
    r.raise_for_status()
    payload = r.json()
    if payload.get("error"):
        raise RuntimeError(f"Kraken API error: {payload['error']}")
    return payload.get("result", {})


def _norm_pair(pair: str) -> str:
    """Normalize a pair to a Kraken altname AddOrder accepts.
    Accepts "BTC/USDT", "BTC-USDT" or "XBTUSDT"; Kraken uses XBT for BTC."""
    p = pair.upper().replace("/", "").replace("-", "")
    if p.startswith("BTC"):
        p = "XBT" + p[3:]
    return p


def _strategy_apr(strategy: dict[str, Any]) -> float:
    est = strategy.get("apr_estimate") or {}
    for key in ("high", "low"):
        val = est.get(key)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                continue
    return 0.0


def register(mcp: FastMCP) -> int:
    if not _credentials_present():
        return 0

    @mcp.tool()
    def kraken_get_balances() -> dict[str, Any]:
        """All Kraken account balances (spot + Earn-bonded) keyed by asset."""
        return _private("/0/private/Balance")

    @mcp.tool()
    def kraken_get_balances_ex() -> dict[str, Any]:
        """Extended balances: shows hold_trade vs balance per asset."""
        return _private("/0/private/BalanceEx")

    @mcp.tool()
    def kraken_list_earn_strategies(
        asset: str | None = None,
        lock_type: str | None = None,
        limit: int = 64,
    ) -> dict[str, Any]:
        """List Kraken Earn strategies (formerly Staking/Rewards).

        asset: filter by asset code (e.g. "DOT", "ETH").
        lock_type: filter by lock type — "flex" | "bonded" | "timed" | "instant".
        """
        params: dict[str, Any] = {"limit": min(max(limit, 1), 64)}
        if asset:
            params["asset"] = asset.upper()
        if lock_type:
            params["lock_type"] = lock_type.lower()
        return _private("/0/private/Earn/Strategies", params)

    @mcp.tool()
    def kraken_list_earn_allocations() -> dict[str, Any]:
        """Current Kraken Earn allocations across all strategies."""
        return _private("/0/private/Earn/Allocations")

    @mcp.tool()
    def kraken_get_earn_allocation_status(strategy_id: str) -> dict[str, Any]:
        """Status of a pending allocate/deallocate on a Kraken Earn strategy."""
        return _private(
            "/0/private/Earn/AllocateStatus", {"strategy_id": strategy_id}
        )

    # ----- Spot trading -------------------------------------------------

    @mcp.tool()
    def kraken_place_spot_order(
        pair: str,
        side: str,
        volume: float,
        ordertype: str = "limit",
        price: float | None = None,
        validate: bool = False,
        oflags: str | None = None,
        userref: int | None = None,
    ) -> dict[str, Any]:
        """Place a Kraken spot order (AddOrder).

        pair: "BTC/USDT", "ETH/USDT", "LINKUSDT" … (BTC is auto-mapped to XBT).
        side: "buy" | "sell".
        volume: order size in the BASE asset (e.g. BTC amount).
        ordertype: "limit" | "market" (limit requires price).
        validate: True = Kraken-side dry-run — checks the order WITHOUT placing it
            (returns only the parsed descr). Use it to rehearse safely.
        oflags: optional Kraken order flags, e.g. "post" (post-only), "fcib".
        """
        params: dict[str, Any] = {
            "pair": _norm_pair(pair),
            "type": side.lower(),
            "ordertype": ordertype.lower(),
            "volume": str(volume),
        }
        if price is not None:
            params["price"] = str(price)
        if oflags:
            params["oflags"] = oflags
        if userref is not None:
            params["userref"] = userref
        if validate:
            params["validate"] = True
        return _private("/0/private/AddOrder", params)

    @mcp.tool()
    def kraken_cancel_order(txid: str) -> dict[str, Any]:
        """Cancel a Kraken order by its txid (or userref)."""
        return _private("/0/private/CancelOrder", {"txid": txid})

    @mcp.tool()
    def kraken_get_open_orders() -> dict[str, Any]:
        """All open Kraken spot orders (keyed by txid)."""
        return _private("/0/private/OpenOrders")

    # ----- Earn (allocate / deallocate) ---------------------------------

    @mcp.tool()
    def kraken_earn_allocate(strategy_id: str, amount: float) -> dict[str, Any]:
        """Allocate `amount` of the strategy's asset into a Kraken Earn strategy
        (async — poll kraken_get_earn_allocation_status). Use only FLEX/instant
        strategies for a hedge leg so it stays sellable."""
        return _private(
            "/0/private/Earn/Allocate",
            {"strategy_id": strategy_id, "amount": str(amount)},
        )

    @mcp.tool()
    def kraken_earn_deallocate(strategy_id: str, amount: float) -> dict[str, Any]:
        """Deallocate (unstake) `amount` from a Kraken Earn strategy back to the
        spot wallet (flex returns instantly; bonded begins unbonding). Async —
        poll kraken_get_earn_deallocate_status."""
        return _private(
            "/0/private/Earn/Deallocate",
            {"strategy_id": strategy_id, "amount": str(amount)},
        )

    @mcp.tool()
    def kraken_get_earn_deallocate_status(strategy_id: str) -> dict[str, Any]:
        """Status of a pending deallocate on a Kraken Earn strategy."""
        return _private(
            "/0/private/Earn/DeallocateStatus", {"strategy_id": strategy_id}
        )

    @mcp.tool()
    def kraken_find_best_earn_rates(
        asset: str | None = None, top_n: int = 10
    ) -> dict[str, Any]:
        """Rank Kraken Earn strategies by APR (highest first). Returns top_n with
        APR, lock type, asset, min amount, and strategy_id for downstream calls.
        """
        params: dict[str, Any] = {"limit": 64}
        if asset:
            params["asset"] = asset.upper()
        result = _private("/0/private/Earn/Strategies", params)
        items = (result or {}).get("items") or []
        ranked = sorted(items, key=_strategy_apr, reverse=True)[:top_n]
        return {
            "top": [
                {
                    "strategy_id": s.get("id"),
                    "asset": s.get("asset"),
                    "apr_estimate": s.get("apr_estimate"),
                    "lock_type": (s.get("lock_type") or {}).get("type"),
                    "user_min_allocation": s.get("user_min_allocation"),
                    "user_cap": s.get("user_cap"),
                    "can_allocate": s.get("can_allocate"),
                    "can_deallocate": s.get("can_deallocate"),
                    "rewards": s.get("rewards"),
                }
                for s in ranked
            ],
        }

    return 12
