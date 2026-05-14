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
from . import hyperliquid as _hl
from . import kraken as _kr
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
        Hyperliquid HLP (USDC only).

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
        across Hyperliquid and Binance USDⓈ-M.

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
                    q = float(b["free"]) + float(b["locked"])
                    if q > 0:
                        _track("binance", b["asset"], q, "spot")
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

    return 6
