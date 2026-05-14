"""WhiteBIT exchange tools — balances + fee/market info.

Smart Staking is intentionally NOT exposed: WhiteBIT does not publish a REST
API for it (all `*/smart-staking/*` paths return 404). The Smart Staking
catalog must be browsed via the web UI at https://whitebit.com/staking.

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

    @mcp.tool()
    def whitebit_smart_staking_info() -> dict[str, Any]:
        """WhiteBIT Smart Staking is **not available via REST API** as of
        2026-05. All `*/smart-staking/*` paths return 404. Use the web UI."""
        return {
            "available_via_api": False,
            "reason": "WhiteBIT does not expose smart-staking endpoints via REST",
            "browse_url": "https://whitebit.com/staking",
            "alternative": (
                "Use `binance_find_best_earn_rates` and "
                "`kraken_find_best_earn_rates` for API-accessible yield"
            ),
        }

    return 5
