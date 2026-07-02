"""Cross-venue aggregator tools.

These tools fan out to whichever exchange modules have credentials configured,
merge the results, and return a normalized view. Each individual venue call is
wrapped so missing creds / upstream errors degrade gracefully into a per-venue
"skipped" / "error" entry rather than failing the whole call.

Currently covered: Binance, Kraken, WhiteBIT, Hyperliquid. (Bybit + OKX modules
were drafted then removed — see project_trading_mcp_profit_maximization memo.)
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from . import binance as _bn
from . import bitget as _bg
from . import bybit as _by
from . import hyperliquid as _hl
from . import kraken as _kr
from . import kraken_futures as _krf
from . import mexc as _mx
from . import whitebit as _wb

# Stablecoins we treat as $1 for NAV roll-ups when a venue lacks a USD oracle.
_USD_STABLES = {
    "USDT", "USDC", "BUSD", "DAI", "FDUSD", "TUSD", "USD", "USDD", "USDE", "PYUSD",
}


def _safe(call):
    """Run a venue call, return result or {"error": str}. Used to keep one venue
    failing from blowing up the cross-venue tool."""
    try:
        return call()
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


def _f(v: Any) -> float | None:
    """Parse a numeric string/None to float, or None."""
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _binance_spot_price(symbol: str) -> float | None:
    """USDT-quoted spot price for a coin via Binance, or None on failure."""
    if not _bn._credentials_present():
        return None
    try:
        return float(_bn._client().get_symbol_ticker(symbol=symbol)["price"])
    except Exception:  # noqa: BLE001
        return None


def _usd_value(asset: str, qty: float) -> float | None:
    """Best-effort USD valuation of qty <asset>. None if not pricable."""
    if qty == 0:
        return 0.0
    asset_u = asset.upper()
    if asset_u in _USD_STABLES:
        return qty
    px = _binance_spot_price(asset_u + "USDT")
    if px is not None:
        return qty * px
    # Fallback: WhiteBIT public ticker (prices venue tokens like WBT that have
    # no Binance pair). Public endpoint — no creds needed.
    try:
        import httpx

        r = httpx.get("https://whitebit.com/api/v4/public/ticker", timeout=10)
        r.raise_for_status()
        t = (r.json() or {}).get(f"{asset_u}_USDT") or {}
        last = t.get("last_price")
        if last is not None:
            return qty * float(last)
    except Exception:  # noqa: BLE001
        pass
    return None


def register(mcp: FastMCP) -> int:
    """Aggregator tools always register — they internally degrade per-venue."""

    # ----- 1. Cross-venue yield comparator ------------------------------

    @mcp.tool()
    def find_best_yield_anywhere(
        asset: str | None = None, top_n: int = 15
    ) -> dict[str, Any]:
        """Best APR for parking an asset across every configured venue.

        Sources scanned: Binance Simple Earn (flexible + locked), Kraken Earn,
        Hyperliquid HLP (USDC only), WhiteBIT Crypto Lending, Bybit Earn,
        Bitget Savings.

        Returns rows sorted by APR descending. Each row has {venue, kind, asset,
        apr, duration_days, …}. Use this *before* picking an Earn product.
        """
        rows: list[dict[str, Any]] = []

        # --- Binance Simple Earn ---
        if _bn._credentials_present():
            def _binance():
                c = _bn._client()
                kw: dict[str, Any] = {"size": 100}
                if asset:
                    kw["asset"] = asset.upper()
                flex = c.get_simple_earn_flexible_product_list(**kw).get("rows", [])
                lock = c.get_simple_earn_locked_product_list(**kw).get("rows", [])
                out: list[dict[str, Any]] = []
                for p in flex:
                    try:
                        apr = float(p.get("latestAnnualPercentageRate") or 0)
                    except (TypeError, ValueError):
                        continue
                    out.append({
                        "venue": "binance",
                        "kind": "simple_earn_flexible",
                        "asset": p.get("asset"),
                        "apr": apr,
                        "duration_days": 0,
                        "product_id": p.get("productId"),
                        "can_purchase": p.get("canPurchase"),
                    })
                for p in lock:
                    detail = p.get("detail") or {}
                    try:
                        apr = float(detail.get("apr") or 0)
                    except (TypeError, ValueError):
                        continue
                    out.append({
                        "venue": "binance",
                        "kind": "simple_earn_locked",
                        "asset": detail.get("asset"),
                        "apr": apr,
                        "duration_days": detail.get("duration"),
                        "project_id": p.get("projectId"),
                    })
                return out

            res = _safe(_binance)
            if isinstance(res, list):
                rows.extend(res)
            else:
                rows.append({"venue": "binance", "error": res.get("error")})

        # --- Kraken Earn ---
        if _kr._credentials_present():
            def _kraken():
                params: dict[str, Any] = {"limit": 64}
                if asset:
                    params["asset"] = asset.upper()
                result = _kr._private("/0/private/Earn/Strategies", params)
                out: list[dict[str, Any]] = []
                for s in (result or {}).get("items") or []:
                    apr = _kr._strategy_apr(s)
                    out.append({
                        "venue": "kraken",
                        "kind": f"earn_{(s.get('lock_type') or {}).get('type') or 'unknown'}",
                        "asset": s.get("asset"),
                        "apr": apr / 100 if apr > 1 else apr,  # Kraken ships % already
                        "strategy_id": s.get("id"),
                        "min": s.get("user_min_allocation"),
                    })
                return out

            res = _safe(_kraken)
            if isinstance(res, list):
                rows.extend(res)
            else:
                rows.append({"venue": "kraken", "error": res.get("error")})

        # --- Hyperliquid HLP (USDC) ---
        if _hl._credentials_present() and (asset is None or asset.upper() == "USDC"):
            def _hlp():
                details: dict[str, Any] = {}
                try:
                    details = _hl._info().query_vault_details(_hl.HLP_VAULT_ADDRESS) or {}
                except Exception:  # noqa: BLE001
                    return None
                apr = None
                for k in ("apr", "annualReturn", "yearlyReturn"):
                    v = details.get(k)
                    if v is None:
                        continue
                    try:
                        apr = float(v)
                        break
                    except (TypeError, ValueError):
                        continue
                return {
                    "venue": "hyperliquid",
                    "kind": "hlp_vault",
                    "asset": "USDC",
                    "apr": apr if apr is not None else 0.0,
                    "duration_days": 4,
                    "vault_address": _hl.HLP_VAULT_ADDRESS,
                    "notes": "4-day withdraw lock from last deposit; APR varies week-to-week",
                }

            res = _safe(_hlp)
            if isinstance(res, dict) and "error" not in res and res is not None:
                rows.append(res)
            elif isinstance(res, dict) and "error" in res:
                rows.append({"venue": "hyperliquid", "error": res["error"]})

        # --- WhiteBIT Crypto Lending (Smart-Flex) ---
        if _wb._credentials_present():
            def _whitebit():
                params = {"ticker": asset.upper()} if asset else None
                plans = _wb._private("/api/v4/main-account/smart-flex/plans", params)
                out = []
                for p in plans if isinstance(plans, list) else []:
                    try:
                        apr = float(str(p.get("apr") or p.get("interest") or 0).replace("%", ""))
                    except (TypeError, ValueError):
                        continue
                    out.append({
                        "venue": "whitebit", "kind": "crypto_lending_flex",
                        "asset": p.get("ticker"), "apr": apr / 100 if apr > 1 else apr,
                        "plan_id": p.get("id") or p.get("planId"),
                    })
                return out

            res = _safe(_whitebit)
            if isinstance(res, list):
                rows.extend(res)
            elif isinstance(res, dict) and "error" in res:
                rows.append({"venue": "whitebit", "error": res["error"]})

        # --- Bybit Earn (FlexibleSaving) ---
        if _by._credentials_present():
            def _bybit():
                params = {"category": "FlexibleSaving"}
                if asset:
                    params["coin"] = asset.upper()
                result = _by._request("GET", "/v5/earn/product", params)
                out = []
                for p in result.get("list") or []:
                    v = p.get("estimateApr")
                    if v is None:
                        continue
                    try:
                        raw = str(v).strip()
                        f = float(raw.replace("%", ""))
                        apr = f / 100 if ("%" in raw or f > 1) else f
                    except (TypeError, ValueError):
                        continue
                    out.append({
                        "venue": "bybit", "kind": "earn_flexible", "asset": p.get("coin"),
                        "apr": apr, "product_id": p.get("productId"),
                    })
                return out

            res = _safe(_bybit)
            if isinstance(res, list):
                rows.extend(res)
            elif isinstance(res, dict) and "error" in res:
                rows.append({"venue": "bybit", "error": res["error"]})

        # --- Bitget Savings ---
        if _bg._credentials_present():
            def _bitget():
                params = {"filter": "available"}
                if asset:
                    params["coin"] = asset.upper()
                data = _bg._request("GET", "/api/v2/earn/savings/product", params)
                prods = data if isinstance(data, list) else (data or {}).get("resultList") or []
                out = []
                for p in prods:
                    best = 0.0
                    for tier in p.get("apyList") or []:
                        for k in ("currentApy", "apy", "rate"):
                            vv = tier.get(k)
                            if vv is not None:
                                try:
                                    best = max(best, float(str(vv).replace("%", "")))
                                except (TypeError, ValueError):
                                    pass
                    if best <= 0:
                        continue
                    out.append({
                        "venue": "bitget", "kind": f"savings_{p.get('periodType')}",
                        "asset": p.get("coin"), "apr": best / 100,
                        "product_id": p.get("productId"),
                    })
                return out

            res = _safe(_bitget)
            if isinstance(res, list):
                rows.extend(res)
            elif isinstance(res, dict) and "error" in res:
                rows.append({"venue": "bitget", "error": res["error"]})

        rankable = [r for r in rows if "apr" in r and "error" not in r]
        rankable.sort(key=lambda r: r.get("apr") or 0, reverse=True)
        errors = [r for r in rows if "error" in r]
        return {"top": rankable[:top_n], "errors": errors, "total_products_scanned": len(rankable)}

    # ----- 2. Borrow rate (Binance cross-margin only for now) -----------

    @mcp.tool()
    def find_cheapest_borrow(asset: str) -> dict[str, Any]:
        """Daily / annualized borrow rate for an asset.

        Currently scans Binance cross-margin only (the only configured venue
        with a borrow-rate endpoint). Kept as an aggregator so adding venues
        later (Kraken margin, etc.) doesn't require reshaping the call.
        """
        rows: list[dict[str, Any]] = []
        asset_u = asset.upper()

        if _bn._credentials_present():
            def _binance_rate():
                c = _bn._client()
                hist = c.get_margin_interest_rate_history(asset=asset_u, size=1)
                if not hist:
                    return None
                daily = float(hist[0].get("dailyInterestRate") or 0)
                return {
                    "venue": "binance",
                    "kind": "cross_margin",
                    "asset": asset_u,
                    "daily_rate": daily,
                    "apr": daily * 365,
                    "timestamp_ms": hist[0].get("timestamp"),
                }

            res = _safe(_binance_rate)
            if isinstance(res, dict) and "error" not in res and res is not None:
                rows.append(res)
            elif isinstance(res, dict) and "error" in res:
                rows.append({"venue": "binance", "error": res["error"]})

        rankable = [r for r in rows if "apr" in r and "error" not in r]
        rankable.sort(key=lambda r: r["apr"])
        return {
            "asset": asset_u,
            "cheapest_first": rankable,
            "errors": [r for r in rows if "error" in r],
        }

    # ----- 3. Cross-venue perp funding comparator -----------------------

    @mcp.tool()
    def compare_perp_funding(coin: str) -> dict[str, Any]:
        """Side-by-side current funding rate (annualized) for a coin's perp
        across Hyperliquid, Binance USDⓈ-M, Kraken Futures, Bybit, Bitget & MEXC.

        Direct feeder for funding-carry basket expansion: identifies the venue
        offering the wider funding spread vs the long leg.
        """
        coin_u = coin.upper()
        usdt = f"{coin_u}USDT"
        rows: list[dict[str, Any]] = []

        if _hl._credentials_present():
            def _hl_call():
                meta, ctxs = _hl._info().meta_and_asset_ctxs()
                for asset, ctx in zip(meta.get("universe", []), ctxs):
                    if (asset.get("name") or "").upper() != coin_u:
                        continue
                    try:
                        hourly = float(ctx.get("funding") or 0)
                    except (TypeError, ValueError):
                        return None
                    return {
                        "venue": "hyperliquid",
                        "symbol": coin_u,
                        "hourly": hourly,
                        "apr": hourly * 24 * 365,
                        "interval_h": 1,
                        "open_interest": ctx.get("openInterest"),
                    }
                return None

            res = _safe(_hl_call)
            if isinstance(res, dict):
                rows.append(res)

        if _bn._credentials_present():
            def _bn_call():
                mp = _bn._client().futures_mark_price(symbol=usdt)
                fr = float(mp.get("lastFundingRate") or 0)
                return {
                    "venue": "binance_usdm",
                    "symbol": usdt,
                    "hourly": fr / 8,
                    "apr": fr * 3 * 365,
                    "interval_h": 8,
                    "next_funding_time": mp.get("nextFundingTime"),
                }

            res = _safe(_bn_call)
            if isinstance(res, dict):
                rows.append(res)

        if _krf._credentials_present():
            def _krf_call():
                symbol = _krf._pf_symbol(coin_u)
                payload = _krf._request("GET", "/api/v3/tickers", public=True)
                for t in payload.get("tickers") or []:
                    if (t.get("symbol") or "").upper() != symbol:
                        continue
                    apr = _krf._ticker_apr(t)
                    if apr is None:
                        return None
                    return {
                        "venue": "kraken_futures",
                        "symbol": symbol,
                        "hourly": apr / (24 * 365),
                        "apr": apr,
                        "interval_h": 1,
                        "open_interest": t.get("openInterest"),
                    }
                return None

            res = _safe(_krf_call)
            if isinstance(res, dict):
                rows.append(res)

        # New venues — public funding data, always included for comparison
        # (all pay funding on an 8h cycle: apr = rate × 3 × 365).
        import httpx as _hx

        def _bybit_call():
            r = _hx.get("https://api.bybit.com/v5/market/tickers",
                        params={"category": "linear", "symbol": usdt}, timeout=15)
            lst = ((r.json() or {}).get("result") or {}).get("list") or []
            if not lst:
                return None
            fr = float(lst[0].get("fundingRate") or 0)
            return {"venue": "bybit", "symbol": usdt, "hourly": fr / 8,
                    "apr": fr * 3 * 365, "interval_h": 8,
                    "open_interest": lst[0].get("openInterest")}

        res = _safe(_bybit_call)
        if isinstance(res, dict):
            rows.append(res)

        def _bitget_call():
            r = _hx.get("https://api.bitget.com/api/v2/mix/market/tickers",
                        params={"productType": "USDT-FUTURES"}, timeout=15)
            for t in (r.json() or {}).get("data") or []:
                if (t.get("symbol") or "").upper() == usdt:
                    fr = float(t.get("fundingRate") or 0)
                    return {"venue": "bitget", "symbol": usdt, "hourly": fr / 8,
                            "apr": fr * 3 * 365, "interval_h": 8,
                            "open_interest": t.get("holdingAmount")}
            return None

        res = _safe(_bitget_call)
        if isinstance(res, dict):
            rows.append(res)

        def _mexc_call():
            sym = f"{coin_u}_USDT"
            r = _hx.get(
                f"https://contract.mexc.com/api/v1/contract/funding_rate/{sym}", timeout=15
            )
            fr = ((r.json() or {}).get("data") or {}).get("fundingRate")
            if fr is None:
                return None
            fr = float(fr)
            return {"venue": "mexc", "symbol": sym, "hourly": fr / 8,
                    "apr": fr * 3 * 365, "interval_h": 8}

        res = _safe(_mexc_call)
        if isinstance(res, dict):
            rows.append(res)

        rankable = [r for r in rows if "error" not in r]
        rankable.sort(key=lambda r: r["apr"], reverse=True)
        spread = None
        if len(rankable) >= 2:
            spread = rankable[0]["apr"] - rankable[-1]["apr"]
        return {
            "coin": coin_u,
            "by_apr_desc": rankable,
            "max_apr_spread": spread,
            "carry_hint": (
                "Short the venue with highest APR, long the venue (or spot) "
                "with the lowest." if spread else None
            ),
        }

    # ----- 3b. Carry entry basis (real order books) ---------------------

    @mcp.tool()
    def carry_basis(
        coin: str,
        notional_usd: float = 1000.0,
        short_venue: str = "hyperliquid",
        long_venue: str = "binance",
    ) -> dict[str, Any]:
        """Entry basis for a delta-neutral funding carry, from REAL order books
        (not marks/mids). The perp we SHORT fills at short_venue's best BID; the
        spot we BUY fills at long_venue's best ASK.

        Returns taker_basis_bps = (short_bid − long_ask)/long_ask×1e4 (cross both
        spreads) and maker_basis_bps = (short_bid − long_bid)/long_bid×1e4 (passive
        buy at the bid), plus whether each top level absorbs notional_usd. Open when
        taker_basis_bps ≥ −5 (favourable/flat); use a maker buy if only maker passes.

        short_venue: hyperliquid | binance | kraken_futures | bybit | bitget.
        long_venue:  binance | kraken.
        """
        import httpx

        coin_u = coin.upper()

        def _perp_bid(venue: str) -> dict[str, Any] | None:
            if venue == "hyperliquid":
                lv = (_hl._info().l2_snapshot(coin_u) or {}).get("levels") or [[], []]
                if not lv[0]:
                    return None
                top = lv[0][0]
                return {
                    "bid": float(top["px"]),
                    "top_usd": float(top["px"]) * float(top["sz"]),
                    "depth_usd": sum(float(x["px"]) * float(x["sz"]) for x in lv[0][:10]),
                }
            if venue == "binance":
                bids = (_bn._client().futures_order_book(symbol=f"{coin_u}USDT", limit=20).get("bids")) or []
                if not bids:
                    return None
                return {
                    "bid": float(bids[0][0]),
                    "top_usd": float(bids[0][0]) * float(bids[0][1]),
                    "depth_usd": sum(float(p) * float(q) for p, q in bids),
                }
            if venue == "kraken_futures":
                r = httpx.get(
                    "https://futures.kraken.com/derivatives/api/v3/orderbook",
                    params={"symbol": _krf._pf_symbol(coin_u)}, timeout=15,
                )
                bids = ((r.json() or {}).get("orderBook") or {}).get("bids") or []
                if not bids:
                    return None
                return {
                    "bid": float(bids[0][0]),
                    "top_usd": float(bids[0][0]) * float(bids[0][1]),
                    "depth_usd": sum(float(p) * float(q) for p, q in bids),
                }
            if venue == "bybit":
                r = httpx.get(
                    "https://api.bybit.com/v5/market/orderbook",
                    params={"category": "linear", "symbol": f"{coin_u}USDT", "limit": 25},
                    timeout=15,
                )
                bids = (((r.json() or {}).get("result") or {}).get("b")) or []
                if not bids:
                    return None
                return {
                    "bid": float(bids[0][0]),
                    "top_usd": float(bids[0][0]) * float(bids[0][1]),
                    "depth_usd": sum(float(p) * float(q) for p, q in bids),
                }
            if venue == "bitget":
                r = httpx.get(
                    "https://api.bitget.com/api/v2/mix/market/orderbook",
                    params={"symbol": f"{coin_u}USDT", "productType": "USDT-FUTURES", "limit": 25},
                    timeout=15,
                )
                bids = ((r.json() or {}).get("data") or {}).get("bids") or []
                if not bids:
                    return None
                return {
                    "bid": float(bids[0][0]),
                    "top_usd": float(bids[0][0]) * float(bids[0][1]),
                    "depth_usd": sum(float(p) * float(q) for p, q in bids),
                }
            return None

        def _spot_ba(venue: str) -> dict[str, Any] | None:
            if venue == "binance":
                ob = _bn._client().get_order_book(symbol=f"{coin_u}USDT", limit=20)
                bids, asks = ob.get("bids") or [], ob.get("asks") or []
                if not bids or not asks:
                    return None
                return {
                    "bid": float(bids[0][0]), "ask": float(asks[0][0]),
                    "top_ask_usd": float(asks[0][0]) * float(asks[0][1]),
                    "ask_depth_usd": sum(float(p) * float(q) for p, q in asks),
                }
            if venue == "kraken":
                pair = ("XBT" if coin_u == "BTC" else coin_u) + "USD"
                r = httpx.get("https://api.kraken.com/0/public/Depth",
                              params={"pair": pair, "count": 20}, timeout=15)
                res = (r.json() or {}).get("result") or {}
                if not res:
                    return None
                book = next(iter(res.values()))
                bids, asks = book.get("bids") or [], book.get("asks") or []
                if not bids or not asks:
                    return None
                return {
                    "bid": float(bids[0][0]), "ask": float(asks[0][0]),
                    "top_ask_usd": float(asks[0][0]) * float(asks[0][1]),
                    "ask_depth_usd": sum(float(px) * float(q) for px, q, *_ in asks),
                }
            return None

        short = _safe(lambda: _perp_bid(short_venue))
        long = _safe(lambda: _spot_ba(long_venue))
        if not isinstance(short, dict) or "bid" not in short:
            return {"error": f"no perp book for {coin_u} on {short_venue}", "detail": short}
        if not isinstance(long, dict) or "ask" not in long:
            return {"error": f"no spot book for {coin_u} on {long_venue}", "detail": long}

        taker = (short["bid"] - long["ask"]) / long["ask"] * 1e4
        maker = (short["bid"] - long["bid"]) / long["bid"] * 1e4
        return {
            "coin": coin_u,
            "short_venue": short_venue,
            "long_venue": long_venue,
            "notional_usd": notional_usd,
            "short_bid": short["bid"],
            "long_ask": long["ask"],
            "long_bid": long["bid"],
            "taker_basis_bps": round(taker, 2),
            "maker_basis_bps": round(maker, 2),
            "gate_taker_pass": taker >= -5,
            "gate_maker_pass": maker >= -5,
            "short_top_absorbs_notional": (short.get("top_usd") or 0) >= notional_usd,
            "long_top_absorbs_notional": (long.get("top_ask_usd") or 0) >= notional_usd,
            "short_bid_depth_usd": short.get("depth_usd"),
            "long_ask_depth_usd": long.get("ask_depth_usd"),
            "hint": "Short fills at short_bid, buy at long_ask. Open when taker_basis_bps >= -5.",
        }

    @mcp.tool()
    def get_server_time() -> dict[str, Any]:
        """Authoritative server time (UTC). Date reports/logs off this rather than
        the model's clock — matters for scheduled/headless runs."""
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        return {
            "utc_iso": now.isoformat(),
            "date": now.strftime("%Y-%m-%d"),
            "epoch_ms": int(now.timestamp() * 1000),
        }

    # ----- 3c. Cross-venue transfer planner -----------------------------

    @mcp.tool()
    def plan_transfer(
        asset: str, amount: float, from_venue: str, to_venue: str
    ) -> dict[str, Any]:
        """Plan a stablecoin move between venues (READ-ONLY — then execute with the
        source venue's own withdraw tool). Returns the source's withdrawal networks
        + fees (cheapest first), the receiving deposit address, and — for a Kraken
        source — the whitelisted addresses (kraken_withdraw needs the 'key').

        from_venue: binance | kraken.  to_venue: binance | kraken | whitebit | hyperliquid.
        """
        asset_u = asset.upper()
        out: dict[str, Any] = {
            "asset": asset_u, "amount": amount, "from": from_venue, "to": to_venue,
        }

        nets: list[dict[str, Any]] = []
        if from_venue == "binance":
            info = _safe(lambda: _bn._client().get_all_coins_info())
            for c in info if isinstance(info, list) else []:
                if c.get("coin") == asset_u:
                    for n in c.get("networkList") or []:
                        if n.get("withdrawEnable"):
                            try:
                                fee = float(n.get("withdrawFee") or 0)
                            except (TypeError, ValueError):
                                fee = None
                            nets.append({
                                "network": n.get("network"), "fee": fee,
                                "min": n.get("withdrawMin"),
                            })
        elif from_venue == "kraken":
            methods = _safe(
                lambda: _kr._private("/0/private/WithdrawMethods", {"asset": asset_u})
            )
            for m in methods if isinstance(methods, list) else []:
                nets.append({
                    "network": m.get("network") or m.get("method"),
                    "minimum": m.get("minimum"),
                    "fee": "kraken_withdraw dry-run (needs a whitelisted key)",
                })
        else:
            out["source_note"] = f"withdrawal-network lookup not wired for {from_venue}"
        nets.sort(key=lambda n: n["fee"] if isinstance(n.get("fee"), (int, float)) else 9e9)
        out["source_networks"] = nets
        out["cheapest_network"] = nets[0]["network"] if nets else None

        if to_venue == "hyperliquid":
            out["dest"] = {"venue": "hyperliquid", "note": (
                "HL takes USDC via the Arbitrum bridge — a CEX withdrawal can't deposit to HL "
                "directly. Withdraw to your own Arbitrum wallet, deposit to HL (credits the "
                "MASTER), then transfer master->sub.")}
        elif to_venue == "binance":
            net = out.get("cheapest_network")
            addr = _safe(
                lambda: _bn._client().get_deposit_address(coin=asset_u, network=net)
            ) if net else None
            out["dest"] = {
                "venue": "binance", "network": net,
                "address": addr.get("address") if isinstance(addr, dict) else None,
            }
        elif to_venue == "kraken":
            out["dest"] = {"venue": "kraken",
                           "note": "kraken_get_deposit_methods(asset) -> kraken_get_deposit_address(asset, method)"}
        elif to_venue == "whitebit":
            out["dest"] = {"venue": "whitebit",
                           "note": "whitebit_get_deposit_address(ticker, network)"}

        if from_venue == "kraken":
            wl = _safe(lambda: _kr._private("/0/private/WithdrawAddresses", {"asset": asset_u}))
            out["kraken_whitelisted"] = [
                {"key": w.get("key"), "address": w.get("address"), "method": w.get("method")}
                for w in (wl if isinstance(wl, list) else [])
            ]
            out["note"] = "Kraken withdraws only to a whitelisted address — pass its 'key' to kraken_withdraw."

        return out

    @mcp.tool()
    def withdraw_fee(
        asset: str, from_venue: str, network: str | None = None
    ) -> dict[str, Any]:
        """Withdrawal fee for an asset from a venue, per network (cheapest first) —
        call this before shuffling capital so the move only fires if worth it.
        from_venue: binance | bybit | bitget | mexc | whitebit | hyperliquid | kraken.
        Returns {venue, asset, networks:[{network, fee, min}], cheapest, note?}.
        Fees are in the ASSET's units (for stablecoins ≈ USD)."""
        import httpx as _hx

        asset_u = asset.upper()
        nets: list[dict[str, Any]] = []
        note: str | None = None

        if from_venue == "binance":
            info = _safe(lambda: _bn._client().get_all_coins_info())
            for c in info if isinstance(info, list) else []:
                if c.get("coin") == asset_u:
                    for n in c.get("networkList") or []:
                        if n.get("withdrawEnable"):
                            nets.append({"network": n.get("network"), "fee": _f(n.get("withdrawFee")), "min": n.get("withdrawMin")})
        elif from_venue == "bybit":
            res = _safe(lambda: _by._request("GET", "/v5/asset/coin/query-info", {"coin": asset_u}))
            for row in ((res.get("rows") if isinstance(res, dict) else None) or []):
                if (row.get("coin") or "").upper() == asset_u:
                    for ch in row.get("chains") or []:
                        nets.append({"network": ch.get("chain"), "fee": _f(ch.get("withdrawFee")), "min": ch.get("withdrawMin")})
        elif from_venue == "bitget":
            r = _safe(lambda: _hx.get("https://api.bitget.com/api/v2/spot/public/coins", params={"coin": asset_u}, timeout=15).json())
            for c in ((r.get("data") if isinstance(r, dict) else None) or []):
                for ch in c.get("chains") or []:
                    nets.append({"network": ch.get("chain"), "fee": _f(ch.get("withdrawFee")), "min": ch.get("minWithdrawAmount")})
        elif from_venue == "mexc":
            info = _safe(lambda: _mx._signed("GET", "/api/v3/capital/config/getall"))
            for c in info if isinstance(info, list) else []:
                if (c.get("coin") or "").upper() == asset_u:
                    for n in c.get("networkList") or []:
                        nets.append({"network": n.get("network") or n.get("netWork"), "fee": _f(n.get("withdrawFee")), "min": n.get("withdrawMin")})
        elif from_venue == "whitebit":
            fees = _safe(lambda: _wb._private("/api/v4/main-account/fee"))
            entry = fees.get(asset_u) if isinstance(fees, dict) else None
            if isinstance(entry, dict):
                wd = entry.get("withdraw") or {}
                nets.append({"network": "default", "fee": _f(wd.get("fixed")), "min": wd.get("min_amount"), "flex_pct": wd.get("flex")})
            note = "WhiteBIT may add a % (flex) on top of the fixed fee; see whitebit_get_fee_schedule for per-network detail."
        elif from_venue == "hyperliquid":
            nets.append({"network": "arbitrum", "fee": 1.0, "min": None})
            note = "HL USDC withdrawal to Arbitrum is a flat ~$1."
        elif from_venue == "kraken":
            note = "Kraken doesn't expose withdrawal fees pre-whitelist — use kraken_withdraw(confirm=False) on a whitelisted key for the exact fee, or kraken_get_withdraw_methods for networks."
        else:
            return {"error": f"unknown venue '{from_venue}'"}

        priced = sorted([n for n in nets if isinstance(n.get("fee"), (int, float))], key=lambda n: n["fee"])
        if network:
            match = next((n for n in nets if (n.get("network") or "").upper() == network.upper()), None)
            return {"venue": from_venue, "asset": asset_u, "network": network,
                    "fee": (match or {}).get("fee"), "networks": nets, "note": note}
        return {"venue": from_venue, "asset": asset_u, "networks": nets,
                "cheapest": priced[0] if priced else None, "note": note}

    @mcp.tool()
    def estimate_rebalance_cost(moves: list[dict[str, Any]]) -> dict[str, Any]:
        """Total withdrawal fees for a multi-leg shuffle. `moves` = list of
        {asset, from_venue, network?(optional)}. Returns each move's cheapest fee
        + the summed total (asset units; for stablecoins ≈ USD). Use to decide
        whether a rebalance's benefit beats the fees before executing."""
        out: list[dict[str, Any]] = []
        total = 0.0
        for m in moves or []:
            info = withdraw_fee(m.get("asset"), m.get("from_venue"), m.get("network"))
            if m.get("network"):
                fee, net = info.get("fee"), m.get("network")
            else:
                ch = info.get("cheapest") or {}
                fee, net = ch.get("fee"), ch.get("network")
            if isinstance(fee, (int, float)):
                total += fee
            out.append({**m, "network": net, "fee": fee})
        return {
            "moves": out,
            "total_fee": round(total, 6),
            "note": "Fees in each asset's units (stablecoins ≈ USD). Kraken legs need a whitelisted-key dry-run for the exact fee.",
        }

    # ----- 4. Aggregated NAV + idle-cash flagger ------------------------

    @mcp.tool()
    def get_total_nav(idle_threshold_usd: float = 500.0) -> dict[str, Any]:
        """Roll up best-effort USD NAV across every configured venue, plus a
        list of stablecoin balances ≥ `idle_threshold_usd` sitting *outside*
        any Earn product (idle cash that could be earning yield).

        Caveat: non-stable asset prices come from Binance spot; tokens with no
        USDT pair on Binance get `usd: null` and are listed in `unpriced`.
        """
        per_venue: dict[str, Any] = {}
        idle: list[dict[str, Any]] = []
        unpriced: list[dict[str, Any]] = []
        total_usd = 0.0

        def _track(venue: str, asset: str, qty: float, location: str) -> None:
            nonlocal total_usd
            if qty <= 0:
                return
            usd = _usd_value(asset, qty)
            if usd is None:
                unpriced.append({"venue": venue, "asset": asset, "qty": qty, "location": location})
                return
            total_usd += usd
            if asset.upper() in _USD_STABLES and usd >= idle_threshold_usd and "earn" not in location.lower():
                idle.append({
                    "venue": venue, "asset": asset, "qty": qty,
                    "usd": usd, "location": location,
                })

        if _bn._credentials_present():
            def _bn_nav():
                c = _bn._client()
                spot = c.get_account().get("balances", [])
                for b in spot:
                    asset = b["asset"]
                    # LD-prefixed balances are Binance Earn wrapper tokens
                    # (LDSUI, LDUSDT, ...) — the SAME funds are reported by the
                    # Simple Earn positions call below; counting both would
                    # double-count (and they're unpriceable as symbols anyway).
                    if asset.startswith("LD") and len(asset) > 2:
                        continue
                    q = float(b["free"]) + float(b["locked"])
                    if q > 0:
                        _track("binance", asset, q, "spot")
                try:
                    fut = c.futures_account()
                    for a in fut.get("assets", []):
                        wb = float(a.get("walletBalance") or 0)
                        if wb > 0:
                            _track("binance", a["asset"], wb, "futures_usdm")
                except Exception:  # noqa: BLE001
                    pass
                try:
                    flex = c.get_simple_earn_flexible_product_position() or {}
                    for r in flex.get("rows", []):
                        q = float(r.get("totalAmount") or 0)
                        if q > 0:
                            _track("binance", r.get("asset"), q, "earn_flexible")
                except Exception:  # noqa: BLE001
                    pass
                return True

            per_venue["binance"] = {"status": "ok" if _safe(_bn_nav) is True else "error"}

        if _kr._credentials_present():
            def _kr_nav():
                bal = _kr._private("/0/private/Balance") or {}
                for asset, qty in bal.items():
                    try:
                        q = float(qty)
                    except (TypeError, ValueError):
                        continue
                    norm = asset
                    if norm.startswith("X") and len(norm) == 4:
                        norm = norm[1:]
                    if norm.startswith("Z") and len(norm) == 4:
                        norm = norm[1:]
                    if norm == "XBT":
                        norm = "BTC"
                    _track("kraken", norm, q, "spot_or_earn")
                return True

            per_venue["kraken"] = {"status": "ok" if _safe(_kr_nav) is True else "error"}

        if _krf._credentials_present():
            def _krf_nav():
                accounts = _krf._request("GET", "/api/v3/accounts").get("accounts") or {}
                flex = accounts.get("flex") or {}
                for ccy, info in (flex.get("currencies") or {}).items():
                    try:
                        q = float((info or {}).get("quantity") or 0)
                    except (TypeError, ValueError):
                        continue
                    if q > 0:
                        _track("kraken_futures", ccy.upper(), q, "futures_flex")
                return True

            per_venue["kraken_futures"] = {"status": "ok" if _safe(_krf_nav) is True else "error"}

        if _wb._credentials_present():
            def _wb_nav():
                main = _wb._private("/api/v4/main-account/balance") or {}
                for asset, info in main.items():
                    if not isinstance(info, dict):
                        continue
                    try:
                        q = float(info.get("main_balance") or 0)
                    except (TypeError, ValueError):
                        continue
                    _track("whitebit", asset, q, "main")
                return True

            per_venue["whitebit"] = {"status": "ok" if _safe(_wb_nav) is True else "error"}

        if _hl._credentials_present():
            def _hl_nav():
                addr = _hl._account_address()
                us = _hl._info().user_state(addr) or {}
                perp_value = float(((us.get("marginSummary") or {}).get("accountValue") or 0))
                if perp_value > 0:
                    _track("hyperliquid", "USDC", perp_value, "perp_collateral")
                try:
                    spot = _hl._info().spot_user_state(addr) or {}
                    for b in spot.get("balances", []):
                        try:
                            q = float(b.get("total") or b.get("hold") or 0)
                        except (TypeError, ValueError):
                            continue
                        if q > 0:
                            _track("hyperliquid", b.get("coin") or "", q, "spot")
                except Exception:  # noqa: BLE001
                    pass
                try:
                    eq = _hl._info().user_vault_equities(addr) or []
                    for v in eq:
                        try:
                            q = float(v.get("equity") or 0)
                        except (TypeError, ValueError):
                            continue
                        if q > 0:
                            label = (
                                "hlp_vault"
                                if (v.get("vaultAddress") or "").lower() == _hl.HLP_VAULT_ADDRESS
                                else "user_vault"
                            )
                            _track("hyperliquid", "USDC", q, label)
                except Exception:  # noqa: BLE001
                    pass
                return True

            per_venue["hyperliquid"] = {"status": "ok" if _safe(_hl_nav) is True else "error"}

        idle.sort(key=lambda r: r["usd"], reverse=True)
        return {
            "total_usd": round(total_usd, 2),
            "venues_scanned": list(per_venue.keys()),
            "idle_stables": idle,
            "idle_threshold_usd": idle_threshold_usd,
            "unpriced": unpriced,
            "venue_status": per_venue,
        }

    # ----- 5. Funding-carry screener ------------------------------------

    @mcp.tool()
    def funding_carry_screener(top_n: int = 10, min_oi_usd: float = 5_000_000) -> dict[str, Any]:
        """Rank Hyperliquid perps as funding-carry basket candidates.

        Score = annualized_funding × min(1, open_interest_usd / $50M). Filters
        out perps below `min_oi_usd` open interest to avoid illiquid bait.

        Pair with `compare_perp_funding(coin)` per top candidate before adding
        to basket.
        """
        if not _hl._credentials_present():
            return {"error": "Hyperliquid not configured; can't screen carry candidates."}
        try:
            meta, ctxs = _hl._info().meta_and_asset_ctxs()
        except Exception as e:  # noqa: BLE001
            return {"error": f"HL info call failed: {e}"}

        rows: list[dict[str, Any]] = []
        for asset, ctx in zip(meta.get("universe", []), ctxs):
            try:
                hourly = float(ctx.get("funding") or 0)
                mark = float(ctx.get("markPx") or 0)
                oi_native = float(ctx.get("openInterest") or 0)
                day_vlm = float(ctx.get("dayNtlVlm") or 0)
            except (TypeError, ValueError):
                continue
            oi_usd = oi_native * mark
            if oi_usd < min_oi_usd:
                continue
            apr = hourly * 24 * 365
            score = abs(apr) * min(1.0, oi_usd / 50_000_000)
            rows.append({
                "coin": asset.get("name"),
                "apr": apr,
                "hourly": hourly,
                "side": "short" if apr > 0 else "long",
                "open_interest_usd": oi_usd,
                "day_ntl_vlm": day_vlm,
                "max_leverage": asset.get("maxLeverage"),
                "score": score,
            })
        rows.sort(key=lambda r: r["score"], reverse=True)
        return {
            "top": rows[:top_n],
            "filter_min_oi_usd": min_oi_usd,
            "total_screened": len(rows),
            "next_step": (
                "For each top candidate, call compare_perp_funding(coin) to "
                "size the cross-venue spread; then verify spot/short liquidity "
                "on Kraken or Binance before adding to the basket."
            ),
        }

    # ----- 6. Promotions sweep (Binance only for now) -------------------

    @mcp.tool()
    def find_best_promotions(
        keywords: list[str] | None = None, limit: int = 10
    ) -> dict[str, Any]:
        """Sweep Binance announcement feed for free-money campaigns: airdrops,
        Launchpool, Megadrop, trading competitions.

        keywords: case-insensitive title substrings (e.g. ["airdrop",
        "launchpool", "megadrop", "competition"]).
        """
        kw_lower = [k.lower() for k in (keywords or [])]
        results: dict[str, Any] = {}

        if _bn._credentials_present():
            def _bn_promo():
                import httpx
                cats = _bn._ANNOUNCEMENT_CATALOGS
                items: list[dict[str, Any]] = []
                for name, cid in cats.items():
                    try:
                        r = httpx.get(
                            "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query",
                            params={"type": 1, "catalogId": cid, "pageNo": 1, "pageSize": limit},
                            headers={"User-Agent": "Mozilla/5.0 trading-mcp"},
                            timeout=20,
                        )
                        r.raise_for_status()
                        data = (r.json() or {}).get("data") or {}
                        arts = data.get("articles") or (
                            (data.get("catalogs") or [{}])[0].get("articles") or []
                        )
                        for a in arts:
                            title = a.get("title") or ""
                            if kw_lower and not any(k in title.lower() for k in kw_lower):
                                continue
                            code = a.get("code")
                            items.append({
                                "venue": "binance",
                                "category": name,
                                "title": title,
                                "date": a.get("releaseDate"),
                                "url": (
                                    f"https://www.binance.com/en/support/announcement/{code}"
                                    if code else None
                                ),
                            })
                    except Exception as e:  # noqa: BLE001
                        items.append({"venue": "binance", "category": name, "error": str(e)})
                return items

            results["binance"] = _safe(_bn_promo)

        flat: list[dict[str, Any]] = []
        for venue, val in results.items():
            if isinstance(val, list):
                flat.extend(v for v in val if "error" not in v)
        return {
            "matches": flat,
            "keywords": kw_lower,
            "per_venue_raw_counts": {
                k: (len(v) if isinstance(v, list) else 0) for k, v in results.items()
            },
        }

    # ----- 7. Dust scanner ----------------------------------------------

    @mcp.tool()
    def aggregator_find_all_dust(
        threshold_usd: float = 5.0,
    ) -> dict[str, Any]:
        """Scan every configured venue for sub-threshold balances and tag each
        row with how to clean it up.

        Tags:
        - ``binance_dust_eligible`` — pass into ``binance_transfer_dust``
        - ``binance_margin_dust_eligible`` — pass into ``binance_transfer_margin_dust``
        - ``binance_convert_only`` — Binance asset that isn't dust-eligible
          (e.g. BNB itself, stablecoins); use ``binance_convert_quote`` →
          ``binance_convert_accept``
        - ``hyperliquid_bridge`` — HL spot USDC dust; ``hyperliquid_bridge_usdc``
        - ``hyperliquid_spot_trade`` — non-USDC HL spot dust; trade to USDC
          via the spot orderbook
        - ``manual_trade`` — Kraken/WhiteBIT, no dust API; spot-sell on the
          venue
        - ``web_only`` — no programmatic path; user must use the web UI

        Returns rows grouped by tag, each with USD recovery estimate.
        """
        rows: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []

        def _add(venue: str, asset: str, qty: float, usd: float | None,
                 location: str, tag: str, **extra: Any) -> None:
            rows.append({
                "venue": venue,
                "asset": asset,
                "qty": qty,
                "usd": usd,
                "location": location,
                "tag": tag,
                **extra,
            })

        # --- Binance Spot + Cross-Margin ---
        if _bn._credentials_present():
            def _bn_scan() -> None:
                c = _bn._client()

                # 1. Pull dust-eligible asset lists once.
                spot_eligible: set[str] = set()
                margin_eligible: set[str] = set()
                try:
                    details = (c.get_dust_assets() or {}).get("details") or []
                    spot_eligible = {(d.get("asset") or "").upper() for d in details}
                except Exception as e:  # noqa: BLE001
                    errors.append({"step": "binance_get_dust_assets", "error": str(e)})
                try:
                    details = (c.get_margin_dust_assets() or {}).get("details") or []
                    margin_eligible = {(d.get("asset") or "").upper() for d in details}
                except Exception as e:  # noqa: BLE001
                    # Margin dust endpoint sometimes 403s if no margin account;
                    # don't promote to top-level error.
                    pass

                # 2. Spot balances.
                spot = c.get_account().get("balances", [])
                for b in spot:
                    asset = (b.get("asset") or "").upper()
                    qty = float(b.get("free", 0)) + float(b.get("locked", 0))
                    if qty <= 0:
                        continue
                    usd = _usd_value(asset, qty)
                    if usd is None or usd >= threshold_usd:
                        continue
                    tag = (
                        "binance_dust_eligible" if asset in spot_eligible
                        else "binance_convert_only"
                    )
                    _add("binance", asset, qty, usd, "spot", tag)

                # 3. Cross-margin balances.
                try:
                    m = c.get_margin_account()
                except Exception:  # noqa: BLE001
                    return
                for a in m.get("userAssets", []):
                    asset = (a.get("asset") or "").upper()
                    try:
                        qty = float(a.get("netAsset", 0))
                    except (TypeError, ValueError):
                        continue
                    if qty <= 0:
                        continue
                    usd = _usd_value(asset, qty)
                    if usd is None or usd >= threshold_usd:
                        continue
                    tag = (
                        "binance_margin_dust_eligible"
                        if asset in margin_eligible
                        else "binance_convert_only"
                    )
                    _add("binance", asset, qty, usd, "cross_margin", tag)

            try:
                _bn_scan()
            except Exception as e:  # noqa: BLE001
                errors.append({"venue": "binance", "error": str(e)})

        # --- Kraken ---
        if _kr._credentials_present():
            def _kr_scan() -> None:
                bal = _kr._private("/0/private/Balance") or {}
                for asset, qty in bal.items():
                    try:
                        q = float(qty)
                    except (TypeError, ValueError):
                        continue
                    if q <= 0:
                        continue
                    norm = asset
                    if norm.startswith(("X", "Z")) and len(norm) == 4:
                        norm = norm[1:]
                    if norm == "XBT":
                        norm = "BTC"
                    usd = _usd_value(norm, q)
                    if usd is None or usd >= threshold_usd:
                        continue
                    _add(
                        "kraken", norm, q, usd, "spot", "manual_trade",
                        hint=f"Place a market SELL on {norm}/USD or {norm}/USDT.",
                    )

            try:
                _kr_scan()
            except Exception as e:  # noqa: BLE001
                errors.append({"venue": "kraken", "error": str(e)})

        # --- WhiteBIT ---
        if _wb._credentials_present():
            def _wb_scan() -> None:
                main = _wb._private("/api/v4/main-account/balance") or {}
                for asset, info in main.items():
                    if not isinstance(info, dict):
                        continue
                    try:
                        q = float(info.get("main_balance") or 0)
                    except (TypeError, ValueError):
                        continue
                    if q <= 0:
                        continue
                    usd = _usd_value(asset, q)
                    if usd is None or usd >= threshold_usd:
                        continue
                    _add(
                        "whitebit", asset, q, usd, "main", "manual_trade",
                        hint=f"Spot-sell on {asset}/USDT pair, or use web 'Convert' button.",
                    )

            try:
                _wb_scan()
            except Exception as e:  # noqa: BLE001
                errors.append({"venue": "whitebit", "error": str(e)})

        # --- Hyperliquid spot ---
        if _hl._credentials_present():
            def _hl_scan() -> None:
                addr = _hl._account_address()
                spot = _hl._info().spot_user_state(addr) or {}
                for b in spot.get("balances", []):
                    asset = (b.get("coin") or "").upper()
                    try:
                        q = float(b.get("total") or b.get("hold") or 0)
                    except (TypeError, ValueError):
                        continue
                    if q <= 0:
                        continue
                    usd = _usd_value(asset, q)
                    if usd is None or usd >= threshold_usd:
                        continue
                    if asset == "USDC":
                        _add(
                            "hyperliquid", asset, q, usd, "spot",
                            "hyperliquid_bridge",
                            hint="hyperliquid_bridge_usdc(amount=…, to_perp=True) "
                                 "to absorb into perp collateral.",
                        )
                    else:
                        _add(
                            "hyperliquid", asset, q, usd, "spot",
                            "hyperliquid_spot_trade",
                            hint=f"hyperliquid_place_perp_order is perp-only; "
                                 f"sell {asset} via HL spot orderbook (UI).",
                        )

            try:
                _hl_scan()
            except Exception as e:  # noqa: BLE001
                errors.append({"venue": "hyperliquid", "error": str(e)})

        # Group by tag, total USD recoverable.
        by_tag: dict[str, dict[str, Any]] = {}
        for r in rows:
            t = r["tag"]
            slot = by_tag.setdefault(t, {"rows": [], "total_usd": 0.0, "count": 0})
            slot["rows"].append(r)
            slot["count"] += 1
            slot["total_usd"] = round(
                slot["total_usd"] + (r.get("usd") or 0), 4
            )

        return {
            "threshold_usd": threshold_usd,
            "total_rows": len(rows),
            "total_usd_recoverable": round(
                sum(r.get("usd") or 0 for r in rows), 4
            ),
            "by_tag": by_tag,
            "errors": errors,
        }

    # ----- 8. Dust cleanup plan -----------------------------------------

    @mcp.tool()
    def aggregator_dust_cleanup_plan(
        threshold_usd: float = 5.0, confirm: bool = False
    ) -> dict[str, Any]:
        """Compose an ordered cleanup plan from ``aggregator_find_all_dust``
        and (with ``confirm=True``) execute the Binance steps.

        Execution scope:
        - Binance spot dust → BNB (one batched ``transfer_dust`` call)
        - Binance cross-margin dust → BNB (one batched ``transfer_margin_dust`` call)
        - Hyperliquid USDC spot dust → perp (one ``usd_class_transfer``)

        Non-executable steps (Kraken, WhiteBIT, Hyperliquid spot non-USDC,
        Binance "convert_only" assets) are returned as TODO actions with the
        recommended tool / UI path. Always re-run with ``confirm=True`` only
        after reviewing the dry-run output.
        """
        scan = aggregator_find_all_dust(threshold_usd)
        plan: list[dict[str, Any]] = []
        executed: list[dict[str, Any]] = []

        by_tag = scan.get("by_tag") or {}

        # 1. Binance spot dust -> BNB.
        if "binance_dust_eligible" in by_tag:
            assets = [r["asset"] for r in by_tag["binance_dust_eligible"]["rows"]]
            est_usd = by_tag["binance_dust_eligible"]["total_usd"]
            step = {
                "step": "binance_transfer_dust",
                "venue": "binance",
                "location": "spot",
                "assets": assets,
                "estimated_usd_recovered": est_usd,
                "tool": "binance_transfer_dust",
            }
            plan.append(step)
            if confirm and assets:
                try:
                    asset_param = ",".join(assets)
                    res = _bn._client().transfer_dust(asset=asset_param)
                    executed.append({**step, "result": res})
                except Exception as e:  # noqa: BLE001
                    executed.append({**step, "error": str(e)})

        # 2. Binance cross-margin dust -> BNB.
        if "binance_margin_dust_eligible" in by_tag:
            assets = [
                r["asset"]
                for r in by_tag["binance_margin_dust_eligible"]["rows"]
            ]
            est_usd = by_tag["binance_margin_dust_eligible"]["total_usd"]
            step = {
                "step": "binance_transfer_margin_dust",
                "venue": "binance",
                "location": "cross_margin",
                "assets": assets,
                "estimated_usd_recovered": est_usd,
                "tool": "binance_transfer_margin_dust",
            }
            plan.append(step)
            if confirm and assets:
                try:
                    asset_param = ",".join(assets)
                    res = _bn._client().transfer_margin_dust(asset=asset_param)
                    executed.append({**step, "result": res})
                except Exception as e:  # noqa: BLE001
                    executed.append({**step, "error": str(e)})

        # 3. Binance convert-only assets (BNB / stables / non-eligible dust).
        if "binance_convert_only" in by_tag:
            for r in by_tag["binance_convert_only"]["rows"]:
                plan.append({
                    "step": "binance_convert_quote_then_accept",
                    "venue": "binance",
                    "asset": r["asset"],
                    "qty": r["qty"],
                    "usd": r["usd"],
                    "tool": "binance_convert_quote → binance_convert_accept",
                    "todo": (
                        f"binance_convert_quote(from_asset='{r['asset']}', "
                        f"to_asset='USDT', from_amount={r['qty']}) "
                        "then binance_convert_accept(quote_id=…)"
                    ),
                })

        # 4. Hyperliquid USDC spot dust -> perp.
        if "hyperliquid_bridge" in by_tag:
            usdc_qty = sum(r["qty"] for r in by_tag["hyperliquid_bridge"]["rows"])
            est_usd = by_tag["hyperliquid_bridge"]["total_usd"]
            step = {
                "step": "hyperliquid_bridge_usdc",
                "venue": "hyperliquid",
                "location": "spot",
                "amount": usdc_qty,
                "to_perp": True,
                "estimated_usd_recovered": est_usd,
                "tool": "hyperliquid_bridge_usdc",
            }
            plan.append(step)
            if confirm and usdc_qty > 0:
                try:
                    res = _hl._exchange().usd_class_transfer(usdc_qty, to_perp=True)
                    executed.append({**step, "result": res})
                except Exception as e:  # noqa: BLE001
                    executed.append({**step, "error": str(e)})

        # 5. Hyperliquid non-USDC spot dust.
        if "hyperliquid_spot_trade" in by_tag:
            for r in by_tag["hyperliquid_spot_trade"]["rows"]:
                plan.append({
                    "step": "hyperliquid_spot_trade",
                    "venue": "hyperliquid",
                    "asset": r["asset"],
                    "qty": r["qty"],
                    "usd": r["usd"],
                    "tool": "manual (HL spot UI)",
                    "todo": (
                        f"HL spot {r['asset']} balance is too small for API perp "
                        f"trading; sell via the spot orderbook on the web UI."
                    ),
                })

        # 6. Kraken / WhiteBIT — manual trade.
        for tag in ("manual_trade",):
            if tag not in by_tag:
                continue
            for r in by_tag[tag]["rows"]:
                plan.append({
                    "step": f"{r['venue']}_manual_trade",
                    "venue": r["venue"],
                    "asset": r["asset"],
                    "qty": r["qty"],
                    "usd": r["usd"],
                    "tool": "manual (venue UI or place_*_order)",
                    "todo": r.get("hint")
                            or f"Spot-sell {r['asset']} on {r['venue']}.",
                })

        return {
            "threshold_usd": threshold_usd,
            "dry_run": not confirm,
            "total_usd_recoverable": scan.get("total_usd_recoverable"),
            "plan": plan,
            "executed": executed if confirm else [],
            "scan_errors": scan.get("errors") or [],
        }

    # ----- 9. Daily snapshot --------------------------------------------

    @mcp.tool()
    def aggregator_get_daily_snapshot(
        idle_threshold_usd: float = 500.0,
        dust_threshold_usd: float = 5.0,
        promo_keywords: list[str] | None = None,
    ) -> dict[str, Any]:
        """One-call composite of the trading state — NAV, positions, open
        orders, dust, idle stables, best yield candidates for each idle
        asset, and promotions filtered to held coins. Designed for the
        morning "where do I stand?" prompt.

        Internally fans out to ``get_total_nav``, ``aggregator_find_all_dust``,
        ``find_best_yield_anywhere``, ``binance_list_promotions`` and the
        per-venue position/order endpoints. Each sub-call is ``_safe()``
        wrapped — one venue's outage degrades that section, never the
        whole snapshot.
        """
        nav = _safe(lambda: get_total_nav(idle_threshold_usd))
        dust = _safe(lambda: aggregator_find_all_dust(dust_threshold_usd))

        # Held coins (qty > 0 anywhere) — used for promotion relevance + yield recs.
        held: set[str] = set()
        idle_assets: list[dict[str, Any]] = []
        if isinstance(nav, dict):
            for entry in (nav.get("idle_stables") or []):
                held.add((entry.get("asset") or "").upper())
                idle_assets.append({
                    "asset": entry.get("asset"),
                    "qty": entry.get("qty"),
                    "usd": entry.get("usd"),
                    "venue": entry.get("venue"),
                })
            for entry in (nav.get("unpriced") or []):
                held.add((entry.get("asset") or "").upper())

        # Positions per venue.
        positions: dict[str, Any] = {}
        if _hl._credentials_present():
            def _hl_pos():
                us = _hl._info().user_state(_hl._account_address()) or {}
                return [
                    p for p in (us.get("assetPositions") or [])
                    if float(((p.get("position") or {}).get("szi") or 0)) != 0
                ]
            positions["hyperliquid_perp"] = _safe(_hl_pos)
        if _bn._credentials_present():
            def _bn_pos():
                c = _bn._client()
                fut = c.futures_account()
                usdm = [
                    p for p in (fut.get("positions") or [])
                    if float(p.get("positionAmt", 0)) != 0
                ]
                coinm = []
                try:
                    cfut = c.futures_coin_account()
                    coinm = [
                        p for p in (cfut.get("positions") or [])
                        if float(p.get("positionAmt", 0)) != 0
                    ]
                except Exception:  # noqa: BLE001
                    pass
                return {"usdm": usdm, "coinm": coinm}
            positions["binance_futures"] = _safe(_bn_pos)

        # Open orders per venue.
        open_orders: dict[str, Any] = {}
        if _bn._credentials_present():
            def _bn_oo():
                c = _bn._client()
                out: dict[str, Any] = {"spot": c.get_open_orders()}
                try:
                    out["futures_usdm"] = c.futures_get_open_orders()
                except Exception:  # noqa: BLE001
                    pass
                return out
            open_orders["binance"] = _safe(_bn_oo)
        if _hl._credentials_present():
            open_orders["hyperliquid"] = _safe(
                lambda: _hl._info().open_orders(_hl._account_address())
            )

        # Yield recommendations for each idle stable.
        yield_recs: dict[str, Any] = {}
        for row in idle_assets[:6]:  # cap to keep call cheap
            asset = (row.get("asset") or "").upper()
            if not asset:
                continue
            yield_recs[asset] = _safe(
                lambda a=asset: find_best_yield_anywhere(asset=a, top_n=3)
            )

        # Held-asset matched promotions (cheap heuristic; Phase D adds tagging).
        kws = promo_keywords or [
            "airdrop", "launchpool", "megadrop", "hodl", "competition", "reward",
        ]
        promos_all = _safe(lambda: find_best_promotions(keywords=kws, limit=20))
        relevant_promos: list[dict[str, Any]] = []
        if isinstance(promos_all, dict):
            for p in promos_all.get("matches") or []:
                title_up = (p.get("title") or "").upper()
                hit = next((h for h in held if h and h in title_up), None)
                if hit:
                    relevant_promos.append({**p, "matched_asset": hit})
            # Always include a few "general" Launchpool/airdrop entries even
            # if no held asset matches — useful to surface free-money plays.
            general = [
                p for p in (promos_all.get("matches") or [])
                if p not in relevant_promos
            ][:5]
        else:
            general = []

        return {
            "nav": nav,
            "positions": positions,
            "open_orders": open_orders,
            "dust": dust,
            "idle_assets": idle_assets,
            "yield_recs_for_idle": yield_recs,
            "promotions": {
                "matched_held_assets": relevant_promos,
                "general_recent": general,
                "keywords": kws,
            },
        }

    # ----- 10. Smart promotions filter ----------------------------------

    @mcp.tool()
    def aggregator_relevant_promotions(
        min_value_usd: float = 10.0, limit_per_category: int = 40
    ) -> dict[str, Any]:
        """Fetch recent Binance announcements and tag/rank by relevance to
        coins you actually hold.

        For each promotion title, applies regex tags
        (``airdrop`` / ``launchpool`` / ``megadrop`` / ``megavault`` /
        ``hold_to_earn`` / ``trade_to_earn`` / ``earn_reward`` /
        ``competition``), extracts uppercase asset symbols from the title,
        and cross-references against your held assets (qty × price ≥
        ``min_value_usd``).

        Returns three buckets:
        - ``held_match`` — title references a coin you hold above threshold
        - ``general_free_money`` — Launchpool / Megadrop / Megavault / generic
          airdrops where holding a stable or BNB is enough to participate
        - ``other`` — tagged but no held-asset match
        """
        import re

        # 1. Build held set with USD valuations.
        held_usd: dict[str, float] = {}
        if _bn._credentials_present():
            try:
                c = _bn._client()
                for b in c.get_account().get("balances", []):
                    asset = (b.get("asset") or "").upper()
                    qty = float(b.get("free", 0)) + float(b.get("locked", 0))
                    if qty <= 0:
                        continue
                    usd = _usd_value(asset, qty) or 0.0
                    held_usd[asset] = held_usd.get(asset, 0.0) + usd
            except Exception:  # noqa: BLE001
                pass
            try:
                pos = _bn._client().get_simple_earn_flexible_product_position() or {}
                for r in pos.get("rows", []):
                    asset = (r.get("asset") or "").upper()
                    qty = float(r.get("totalAmount") or 0)
                    if qty <= 0:
                        continue
                    usd = _usd_value(asset, qty) or 0.0
                    held_usd[asset] = held_usd.get(asset, 0.0) + usd
            except Exception:  # noqa: BLE001
                pass
        if _kr._credentials_present():
            try:
                bal = _kr._private("/0/private/Balance") or {}
                for asset, qty in bal.items():
                    try:
                        q = float(qty)
                    except (TypeError, ValueError):
                        continue
                    if q <= 0:
                        continue
                    norm = asset
                    if norm.startswith(("X", "Z")) and len(norm) == 4:
                        norm = norm[1:]
                    if norm == "XBT":
                        norm = "BTC"
                    usd = _usd_value(norm, q) or 0.0
                    held_usd[norm] = held_usd.get(norm, 0.0) + usd
            except Exception:  # noqa: BLE001
                pass
        if _wb._credentials_present():
            try:
                main = _wb._private("/api/v4/main-account/balance") or {}
                for asset, info in main.items():
                    if not isinstance(info, dict):
                        continue
                    try:
                        q = float(info.get("main_balance") or 0)
                    except (TypeError, ValueError):
                        continue
                    if q <= 0:
                        continue
                    usd = _usd_value(asset, q) or 0.0
                    held_usd[asset.upper()] = held_usd.get(asset.upper(), 0.0) + usd
            except Exception:  # noqa: BLE001
                pass
        if _hl._credentials_present():
            try:
                addr = _hl._account_address()
                us = _hl._info().user_state(addr) or {}
                perp_val = float(((us.get("marginSummary") or {}).get("accountValue") or 0))
                if perp_val > 0:
                    held_usd["USDC"] = held_usd.get("USDC", 0.0) + perp_val
            except Exception:  # noqa: BLE001
                pass

        qualifying_held = {a for a, v in held_usd.items() if v >= min_value_usd}

        # 2. Pull Binance announcements (activities + new-listings).
        items: list[dict[str, Any]] = []
        if _bn._credentials_present():
            for cat_name, cat_id in (
                ("activities", 93), ("new-listings", 48),
            ):
                try:
                    r = httpx.get(
                        "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query",
                        params={"type": 1, "catalogId": cat_id, "pageNo": 1,
                                "pageSize": limit_per_category},
                        headers={"User-Agent": "Mozilla/5.0 trading-mcp"},
                        timeout=20,
                    )
                    r.raise_for_status()
                    data = (r.json() or {}).get("data") or {}
                    arts = data.get("articles") or (
                        (data.get("catalogs") or [{}])[0].get("articles") or []
                    )
                    for a in arts:
                        items.append({
                            "venue": "binance",
                            "category": cat_name,
                            "title": a.get("title") or "",
                            "date": a.get("releaseDate"),
                            "code": a.get("code"),
                        })
                except Exception:  # noqa: BLE001
                    pass

        # 3. Tag titles + extract asset symbols.
        tag_patterns: list[tuple[str, re.Pattern[str]]] = [
            ("airdrop", re.compile(r"\bair\s*drop\b", re.I)),
            ("launchpool", re.compile(r"\blaunch\s*pool\b", re.I)),
            ("megadrop", re.compile(r"\bmega\s*drop\b", re.I)),
            ("megavault", re.compile(r"\bmega\s*vault\b", re.I)),
            ("hold_to_earn", re.compile(r"\b(hodl|hold\s+to\s+earn|holders?)\b", re.I)),
            ("trade_to_earn", re.compile(r"\b(trade\s+to\s+earn|trading\s+competition|compete)\b", re.I)),
            ("competition", re.compile(r"\bcompetition\b", re.I)),
            ("earn_reward", re.compile(r"\b(rewards?|earn)\b", re.I)),
            ("listing", re.compile(r"\b(will\s+list|new\s+listing)\b", re.I)),
        ]
        # Asset symbols look like 2-6 uppercase chars (BNB, BTC, FDUSD…).
        # Constrain to whole tokens to avoid false hits inside words.
        sym_re = re.compile(r"\b([A-Z0-9]{2,6})\b")
        common_words = {
            "USD", "GMT", "UTC", "AM", "PM", "API", "NFT", "AMA", "VIP",
            "TBA", "FAQ", "IDO", "ICO", "WEB", "EU", "US", "UK", "DEX",
            "CEX", "DEFI", "TVL", "AOA", "FOR", "AND", "THE", "NEW",
        }

        held_match: list[dict[str, Any]] = []
        general_free_money: list[dict[str, Any]] = []
        other: list[dict[str, Any]] = []

        for it in items:
            title = it["title"] or ""
            tags = [name for name, pat in tag_patterns if pat.search(title)]
            if not tags:
                continue
            symbols = {
                s for s in sym_re.findall(title)
                if s not in common_words and 2 <= len(s) <= 6
            }
            held_hits = symbols & qualifying_held
            code = it.get("code")
            row = {
                "title": title,
                "category": it.get("category"),
                "date": it.get("date"),
                "url": (
                    f"https://www.binance.com/en/support/announcement/{code}"
                    if code else None
                ),
                "tags": tags,
                "asset_symbols_in_title": sorted(symbols),
                "held_match_assets": sorted(held_hits),
            }
            if held_hits:
                held_match.append(row)
            elif any(
                t in tags for t in
                ("launchpool", "megadrop", "megavault", "airdrop")
            ):
                general_free_money.append(row)
            else:
                other.append(row)

        return {
            "min_value_usd": min_value_usd,
            "qualifying_held_assets": sorted(qualifying_held),
            "held_usd_summary": {
                a: round(v, 2) for a, v in
                sorted(held_usd.items(), key=lambda kv: -kv[1])[:30]
            },
            "held_match": held_match,
            "general_free_money": general_free_money,
            "other": other,
            "total_tagged": len(held_match) + len(general_free_money) + len(other),
            "scanned_articles": len(items),
        }

    # ----- 11–13. Buy/sell helper ---------------------------------------

    # Default taker fees (decimal). Override via env if a VIP tier applies.
    _DEFAULT_TAKER_BPS = {
        "binance": 10.0,    # 0.10%
        "kraken": 26.0,     # 0.26%
        "whitebit": 10.0,   # 0.10%
        "hyperliquid": 3.5, # 0.035%
    }

    def _kraken_pair(coin: str) -> str:
        """Best-guess Kraken USDT pair code (BTC → XBTUSDT)."""
        c = coin.upper()
        if c == "BTC":
            c = "XBT"
        return f"{c}USDT"

    def _walk_book(side_levels: list[tuple[float, float]],
                   target_usd: float) -> dict[str, Any] | None:
        """Walk one side of an orderbook, accumulating until USD notional
        crosses target. Returns vwap + filled_usd + filled_qty + worst_price,
        or None if the book can't fill the order."""
        cum_qty = 0.0
        cum_usd = 0.0
        last_px = 0.0
        for idx, (px, qty) in enumerate(side_levels):
            try:
                px = float(px); qty = float(qty)
            except (TypeError, ValueError):
                continue
            level_usd = px * qty
            need = target_usd - cum_usd
            if level_usd >= need:
                take_qty = need / px
                cum_qty += take_qty
                cum_usd += take_qty * px
                last_px = px
                return {
                    "vwap": cum_usd / cum_qty if cum_qty else None,
                    "filled_usd": cum_usd,
                    "filled_qty": cum_qty,
                    "worst_price": last_px,
                    "levels_consumed": idx + 1,
                }
            cum_qty += qty
            cum_usd += level_usd
            last_px = px
        if cum_qty == 0:
            return None
        return {
            "vwap": cum_usd / cum_qty,
            "filled_usd": cum_usd,
            "filled_qty": cum_qty,
            "worst_price": last_px,
            "partial": True,
        }

    def _binance_book(coin: str) -> dict[str, Any] | None:
        if not _bn._credentials_present():
            return None
        try:
            ob = _bn._client().get_order_book(
                symbol=f"{coin.upper()}USDT", limit=50,
            )
            return {
                "bids": [(float(p), float(q)) for p, q in ob.get("bids") or []],
                "asks": [(float(p), float(q)) for p, q in ob.get("asks") or []],
            }
        except Exception:  # noqa: BLE001
            return None

    def _kraken_book(coin: str) -> dict[str, Any] | None:
        try:
            pair = _kraken_pair(coin)
            r = httpx.get(
                f"https://api.kraken.com/0/public/Depth",
                params={"pair": pair, "count": 50}, timeout=20,
            )
            r.raise_for_status()
            res = (r.json() or {}).get("result") or {}
            if not res:
                return None
            book = next(iter(res.values()))
            return {
                "bids": [(float(p), float(q)) for p, q, *_ in book.get("bids") or []],
                "asks": [(float(p), float(q)) for p, q, *_ in book.get("asks") or []],
            }
        except Exception:  # noqa: BLE001
            return None

    def _whitebit_book(coin: str) -> dict[str, Any] | None:
        try:
            r = httpx.get(
                f"https://whitebit.com/api/v4/public/orderbook/{coin.upper()}_USDT",
                params={"depth": 50}, timeout=20,
            )
            r.raise_for_status()
            ob = r.json() or {}
            return {
                "bids": [(float(p), float(q)) for p, q in ob.get("bids") or []],
                "asks": [(float(p), float(q)) for p, q in ob.get("asks") or []],
            }
        except Exception:  # noqa: BLE001
            return None

    def _hl_spot_book(coin: str) -> dict[str, Any] | None:
        if not _hl._credentials_present():
            return None
        try:
            # HL spot pairs are named e.g. "@<index>" or "PURR/USDC". The SDK
            # accepts the coin name and resolves internally; we just try the
            # raw coin first (works for spot tokens).
            l2 = _hl._info().l2_snapshot(coin.upper())
            levels = l2.get("levels") or []
            if len(levels) < 2:
                return None
            bids = [(float(lv["px"]), float(lv["sz"])) for lv in levels[0]]
            asks = [(float(lv["px"]), float(lv["sz"])) for lv in levels[1]]
            return {"bids": bids, "asks": asks}
        except Exception:  # noqa: BLE001
            return None

    @mcp.tool()
    def aggregator_compare_buy_sell_prices(
        coin: str, side: str, amount_usd: float,
    ) -> dict[str, Any]:
        """Compare effective fill price for buying or selling ``amount_usd``
        of a coin against COIN/USDT spot orderbooks on every configured
        venue, including taker fee.

        Returns rows sorted from BEST to WORST for the operator (lowest
        effective price for BUY, highest for SELL). Each row carries
        ``vwap``, ``fee_bps``, ``effective_price`` (vwap × (1 ± fee)),
        ``filled_usd`` (whether the venue can absorb the size), and
        ``slippage_bps`` vs the best mid across venues.
        """
        is_buy = side.upper() == "BUY"
        venues = [
            ("binance", _binance_book(coin)),
            ("kraken", _kraken_book(coin)),
            ("whitebit", _whitebit_book(coin)),
            ("hyperliquid", _hl_spot_book(coin)),
        ]
        # Mid across whichever venues responded — used to compute slippage_bps.
        mids: list[float] = []
        for _, book in venues:
            if not book or not book["bids"] or not book["asks"]:
                continue
            mids.append((book["bids"][0][0] + book["asks"][0][0]) / 2)
        ref_mid = sum(mids) / len(mids) if mids else None

        rows: list[dict[str, Any]] = []
        for venue, book in venues:
            if not book:
                rows.append({"venue": venue, "skipped": True,
                             "reason": "no book / not configured"})
                continue
            side_levels = book["asks"] if is_buy else book["bids"]
            walked = _walk_book(side_levels, amount_usd)
            if not walked:
                rows.append({"venue": venue, "skipped": True,
                             "reason": "empty book"})
                continue
            fee_bps = _DEFAULT_TAKER_BPS.get(venue, 10.0)
            vwap = walked["vwap"]
            sign = 1 if is_buy else -1
            eff = vwap * (1 + sign * fee_bps / 10_000)
            slip_bps = None
            if ref_mid:
                slip_bps = (vwap - ref_mid) / ref_mid * 10_000 * sign
            rows.append({
                "venue": venue,
                "vwap": vwap,
                "effective_price": eff,
                "fee_bps": fee_bps,
                "filled_usd": walked["filled_usd"],
                "filled_qty": walked["filled_qty"],
                "worst_price": walked["worst_price"],
                "partial_fill": walked.get("partial", False),
                "slippage_bps_vs_xvenue_mid": slip_bps,
            })

        fillable = [r for r in rows if "effective_price" in r]
        fillable.sort(
            key=lambda r: r["effective_price"], reverse=not is_buy,
        )
        return {
            "coin": coin.upper(),
            "side": side.upper(),
            "amount_usd": amount_usd,
            "cross_venue_mid": ref_mid,
            "ranked": fillable,
            "skipped": [r for r in rows if "skipped" in r],
            "best_venue": fillable[0]["venue"] if fillable else None,
        }

    @mcp.tool()
    def aggregator_get_market_summary(coin: str) -> dict[str, Any]:
        """One-call market overview for a coin: spot price + 24h change +
        cross-venue funding APR + best Earn APR + book depth at $1k / $10k.
        Pairs with ``aggregator_compare_buy_sell_prices`` for execution sizing.
        """
        coin_u = coin.upper()
        out: dict[str, Any] = {"coin": coin_u}

        # Price + 24h via Binance ticker.
        if _bn._credentials_present():
            def _bn_tk():
                t = _bn._client().get_ticker(symbol=f"{coin_u}USDT")
                return {
                    "last": float(t.get("lastPrice", 0)),
                    "change_24h_pct": float(t.get("priceChangePercent", 0)),
                    "high_24h": float(t.get("highPrice", 0)),
                    "low_24h": float(t.get("lowPrice", 0)),
                    "vol_24h_usd": float(t.get("quoteVolume", 0)),
                }
            out["binance_ticker"] = _safe(_bn_tk)

        # Cross-venue funding (reuse compare_perp_funding inner logic).
        out["funding"] = _safe(lambda: compare_perp_funding(coin_u))

        # Best Earn APR.
        out["best_yield"] = _safe(
            lambda: find_best_yield_anywhere(asset=coin_u, top_n=5)
        )

        # Depth probes — what's effective price for $1k / $10k buy vs sell on Binance?
        def _depth_probe():
            book = _binance_book(coin_u)
            if not book:
                return None
            res: dict[str, Any] = {}
            for usd in (1000.0, 10000.0):
                bid_walk = _walk_book(book["bids"], usd)
                ask_walk = _walk_book(book["asks"], usd)
                res[f"${int(usd)}"] = {
                    "sell_vwap": bid_walk["vwap"] if bid_walk else None,
                    "buy_vwap": ask_walk["vwap"] if ask_walk else None,
                    "spread_bps": (
                        (ask_walk["vwap"] - bid_walk["vwap"])
                        / ((ask_walk["vwap"] + bid_walk["vwap"]) / 2) * 10_000
                        if bid_walk and ask_walk else None
                    ),
                }
            return res
        out["binance_depth_probe"] = _safe(_depth_probe)

        return out

    @mcp.tool()
    def aggregator_route_order(
        coin: str, side: str, amount_usd: float,
        max_slippage_bps: float = 20.0, confirm: bool = False,
    ) -> dict[str, Any]:
        """Suggest where to place a spot order (and optionally execute it).

        Picks the single venue with the lowest effective-price ranking from
        ``aggregator_compare_buy_sell_prices``. Aborts if expected slippage
        vs cross-venue mid exceeds ``max_slippage_bps``.

        ``confirm=True`` sends a MARKET order on the chosen venue (Binance
        spot only for v1 — Kraken/WhiteBIT/HL routing left as TODO since
        those tools aren't yet wired into trading-mcp).
        """
        cmp = aggregator_compare_buy_sell_prices(coin, side, amount_usd)
        ranked = cmp.get("ranked") or []
        if not ranked:
            return {"error": "no venue could fill the order", "compare": cmp}
        best = ranked[0]
        slip = best.get("slippage_bps_vs_xvenue_mid")
        if slip is not None and slip > max_slippage_bps:
            return {
                "aborted": True,
                "reason": (
                    f"best venue slippage_bps={slip:.1f} exceeds "
                    f"max_slippage_bps={max_slippage_bps}"
                ),
                "best": best, "compare": cmp,
            }
        plan = {
            "venue": best["venue"],
            "coin": coin.upper(),
            "side": side.upper(),
            "amount_usd": amount_usd,
            "expected_vwap": best.get("vwap"),
            "expected_fee_bps": best.get("fee_bps"),
            "expected_effective_price": best.get("effective_price"),
            "expected_slippage_bps": slip,
        }
        if not confirm:
            return {"dry_run": True, "plan": plan, "compare": cmp}

        # Execution: Binance spot only for v1.
        if best["venue"] != "binance":
            return {
                "error": (
                    f"routing-execution not yet implemented for venue="
                    f"{best['venue']}. Re-call with confirm=False or use the "
                    f"venue-specific place_*_order tool."
                ),
                "plan": plan,
            }
        try:
            params: dict[str, Any] = {
                "symbol": f"{coin.upper()}USDT",
                "side": side.upper(),
                "type": "MARKET",
            }
            if side.upper() == "BUY":
                params["quoteOrderQty"] = amount_usd
            else:
                # SELL by base qty — use expected vwap to derive base size.
                qty = amount_usd / (best.get("vwap") or 1.0)
                params["quantity"] = qty
            order = _bn._client().create_order(**params)
            return {"plan": plan, "order": order, "compare": cmp}
        except Exception as e:  # noqa: BLE001
            return {"plan": plan, "error": str(e), "compare": cmp}

    # ----- 14. Funding-carry bot status ---------------------------------

    @mcp.tool()
    def funding_carry_status(
        coin: str | None = None, lookback_hours: int = 168
    ) -> dict[str, Any]:
        """Live status of the funding-carry bot's hedged position.

        The bot runs a delta-neutral carry: SHORT perp on the Hyperliquid
        vault + LONG spot on Kraken. This tool reconstructs performance from
        on-venue state — it does NOT read the bot's own fc_state.json, so
        figures are "since the venue lookback window", not since inception.

        - ``coin``: the carry asset (BTC/ETH/LINK/…). If omitted, auto-detected
          from the single open Hyperliquid perp position.
        - ``lookback_hours``: realized-funding window (default 168h = 7d).

        Reports: HL short (size, entry, uPnL, leverage, liq distance),
        realized funding collected + annualized on vault equity, the Kraken
        spot hedge leg, leg-delta (hedge quality), and current forward
        funding APR. Read-only.
        """
        import time

        out: dict[str, Any] = {
            "lookback_hours": lookback_hours,
            "caveats": [
                "Reconstructed from venue state, not the bot's fc_state.json "
                "— numbers are over the lookback window, not since inception.",
                "Kraken MCP key may differ from the bot's Kraken key; if the "
                "spot leg shows zero, the MCP is reading a different account.",
            ],
        }

        # --- Hyperliquid short leg ---------------------------------------
        def _hl_state() -> dict[str, Any]:
            return _hl._info().user_state(_hl._target_address()) or {}

        us = _safe(_hl_state)
        hl: dict[str, Any] = {"vault": _hl._target_address()}
        if isinstance(us, dict) and "error" not in us:
            ms = us.get("marginSummary", {}) or {}
            acct_val = float(ms.get("accountValue", 0) or 0)
            hl["account_value_usd"] = acct_val
            positions = []
            for ap in us.get("assetPositions", []) or []:
                p = ap.get("position", {}) or {}
                szi = float(p.get("szi", 0) or 0)
                if szi == 0:
                    continue
                lev = p.get("leverage", {}) or {}
                positions.append({
                    "coin": p.get("coin"),
                    "size": szi,
                    "side": "SHORT" if szi < 0 else "LONG",
                    "entry_px": float(p.get("entryPx", 0) or 0),
                    "position_value_usd": float(p.get("positionValue", 0) or 0),
                    "unrealized_pnl_usd": float(p.get("unrealizedPnl", 0) or 0),
                    "leverage": lev.get("value"),
                    "liquidation_px": p.get("liquidationPx"),
                })
            hl["positions"] = positions
            if coin is None and len(positions) == 1:
                coin = positions[0]["coin"]
        else:
            hl["error"] = us.get("error") if isinstance(us, dict) else str(us)
        out["coin"] = coin
        out["hyperliquid_short"] = hl

        # --- Realized funding over the window ----------------------------
        def _hl_funding() -> Any:
            start_ms = int(time.time() * 1000) - lookback_hours * 3600 * 1000
            info = _hl._info()
            method = getattr(info, "user_funding_history", None)
            if method:
                return method(_hl._target_address(), start_ms)
            return info.post("/info", {
                "type": "userFunding",
                "user": _hl._target_address(),
                "startTime": start_ms,
            })

        fund = _safe(_hl_funding)
        if isinstance(fund, list):
            total = 0.0
            coin_total = 0.0
            for ev in fund:
                d = (ev.get("delta") or {}) if isinstance(ev, dict) else {}
                if d.get("type") != "funding":
                    continue
                usdc = float(d.get("usdc", 0) or 0)
                total += usdc
                if coin and d.get("coin") == coin:
                    coin_total += usdc
            acct_val = hl.get("account_value_usd") or 0.0
            hrs = max(lookback_hours, 1)
            ann = (total / acct_val) * (8760 / hrs) if acct_val else None
            out["realized_funding"] = {
                "events": len(fund),
                "total_usdc": round(total, 6),
                "this_coin_usdc": round(coin_total, 6),
                "annualized_on_vault_equity": (
                    round(ann, 4) if ann is not None else None
                ),
                "note": "positive = received (short pays you when funding > 0)",
            }
        else:
            out["realized_funding"] = {
                "error": fund.get("error") if isinstance(fund, dict) else str(fund)
            }

        # --- Kraken spot hedge leg ---------------------------------------
        # Kraken asset codes diverge from tickers; map the common carry coins.
        _KR_ALIASES = {
            "BTC": ("XXBT", "XBT", "BTC"),
            "ETH": ("XETH", "ETH"),
            "DOGE": ("XXDG", "XDG", "DOGE"),
            "LINK": ("LINK",),
            "AVAX": ("AVAX",),
        }
        if _kr._credentials_present():
            bal = _safe(lambda: _kr._private("/0/private/Balance"))
            if isinstance(bal, dict) and "error" not in bal:
                spot_qty = 0.0
                matched_key = None
                if coin:
                    for k in _KR_ALIASES.get(coin.upper(), (coin.upper(),)):
                        if k in bal:
                            spot_qty = float(bal[k] or 0)
                            matched_key = k
                            break
                px = _binance_spot_price((coin or "").upper() + "USDT") if coin else None
                out["kraken_spot_hedge"] = {
                    "coin": coin,
                    "matched_balance_key": matched_key,
                    "qty": spot_qty,
                    "usd_value": round(spot_qty * px, 2) if px else None,
                    "all_balances": bal,
                }
            else:
                out["kraken_spot_hedge"] = {
                    "error": bal.get("error") if isinstance(bal, dict) else str(bal)
                }
        else:
            out["kraken_spot_hedge"] = {"error": "Kraken not configured in MCP"}

        # --- Leg delta (hedge quality) -----------------------------------
        try:
            short_sz = abs(
                next(
                    (p["size"] for p in hl.get("positions", []) if p["coin"] == coin),
                    0.0,
                )
            )
            long_sz = out["kraken_spot_hedge"].get("qty", 0.0) or 0.0
            net = long_sz - short_sz
            denom = max(short_sz, long_sz, 1e-9)
            out["leg_delta"] = {
                "hl_short_size": short_sz,
                "kraken_long_size": long_sz,
                "net_base": round(net, 8),
                "net_pct_of_leg": round(net / denom, 4),
                "note": (
                    "near 0 = well-hedged; large |net_pct| = unhedged "
                    "directional exposure (or MCP reading the wrong Kraken acct)"
                ),
            }
        except Exception as e:  # noqa: BLE001
            out["leg_delta"] = {"error": str(e)}

        # --- Forward funding APR for the coin ----------------------------
        if coin:
            def _fwd() -> float | None:
                meta_ctxs = _hl._info().meta_and_asset_ctxs()
                meta, ctxs = meta_ctxs[0], meta_ctxs[1]
                for u, c in zip(meta.get("universe", []), ctxs):
                    if u.get("name") == coin:
                        return float(c.get("funding", 0) or 0)
                return None

            hourly = _safe(_fwd)
            if isinstance(hourly, (int, float)):
                out["forward_funding"] = {
                    "hourly": hourly,
                    "apr": round(_hl._annualize_funding(hourly), 4),
                    "note": "short earns this when positive; flip risk if < 0",
                }
            else:
                out["forward_funding"] = {
                    "error": hourly.get("error")
                    if isinstance(hourly, dict) else str(hourly)
                }

        return out

    return 19
