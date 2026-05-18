"""Binance exchange tools.

Covers Spot, USDⓈ-M Futures, COIN-M Futures, Margin (cross + isolated),
Simple Earn, transfers, deposits, and withdrawals.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

import httpx
from binance.client import Client
from mcp.server.fastmcp import FastMCP

_ANNOUNCEMENT_CATALOGS: dict[str, int] = {
    "activities": 93,
    "new-listings": 48,
    "news": 49,
    "delisting": 161,
}


@lru_cache(maxsize=1)
def _client() -> Client:
    api_key = os.environ.get("BINANCE_API_KEY")
    api_secret = os.environ.get("BINANCE_API_SECRET")
    if not api_key or not api_secret:
        raise RuntimeError("BINANCE_API_KEY / BINANCE_API_SECRET not set")
    testnet = os.environ.get("BINANCE_TESTNET", "").lower() in ("1", "true", "yes")
    return Client(api_key, api_secret, testnet=testnet)


def _credentials_present() -> bool:
    return bool(os.environ.get("BINANCE_API_KEY") and os.environ.get("BINANCE_API_SECRET"))


def validate() -> dict[str, Any]:
    """Smoke-test Binance creds with a read-only authenticated call.
    Raises on failure. Returns a small dict on success."""
    acct = _client().get_account()
    return {
        "account_type": acct.get("accountType"),
        "can_trade": acct.get("canTrade"),
        "can_withdraw": acct.get("canWithdraw"),
        "non_zero_balances": sum(
            1 for b in acct.get("balances", [])
            if float(b["free"]) + float(b["locked"]) > 0
        ),
    }


def register(mcp: FastMCP) -> int:
    """Attach Binance tools to the MCP server. Returns count, or 0 if skipped."""
    if not _credentials_present():
        return 0

    # ----- Portfolio ------------------------------------------------------

    @mcp.tool()
    def binance_get_portfolio_overview() -> dict[str, Any]:
        """Aggregate non-zero balances across Binance Spot, USDⓈ-M Futures,
        COIN-M Futures, cross Margin, isolated Margin, and Simple Earn."""
        c = _client()
        out: dict[str, Any] = {}

        try:
            spot = c.get_account()
            out["spot"] = [
                b for b in spot.get("balances", [])
                if float(b["free"]) + float(b["locked"]) > 0
            ]
        except Exception as e:
            out["spot_error"] = str(e)

        try:
            fut = c.futures_account()
            out["futures_usdm"] = {
                "totalWalletBalance": fut.get("totalWalletBalance"),
                "totalUnrealizedProfit": fut.get("totalUnrealizedProfit"),
                "totalMarginBalance": fut.get("totalMarginBalance"),
                "availableBalance": fut.get("availableBalance"),
                "assets": [a for a in fut.get("assets", []) if float(a.get("walletBalance", 0)) > 0],
                "positions": [p for p in fut.get("positions", []) if float(p.get("positionAmt", 0)) != 0],
            }
        except Exception as e:
            out["futures_usdm_error"] = str(e)

        try:
            cfut = c.futures_coin_account()
            out["futures_coinm"] = {
                "assets": [a for a in cfut.get("assets", []) if float(a.get("walletBalance", 0)) > 0],
                "positions": [p for p in cfut.get("positions", []) if float(p.get("positionAmt", 0)) != 0],
            }
        except Exception as e:
            out["futures_coinm_error"] = str(e)

        try:
            m = c.get_margin_account()
            out["margin_cross"] = {
                "totalAssetOfBtc": m.get("totalAssetOfBtc"),
                "totalLiabilityOfBtc": m.get("totalLiabilityOfBtc"),
                "totalNetAssetOfBtc": m.get("totalNetAssetOfBtc"),
                "marginLevel": m.get("marginLevel"),
                "userAssets": [
                    a for a in m.get("userAssets", [])
                    if float(a.get("netAsset", 0)) != 0
                ],
            }
        except Exception as e:
            out["margin_cross_error"] = str(e)

        try:
            im = c.get_isolated_margin_account()
            out["margin_isolated"] = [
                a for a in im.get("assets", [])
                if float(a.get("baseAsset", {}).get("netAsset", 0)) != 0
                or float(a.get("quoteAsset", {}).get("netAsset", 0)) != 0
            ]
        except Exception as e:
            out["margin_isolated_error"] = str(e)

        try:
            out["earn_simple"] = c.get_simple_earn_account_summary()
        except Exception as e:
            out["earn_simple_error"] = str(e)

        return out

    # ----- Market data ---------------------------------------------------

    @mcp.tool()
    def binance_get_price(symbol: str) -> dict[str, Any]:
        """Latest price for a Binance spot symbol (e.g. BTCUSDT)."""
        return _client().get_symbol_ticker(symbol=symbol.upper())

    @mcp.tool()
    def binance_get_klines(symbol: str, interval: str = "1h", limit: int = 100) -> list[list]:
        """Candlesticks for a Binance spot symbol. Interval: 1m, 5m, 15m, 1h, 4h, 1d, ..."""
        return _client().get_klines(symbol=symbol.upper(), interval=interval, limit=limit)

    # ----- Spot ----------------------------------------------------------

    @mcp.tool()
    def binance_get_spot_balances(non_zero_only: bool = True) -> list[dict]:
        """Binance spot wallet balances."""
        balances = _client().get_account().get("balances", [])
        if non_zero_only:
            balances = [b for b in balances if float(b["free"]) + float(b["locked"]) > 0]
        return balances

    @mcp.tool()
    def binance_get_spot_open_orders(symbol: str | None = None) -> list[dict]:
        """Open Binance spot orders, optionally filtered by symbol."""
        kwargs = {"symbol": symbol.upper()} if symbol else {}
        return _client().get_open_orders(**kwargs)

    @mcp.tool()
    def binance_place_spot_order(
        symbol: str,
        side: str,
        type: str = "LIMIT",
        quantity: float | None = None,
        quote_order_qty: float | None = None,
        price: float | None = None,
        time_in_force: str = "GTC",
        client_order_id: str | None = None,
    ) -> dict[str, Any]:
        """Place a Binance spot order.

        side: BUY | SELL
        type: LIMIT | MARKET | STOP_LOSS_LIMIT | TAKE_PROFIT_LIMIT | LIMIT_MAKER
        For MARKET BUY, prefer quote_order_qty (quote currency amount) over quantity.
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
        if type.upper() in ("LIMIT", "STOP_LOSS_LIMIT", "TAKE_PROFIT_LIMIT"):
            params["timeInForce"] = time_in_force
        if client_order_id:
            params["newClientOrderId"] = client_order_id
        return _client().create_order(**params)

    @mcp.tool()
    def binance_cancel_spot_order(
        symbol: str,
        order_id: int | None = None,
        client_order_id: str | None = None,
    ) -> dict[str, Any]:
        """Cancel a Binance spot order by orderId or origClientOrderId."""
        kwargs: dict[str, Any] = {"symbol": symbol.upper()}
        if order_id is not None:
            kwargs["orderId"] = order_id
        if client_order_id:
            kwargs["origClientOrderId"] = client_order_id
        return _client().cancel_order(**kwargs)

    @mcp.tool()
    def binance_get_spot_trade_history(symbol: str, limit: int = 50) -> list[dict]:
        """Recent Binance spot trades on this account for a symbol."""
        return _client().get_my_trades(symbol=symbol.upper(), limit=limit)

    # ----- USDⓈ-M Futures -----------------------------------------------

    @mcp.tool()
    def binance_get_futures_account() -> dict[str, Any]:
        """Binance USDⓈ-M futures account: balances, positions, margin."""
        return _client().futures_account()

    @mcp.tool()
    def binance_get_futures_positions(symbol: str | None = None) -> list[dict]:
        """Open Binance USDⓈ-M futures positions (filtered to non-zero)."""
        kwargs = {"symbol": symbol.upper()} if symbol else {}
        pos = _client().futures_position_information(**kwargs)
        return [p for p in pos if float(p.get("positionAmt", 0)) != 0]

    @mcp.tool()
    def binance_place_futures_order(
        symbol: str,
        side: str,
        type: str = "LIMIT",
        quantity: float | None = None,
        price: float | None = None,
        reduce_only: bool = False,
        time_in_force: str = "GTC",
        position_side: str = "BOTH",
        client_order_id: str | None = None,
    ) -> dict[str, Any]:
        """Place a Binance USDⓈ-M futures order.

        side: BUY | SELL
        type: LIMIT | MARKET | STOP_MARKET | TAKE_PROFIT_MARKET | TRAILING_STOP_MARKET
        """
        params: dict[str, Any] = {
            "symbol": symbol.upper(),
            "side": side.upper(),
            "type": type.upper(),
            "positionSide": position_side.upper(),
        }
        if quantity is not None:
            params["quantity"] = quantity
        if price is not None:
            params["price"] = price
        if type.upper() == "LIMIT":
            params["timeInForce"] = time_in_force
        if reduce_only:
            params["reduceOnly"] = "true"
        if client_order_id:
            params["newClientOrderId"] = client_order_id
        return _client().futures_create_order(**params)

    @mcp.tool()
    def binance_cancel_futures_order(
        symbol: str,
        order_id: int | None = None,
        client_order_id: str | None = None,
    ) -> dict[str, Any]:
        """Cancel a Binance USDⓈ-M futures order."""
        kwargs: dict[str, Any] = {"symbol": symbol.upper()}
        if order_id is not None:
            kwargs["orderId"] = order_id
        if client_order_id:
            kwargs["origClientOrderId"] = client_order_id
        return _client().futures_cancel_order(**kwargs)

    @mcp.tool()
    def binance_get_futures_open_orders(symbol: str | None = None) -> list[dict]:
        """List Binance USDⓈ-M futures open orders."""
        kwargs = {"symbol": symbol.upper()} if symbol else {}
        return _client().futures_get_open_orders(**kwargs)

    @mcp.tool()
    def binance_set_futures_leverage(symbol: str, leverage: int) -> dict[str, Any]:
        """Change leverage for a Binance USDⓈ-M futures symbol."""
        return _client().futures_change_leverage(symbol=symbol.upper(), leverage=leverage)

    @mcp.tool()
    def binance_set_futures_margin_type(symbol: str, margin_type: str) -> dict[str, Any]:
        """Set margin type for a Binance USDⓈ-M symbol: ISOLATED or CROSSED."""
        return _client().futures_change_margin_type(
            symbol=symbol.upper(), marginType=margin_type.upper()
        )

    @mcp.tool()
    def binance_get_futures_funding_rate(symbol: str, limit: int = 10) -> list[dict]:
        """Recent funding rate history for a Binance USDⓈ-M perp."""
        return _client().futures_funding_rate(symbol=symbol.upper(), limit=limit)

    # ----- COIN-M Futures ------------------------------------------------

    @mcp.tool()
    def binance_get_coin_futures_account() -> dict[str, Any]:
        """Binance COIN-M futures account."""
        return _client().futures_coin_account()

    @mcp.tool()
    def binance_get_coin_futures_positions(symbol: str | None = None) -> list[dict]:
        """Open Binance COIN-M futures positions."""
        kwargs = {"pair": symbol.upper()} if symbol else {}
        pos = _client().futures_coin_position_information(**kwargs)
        return [p for p in pos if float(p.get("positionAmt", 0)) != 0]

    @mcp.tool()
    def binance_place_coin_futures_order(
        symbol: str,
        side: str,
        type: str = "LIMIT",
        quantity: float | None = None,
        price: float | None = None,
        reduce_only: bool = False,
        time_in_force: str = "GTC",
        position_side: str = "BOTH",
    ) -> dict[str, Any]:
        """Place a Binance COIN-M futures order."""
        params: dict[str, Any] = {
            "symbol": symbol.upper(),
            "side": side.upper(),
            "type": type.upper(),
            "positionSide": position_side.upper(),
        }
        if quantity is not None:
            params["quantity"] = quantity
        if price is not None:
            params["price"] = price
        if type.upper() == "LIMIT":
            params["timeInForce"] = time_in_force
        if reduce_only:
            params["reduceOnly"] = "true"
        return _client().futures_coin_create_order(**params)

    @mcp.tool()
    def binance_cancel_coin_futures_order(symbol: str, order_id: int) -> dict[str, Any]:
        """Cancel a Binance COIN-M futures order."""
        return _client().futures_coin_cancel_order(symbol=symbol.upper(), orderId=order_id)

    # ----- Margin --------------------------------------------------------

    @mcp.tool()
    def binance_get_margin_account(isolated: bool = False) -> dict[str, Any]:
        """Binance cross- or isolated-margin account snapshot."""
        c = _client()
        return c.get_isolated_margin_account() if isolated else c.get_margin_account()

    @mcp.tool()
    def binance_margin_borrow(
        asset: str, amount: float, isolated_symbol: str | None = None
    ) -> dict[str, Any]:
        """Borrow on Binance margin. For isolated, pass isolated_symbol."""
        kwargs: dict[str, Any] = {"asset": asset.upper(), "amount": amount}
        if isolated_symbol:
            kwargs["isIsolated"] = "TRUE"
            kwargs["symbol"] = isolated_symbol.upper()
        return _client().create_margin_loan(**kwargs)

    @mcp.tool()
    def binance_margin_repay(
        asset: str, amount: float, isolated_symbol: str | None = None
    ) -> dict[str, Any]:
        """Repay a Binance margin loan."""
        kwargs: dict[str, Any] = {"asset": asset.upper(), "amount": amount}
        if isolated_symbol:
            kwargs["isIsolated"] = "TRUE"
            kwargs["symbol"] = isolated_symbol.upper()
        return _client().repay_margin_loan(**kwargs)

    @mcp.tool()
    def binance_place_margin_order(
        symbol: str,
        side: str,
        type: str = "LIMIT",
        quantity: float | None = None,
        price: float | None = None,
        time_in_force: str = "GTC",
        is_isolated: bool = False,
        side_effect_type: str = "NO_SIDE_EFFECT",
    ) -> dict[str, Any]:
        """Place a Binance margin order.

        side_effect_type: NO_SIDE_EFFECT | MARGIN_BUY | AUTO_REPAY
        """
        params: dict[str, Any] = {
            "symbol": symbol.upper(),
            "side": side.upper(),
            "type": type.upper(),
            "isIsolated": "TRUE" if is_isolated else "FALSE",
            "sideEffectType": side_effect_type.upper(),
        }
        if quantity is not None:
            params["quantity"] = quantity
        if price is not None:
            params["price"] = price
        if type.upper() == "LIMIT":
            params["timeInForce"] = time_in_force
        return _client().create_margin_order(**params)

    # ----- Simple Earn ---------------------------------------------------

    @mcp.tool()
    def binance_list_earn_flexible_offers(
        asset: str | None = None, size: int = 50
    ) -> dict[str, Any]:
        """List Binance Simple Earn FLEXIBLE products with current APRs."""
        kwargs: dict[str, Any] = {"size": size}
        if asset:
            kwargs["asset"] = asset.upper()
        return _client().get_simple_earn_flexible_product_list(**kwargs)

    @mcp.tool()
    def binance_list_earn_locked_offers(
        asset: str | None = None, size: int = 50
    ) -> dict[str, Any]:
        """List Binance Simple Earn LOCKED products with APRs + lock periods."""
        kwargs: dict[str, Any] = {"size": size}
        if asset:
            kwargs["asset"] = asset.upper()
        return _client().get_simple_earn_locked_product_list(**kwargs)

    @mcp.tool()
    def binance_get_earn_flexible_positions() -> dict[str, Any]:
        """Current Binance Simple Earn FLEXIBLE positions."""
        return _client().get_simple_earn_flexible_product_position()

    @mcp.tool()
    def binance_get_earn_locked_positions() -> dict[str, Any]:
        """Current Binance Simple Earn LOCKED positions."""
        return _client().get_simple_earn_locked_product_position()

    @mcp.tool()
    def binance_get_dual_investment_positions(
        status: str = "PURCHASE_SUCCESS",
    ) -> dict[str, Any]:
        """Current Binance Dual Investment (Advanced Earn) positions.

        Dual Investment is NOT part of Simple Earn — it has its own endpoint,
        so it is invisible to ``binance_get_earn_*`` and any NAV roll-up that
        only sums Spot + Simple Earn. Use this to capture USDT/coin locked in
        DCI "Buy Low / Sell High" products.

        status: PURCHASE_SUCCESS (active/holding, default) | PENDING |
                SETTLED | PURCHASE_FAIL | REFUNDED. Pass "" for all statuses.
        """
        params: dict[str, Any] = {}
        if status:
            params["status"] = status
        return _client().margin_v1_get_dci_product_positions(**params)

    @mcp.tool()
    def binance_subscribe_earn_flexible(
        product_id: str, amount: float, auto_subscribe: bool = True
    ) -> dict[str, Any]:
        """Subscribe to a Binance Simple Earn FLEXIBLE product."""
        return _client().subscribe_simple_earn_flexible_product(
            productId=product_id, amount=amount, autoSubscribe=str(auto_subscribe).lower()
        )

    @mcp.tool()
    def binance_subscribe_earn_locked(
        project_id: str, amount: float, auto_subscribe: bool = False
    ) -> dict[str, Any]:
        """Subscribe to a Binance Simple Earn LOCKED product."""
        return _client().subscribe_simple_earn_locked_product(
            projectId=project_id, amount=amount, autoSubscribe=str(auto_subscribe).lower()
        )

    @mcp.tool()
    def binance_redeem_earn_flexible(
        product_id: str, amount: float | None = None, redeem_all: bool = False
    ) -> dict[str, Any]:
        """Redeem from a Binance Simple Earn FLEXIBLE position."""
        kwargs: dict[str, Any] = {"productId": product_id}
        if redeem_all:
            kwargs["redeemAll"] = "true"
        elif amount is not None:
            kwargs["amount"] = amount
        return _client().redeem_simple_earn_flexible_product(**kwargs)

    @mcp.tool()
    def binance_redeem_earn_locked(position_id: str) -> dict[str, Any]:
        """Early-redeem a Binance Simple Earn LOCKED position."""
        return _client().redeem_simple_earn_locked_product(positionId=position_id)

    @mcp.tool()
    def binance_find_best_earn_rates(
        asset: str | None = None, top_n: int = 10
    ) -> dict[str, Any]:
        """Discover the highest-APR Binance Simple Earn opportunities. Returns
        top FLEXIBLE and LOCKED products sorted by APR."""
        c = _client()
        flexible = c.get_simple_earn_flexible_product_list(
            **({"asset": asset.upper()} if asset else {}), size=100
        )
        locked = c.get_simple_earn_locked_product_list(
            **({"asset": asset.upper()} if asset else {}), size=100
        )

        def _flex_rate(p: dict) -> float:
            try:
                return float(p.get("latestAnnualPercentageRate", 0))
            except (TypeError, ValueError):
                return 0.0

        def _locked_rate(p: dict) -> float:
            detail = p.get("detail", {}) or {}
            try:
                return float(detail.get("apr", 0))
            except (TypeError, ValueError):
                return 0.0

        flex_rows = sorted(flexible.get("rows", []), key=_flex_rate, reverse=True)[:top_n]
        locked_rows = sorted(locked.get("rows", []), key=_locked_rate, reverse=True)[:top_n]

        return {
            "flexible_top": [
                {
                    "asset": p.get("asset"),
                    "productId": p.get("productId"),
                    "apr": _flex_rate(p),
                    "tierAnnualPercentageRate": p.get("tierAnnualPercentageRate"),
                    "canPurchase": p.get("canPurchase"),
                    "minPurchaseAmount": p.get("minPurchaseAmount"),
                }
                for p in flex_rows
            ],
            "locked_top": [
                {
                    "asset": (p.get("detail") or {}).get("asset"),
                    "projectId": p.get("projectId"),
                    "apr": _locked_rate(p),
                    "duration": (p.get("detail") or {}).get("duration"),
                    "renewable": (p.get("detail") or {}).get("renewable"),
                    "minAmount": (p.get("quota") or {}).get("minimum"),
                    "maxAmount": (p.get("quota") or {}).get("totalPersonalQuota"),
                }
                for p in locked_rows
            ],
        }

    # ----- Promotions / Announcements (public, no auth) -----------------

    @mcp.tool()
    def binance_list_promotions(
        category: str = "activities",
        keywords: list[str] | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Fetch Binance public announcements — trading competitions, airdrops,
        Launchpool, Megadrop, new listings, etc. Uses the public CMS endpoint
        (no API key needed).

        category: activities | new-listings | news | delisting | all
        keywords: optional case-insensitive substrings to filter titles
                  (e.g. ["competition", "airdrop", "launchpool"]).
        """
        cats: list[tuple[str, int]] = []
        cat = category.lower()
        if cat == "all":
            cats = list(_ANNOUNCEMENT_CATALOGS.items())
        elif cat in _ANNOUNCEMENT_CATALOGS:
            cats = [(cat, _ANNOUNCEMENT_CATALOGS[cat])]
        else:
            return {
                "error": f"unknown category {category!r}",
                "valid": list(_ANNOUNCEMENT_CATALOGS) + ["all"],
            }

        results: dict[str, Any] = {}
        kw_lower = [k.lower() for k in (keywords or [])]
        for name, catalog_id in cats:
            url = (
                "https://www.binance.com/bapi/composite/v1/public/cms/article/"
                "list/query"
            )
            params = {
                "type": 1,
                "catalogId": catalog_id,
                "pageNo": 1,
                "pageSize": max(1, min(limit, 50)),
            }
            try:
                r = httpx.get(
                    url,
                    params=params,
                    headers={"User-Agent": "Mozilla/5.0 trading-mcp"},
                    timeout=20,
                )
                r.raise_for_status()
                payload = r.json()
            except Exception as e:  # noqa: BLE001
                results[name] = {"error": str(e)}
                continue

            data = (payload or {}).get("data") or {}
            articles = data.get("articles")
            if not articles:
                catalogs = data.get("catalogs") or []
                articles = catalogs[0].get("articles", []) if catalogs else []
            items = []
            for a in articles:
                title = a.get("title") or ""
                if kw_lower and not any(k in title.lower() for k in kw_lower):
                    continue
                code = a.get("code")
                items.append({
                    "title": title,
                    "releaseDate": a.get("releaseDate"),
                    "url": (
                        f"https://www.binance.com/en/support/announcement/{code}"
                        if code else None
                    ),
                })
            results[name] = items
        return results

    # ----- Dust & Convert ------------------------------------------------

    @mcp.tool()
    def binance_get_dust_assets() -> dict[str, Any]:
        """List Binance Spot balances eligible for dust → BNB conversion.

        Returns each asset's free amount and the BTC/BNB it would convert to,
        plus `totalTransferBtc`/`totalTransferBNB` for the whole batch. Feeds
        ``binance_transfer_dust``.
        """
        return _client().get_dust_assets()

    @mcp.tool()
    def binance_transfer_dust(
        assets: list[str], confirm: bool = False
    ) -> dict[str, Any]:
        """Convert one or more Binance Spot dust assets to BNB.

        ``assets``: list of symbols from ``binance_get_dust_assets`` (e.g.
        ["XRP", "ADA"]). Sent to ``POST /sapi/v1/asset/dust`` as a
        comma-joined ``asset`` param — Binance accepts the batch form.

        Safety: ``confirm`` must be ``True`` to submit. Otherwise a dry-run
        echoes the planned conversion so a human can verify the asset list.
        """
        asset_param = ",".join(a.upper() for a in assets)
        if not confirm:
            return {
                "dry_run": True,
                "warning": "Set confirm=True to actually convert these to BNB.",
                "assets": [a.upper() for a in assets],
                "asset_param": asset_param,
                "note": (
                    "Call binance_get_dust_assets() first to see expected BNB. "
                    "Conversion is one-shot per day per asset on Binance's side."
                ),
            }
        return _client().transfer_dust(asset=asset_param)

    @mcp.tool()
    def binance_get_margin_dust_assets() -> dict[str, Any]:
        """List Binance Cross-Margin balances eligible for dust → BNB
        conversion. Feeds ``binance_transfer_margin_dust``."""
        return _client().get_margin_dust_assets()

    @mcp.tool()
    def binance_transfer_margin_dust(
        assets: list[str], confirm: bool = False
    ) -> dict[str, Any]:
        """Convert one or more Binance Cross-Margin dust assets to BNB.

        Same shape as ``binance_transfer_dust`` but for the margin wallet.
        """
        asset_param = ",".join(a.upper() for a in assets)
        if not confirm:
            return {
                "dry_run": True,
                "warning": "Set confirm=True to actually convert these to BNB.",
                "assets": [a.upper() for a in assets],
                "asset_param": asset_param,
                "wallet": "cross_margin",
            }
        return _client().transfer_margin_dust(asset=asset_param)

    @mcp.tool()
    def binance_convert_quote(
        from_asset: str,
        to_asset: str,
        from_amount: float | None = None,
        to_amount: float | None = None,
    ) -> dict[str, Any]:
        """Request a Binance Convert quote for an arbitrary asset pair.

        Pass EITHER ``from_amount`` (debit side) OR ``to_amount`` (credit
        side), not both. Returns a ``quoteId`` valid for ~10 seconds that you
        accept via ``binance_convert_accept(quote_id)``.

        Use this when dust-to-BNB isn't enough — e.g. converting accumulated
        BNB back to USDT, or moving a stranded altcoin to a stablecoin.
        """
        if (from_amount is None) == (to_amount is None):
            return {
                "error": "pass exactly one of from_amount / to_amount",
            }
        params: dict[str, Any] = {
            "fromAsset": from_asset.upper(),
            "toAsset": to_asset.upper(),
        }
        if from_amount is not None:
            params["fromAmount"] = from_amount
        else:
            params["toAmount"] = to_amount
        return _client().convert_request_quote(**params)

    @mcp.tool()
    def binance_convert_accept(
        quote_id: str, confirm: bool = False
    ) -> dict[str, Any]:
        """Accept a Binance Convert quote by ``quote_id`` from
        ``binance_convert_quote``.

        Safety: ``confirm`` must be ``True`` to submit. Quote expires fast
        (~10s) — fetch a fresh one if the dry-run delays you.
        """
        if not confirm:
            return {
                "dry_run": True,
                "warning": "Set confirm=True to execute this conversion.",
                "quote_id": quote_id,
                "note": "Quotes expire ~10s after issuance — re-quote if stale.",
            }
        return _client().convert_accept_quote(quoteId=quote_id)

    # ----- Transfers -----------------------------------------------------

    @mcp.tool()
    def binance_universal_transfer(
        transfer_type: str, asset: str, amount: float
    ) -> dict[str, Any]:
        """Move funds between Binance wallets. Common transfer_type values:

        MAIN_UMFUTURE, UMFUTURE_MAIN, MAIN_CMFUTURE, CMFUTURE_MAIN,
        MAIN_MARGIN, MARGIN_MAIN, MAIN_FUNDING, FUNDING_MAIN, ...
        """
        return _client().universal_transfer(
            type=transfer_type.upper(), asset=asset.upper(), amount=amount
        )

    @mcp.tool()
    def binance_get_transfer_history(transfer_type: str, limit: int = 20) -> dict[str, Any]:
        """Recent Binance universal transfers of a given type."""
        return _client().query_universal_transfer_history(
            type=transfer_type.upper(), size=limit
        )

    # ----- Deposits & Withdrawals ---------------------------------------

    @mcp.tool()
    def binance_get_deposit_address(coin: str, network: str | None = None) -> dict[str, Any]:
        """Get a Binance deposit address for a coin/network."""
        kwargs: dict[str, Any] = {"coin": coin.upper()}
        if network:
            kwargs["network"] = network.upper()
        return _client().get_deposit_address(**kwargs)

    @mcp.tool()
    def binance_get_deposit_history(
        coin: str | None = None, limit: int = 20
    ) -> list[dict]:
        """Recent Binance deposit history."""
        kwargs: dict[str, Any] = {"limit": limit}
        if coin:
            kwargs["coin"] = coin.upper()
        return _client().get_deposit_history(**kwargs)

    @mcp.tool()
    def binance_get_withdraw_history(
        coin: str | None = None, limit: int = 20
    ) -> list[dict]:
        """Recent Binance withdrawal history."""
        kwargs: dict[str, Any] = {"limit": limit}
        if coin:
            kwargs["coin"] = coin.upper()
        return _client().get_withdraw_history(**kwargs)

    @mcp.tool()
    def binance_withdraw(
        coin: str,
        address: str,
        amount: float,
        network: str | None = None,
        address_tag: str | None = None,
        withdraw_order_id: str | None = None,
        confirm: bool = False,
    ) -> dict[str, Any]:
        """Withdraw a coin from Binance to an external address.

        Safety: ``confirm`` must be ``True`` to actually submit. Otherwise a
        dry-run summary is returned so the human can verify network, address,
        and amount before the irreversible execution.
        """
        if not confirm:
            return {
                "dry_run": True,
                "warning": "Set confirm=True to actually submit this withdrawal.",
                "coin": coin.upper(),
                "amount": amount,
                "address": address,
                "network": network,
                "address_tag": address_tag,
            }
        kwargs: dict[str, Any] = {
            "coin": coin.upper(),
            "address": address,
            "amount": amount,
        }
        if network:
            kwargs["network"] = network.upper()
        if address_tag:
            kwargs["addressTag"] = address_tag
        if withdraw_order_id:
            kwargs["withdrawOrderId"] = withdraw_order_id
        return _client().withdraw(**kwargs)

    return 39  # number of tools registered above
