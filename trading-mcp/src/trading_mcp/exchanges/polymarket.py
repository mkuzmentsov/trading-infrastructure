"""Polymarket tools — market scanning, analysis and CLOB trading.

Mirrors the pm-scout module workflow (hummingbot-infra/pm-scout): scan ALL
markets (newest precedence), inspect books/whale flow, review the wallet's
positions/redeemables, and place maker-first orders.

APIs:
  * Gamma  (``https://gamma-api.polymarket.com``)  — market catalog (public)
  * CLOB   (``https://clob.polymarket.com``)       — books + signed orders
  * Data   (``https://data-api.polymarket.com``)   — positions / trades (public)

Read tools register always. Trading tools register only when a wallet key is
configured. Redemption EXECUTION is intentionally NOT here (Safe/relayer flow
lives in the every-tick-single engine); ``polymarket_get_redeemable`` lists
what is claimable.

Env vars:
    POLYMARKET_PK               wallet private key           (trading tools)
    POLYMARKET_ADDRESS          proxy/EOA address            (positions fallback)
    POLYMARKET_FUNDER           Safe/deposit wallet          (positions holder)
    POLYMARKET_SIGNATURE_TYPE   0=EOA, 1=email proxy, 2=Gnosis Safe
    POLYGON_RPC_URL             optional — on-chain pUSD balance read
"""

from __future__ import annotations

import json
import os
import statistics
import time
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

_GAMMA = "https://gamma-api.polymarket.com"
_CLOB = "https://clob.polymarket.com"
_DATA = "https://data-api.polymarket.com"
_PUSD = "0xc011a7e12a19f7b1f670d46f03b03f3342e82dfb"  # Polymarket USD wrapper
_UA = {"User-Agent": "trading-mcp/1.0"}

_client_cache: Any = None


def _wallet() -> str:
    return os.environ.get("POLYMARKET_FUNDER") or os.environ.get("POLYMARKET_ADDRESS") or ""


def _creds_present() -> bool:
    return bool(os.environ.get("POLYMARKET_PK"))


def _get(base: str, path: str, params: dict | None = None) -> Any:
    r = httpx.get(f"{base}{path}", params=params, headers=_UA, timeout=25)
    r.raise_for_status()
    return r.json()


def _f(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def _jlist(v: Any) -> list:
    try:
        return json.loads(v) if isinstance(v, str) else (v or [])
    except Exception:
        return []


def _slim(m: dict) -> dict:
    ev = (m.get("events") or [{}])[0] if m.get("events") else {}
    return {
        "question": m.get("question"),
        "slug": m.get("slug"),
        "event": ev.get("title"),
        "category": m.get("category") or ev.get("category"),
        "created": m.get("createdAt") or m.get("startDate"),
        "end": m.get("endDate"),
        "volume24h": _f(m.get("volume24hr")),
        "liquidity": _f(m.get("liquidityNum") or m.get("liquidity")),
        "outcomes": _jlist(m.get("outcomes")),
        "prices": [_f(p) for p in _jlist(m.get("outcomePrices"))],
        "bestBid": _f(m.get("bestBid")),
        "bestAsk": _f(m.get("bestAsk")),
        "tokens": _jlist(m.get("clobTokenIds")),
        "conditionId": m.get("conditionId"),
        "negRisk": bool(m.get("negRisk")),
        "feesEnabled": m.get("feesEnabled"),
        "rewardsMinSize": _f(m.get("rewardsMinSize")),
        "rewardsMaxSpread": _f(m.get("rewardsMaxSpread")),
    }


def _clob_client():
    """Lazy singleton py-clob-client-v2 client (signed order path)."""
    global _client_cache
    if _client_cache is not None:
        return _client_cache
    from py_clob_client_v2 import ClobClient

    client = ClobClient(
        host=_CLOB,
        key=os.environ["POLYMARKET_PK"],
        chain_id=137,
        signature_type=int(os.environ.get("POLYMARKET_SIGNATURE_TYPE", "0")),
        funder=os.environ.get("POLYMARKET_FUNDER") or None,
    )
    client.set_api_creds(client.create_or_derive_api_key())
    _client_cache = client
    return client


def register(mcp: FastMCP) -> int:
    count = 0

    # ----- Market discovery (public) -------------------------------------

    @mcp.tool()
    def polymarket_scan_markets(
        view: str = "newest",
        limit: int = 25,
        min_liquidity: float = 0,
        max_pages: int = 12,
    ) -> list[dict[str, Any]]:
        """Scan active Polymarket markets. view: 'newest' (default — newest
        markets take precedence, least efficient prices), 'volume' (top 24h
        movers), 'closing' (ending soonest), 'rewards' (liquidity-rewards
        carrying). Returns compact market records incl. tokens/conditionId
        for follow-up book/flow/order calls."""
        order = {"newest": "startDate", "volume": "volume24hr",
                 "closing": "endDate", "rewards": "volume24hr"}.get(view, "startDate")
        asc = "true" if view == "closing" else "false"
        rows: list[dict] = []
        offset = 0
        for _ in range(max_pages):
            try:
                batch = _get(_GAMMA, "/markets", {
                    "active": "true", "closed": "false", "limit": 100,
                    "offset": offset, "order": order, "ascending": asc})
            except httpx.HTTPStatusError:
                break                      # gamma caps pagination depth (422)
            if not batch:
                break
            rows.extend(batch)
            offset += len(batch)
            if len(batch) < 100:
                break
        out = []
        now = time.time()
        for m in rows:
            s = _slim(m)
            if not s["tokens"] or s["liquidity"] < min_liquidity:
                continue
            if view == "rewards" and s["rewardsMinSize"] <= 0:
                continue
            if view == "closing":
                try:
                    endts = time.mktime(time.strptime((s["end"] or "")[:19], "%Y-%m-%dT%H:%M:%S"))
                    if endts < now:
                        continue
                except Exception:
                    continue
            out.append(s)
            if len(out) >= limit:
                break
        return out

    @mcp.tool()
    def polymarket_get_market(slug: str = "", condition_id: str = "") -> dict[str, Any]:
        """Full detail for one market by slug OR conditionId — including the
        DESCRIPTION (resolution rules — always read before betting), fees,
        rewards config, tokens and current prices."""
        params = {"slug": slug} if slug else {"condition_ids": condition_id}
        d = _get(_GAMMA, "/markets", params)
        if not d:
            raise RuntimeError("market not found")
        m = d[0]
        s = _slim(m)
        s["description"] = m.get("description")
        s["resolutionSource"] = m.get("resolutionSource")
        s["orderMinSize"] = _f(m.get("orderMinSize"), 5.0)
        s["closed"] = m.get("closed")
        return s

    @mcp.tool()
    def polymarket_get_book(token_id: str, size: float = 100) -> dict[str, Any]:
        """CLOB order book for a token: best bid/ask, mid, spread, depth within
        ±2c, and whether `size` shares fit inside 2c (THIN warning)."""
        b = _get(_CLOB, "/book", {"token_id": token_id})
        bids = sorted(((_f(x["price"]), _f(x["size"])) for x in b.get("bids", [])), reverse=True)
        asks = sorted(((_f(x["price"]), _f(x["size"])) for x in b.get("asks", [])))
        if not bids or not asks:
            return {"empty": True, "n_bids": len(bids), "n_asks": len(asks)}
        bb, ba = bids[0][0], asks[0][0]
        d_bid = sum(s for p, s in bids if p >= bb - 0.02)
        d_ask = sum(s for p, s in asks if p <= ba + 0.02)
        return {"bid": bb, "ask": ba, "mid": round((bb + ba) / 2, 4),
                "spread": round(ba - bb, 4), "depth_bid_2c": d_bid,
                "depth_ask_2c": d_ask, "fits": min(d_bid, d_ask) >= size}

    @mcp.tool()
    def polymarket_get_flow(condition_id: str, hours: float = 48, whale_x: float = 20) -> dict[str, Any]:
        """Insider/whale flow analysis for a market: net aggressive flow per
        outcome, buyer concentration, and the largest recent prints. A massive
        one-sided entry without public news often front-runs announcements
        (follow-signal); a big dump against a held side is a close-warning."""
        cutoff = time.time() - hours * 3600
        ts: list[dict] = []
        offset = 0
        for _ in range(10):
            batch = _get(_DATA, "/trades", {"market": condition_id, "limit": 500, "offset": offset})
            if not isinstance(batch, list) or not batch:
                break
            ts.extend(batch)
            if _f(batch[-1].get("timestamp")) < cutoff or len(batch) < 500:
                break
            offset += len(batch)
        ts = [t for t in ts if _f(t.get("timestamp")) >= cutoff]
        if not ts:
            return {"trades": 0}
        sizes = [_f(t.get("size")) for t in ts]
        med = statistics.median(sizes) or 1.0
        flows: dict[str, float] = {}
        buyers: dict[str, float] = {}
        for t in ts:
            oc = t.get("outcome") or "?"
            usd = _f(t.get("size")) * _f(t.get("price"))
            sgn = 1 if (t.get("side") or "").upper() == "BUY" else -1
            flows[oc] = round(flows.get(oc, 0.0) + sgn * usd, 2)
            if sgn > 0:
                w = t.get("proxyWallet") or t.get("pseudonym") or "?"
                buyers[w] = buyers.get(w, 0.0) + usd
        top3 = sorted(buyers.values(), reverse=True)[:3]
        whales = sorted((t for t in ts if _f(t.get("size")) >= whale_x * med),
                        key=lambda x: -_f(x.get("size")))[:10]
        return {
            "trades": len(ts), "median_size": med,
            "top3_buyer_concentration": round(sum(top3) / (sum(buyers.values()) or 1), 3),
            "net_flow_usd": flows,
            "whale_prints": [{
                "time": time.strftime("%Y-%m-%d %H:%M", time.gmtime(_f(t.get("timestamp")))),
                "side": t.get("side"), "outcome": t.get("outcome"),
                "shares": _f(t.get("size")), "price": _f(t.get("price")),
                "who": t.get("pseudonym") or t.get("proxyWallet"),
            } for t in whales],
        }

    count += 4

    # ----- Reward-pool farming / venue structure (public) ------------------

    @mcp.tool()
    def polymarket_get_books(token_ids: list[str]) -> list[dict[str, Any]]:
        """Batch order books (one CLOB round-trip for many tokens). Use instead
        of looping polymarket_get_book — the venue caps request rate, and a
        multi-leg thesis must read every leg at the SAME instant to be valid."""
        out: list[dict[str, Any]] = []
        for i in range(0, len(token_ids), 250):
            chunk = token_ids[i:i + 250]
            r = httpx.post(f"{_CLOB}/books", json=[{"token_id": t} for t in chunk],
                           headers=_UA, timeout=45)
            r.raise_for_status()
            for b in r.json():
                bids = sorted(((_f(x["price"]), _f(x["size"])) for x in b.get("bids", [])), reverse=True)
                asks = sorted(((_f(x["price"]), _f(x["size"])) for x in b.get("asks", [])))
                out.append({
                    "token_id": b.get("asset_id"),
                    "bid": bids[0][0] if bids else None, "bid_size": bids[0][1] if bids else 0.0,
                    "ask": asks[0][0] if asks else None, "ask_size": asks[0][1] if asks else 0.0,
                    "mid": round((bids[0][0] + asks[0][0]) / 2, 4) if bids and asks else None,
                })
        return out

    @mcp.tool()
    def polymarket_scan_reward_pools(
        limit: int = 25,
        max_capital: float = 0,
        min_pool: float = 1.0,
        max_pages: int = 30,
    ) -> dict[str, Any]:
        """⭐ Screen LIVE liquidity-reward pools by capturable yield, measured
        against the REAL book (not gamma's cached bestBid/bestAsk).

        For each market carrying a reward pool this reads the actual CLOB book,
        counts the qualifying competition — resting size >= rewardsMinSize and
        within rewardsMaxSpread of the midpoint, the only orders that score —
        and models your share as minSize/(minSize + competition), the payout
        formula's Q_normal when you post the minimum qualifying quote.

        `capital_usd` is the cost of a two-sided minimum quote (one share of
        YES + one of NO costs $1, so it is ~rewardsMinSize dollars).

        CAVEATS the caller must respect:
          * `est_daily_usd` assumes competition stays as it is now. An empty
            band is usually a pool that only just opened — first movers get it
            until others arrive.
          * Rewards pay only while you are quoted; the payout floor is $1/day,
            so rows under ~$1 are unlikely to pay at all.
          * A wide book (`spread` large) means the midpoint is barely
            informative — quoting inside it invites adverse selection. Weigh
            `est_daily_usd` against `spread` * size before deploying.
        """
        rows: list[dict] = []
        offset = 0
        for _ in range(max_pages):
            try:
                batch = _get(_GAMMA, "/markets",
                             {"closed": "false", "limit": 100, "offset": offset})
            except httpx.HTTPStatusError:
                break
            if not isinstance(batch, list) or not batch:
                break
            rows.extend([b for b in batch if isinstance(b, dict)])
            if len(batch) < 100:
                break
            offset += 100

        cands = []
        for m in rows:
            pool = sum(_f(x.get("rewardsDailyRate"))
                       for x in (m.get("clobRewards") or []) if isinstance(x, dict))
            toks = _jlist(m.get("clobTokenIds"))
            if pool < min_pool or len(toks) != 2:
                continue
            minsz = _f(m.get("rewardsMinSize"))
            if max_capital and minsz > max_capital:
                continue
            cands.append((m, pool, toks, minsz, _f(m.get("rewardsMaxSpread"))))

        books: dict[str, dict] = {}
        flat = [t for _, _, toks, _, _ in cands for t in toks]
        for i in range(0, len(flat), 250):
            chunk = flat[i:i + 250]
            try:
                r = httpx.post(f"{_CLOB}/books", json=[{"token_id": t} for t in chunk],
                               headers=_UA, timeout=45)
                r.raise_for_status()
                for b in r.json():
                    books[b["asset_id"]] = b
            except Exception:
                continue

        out = []
        for m, pool, toks, minsz, maxspread in cands:
            b = books.get(toks[0])
            if not b:
                continue
            bids = sorted(((_f(x["price"]), _f(x["size"])) for x in b.get("bids", [])), reverse=True)
            asks = sorted(((_f(x["price"]), _f(x["size"])) for x in b.get("asks", [])))
            if not bids or not asks:
                mid = None
                comp = 0.0
                spread = None
            else:
                mid = (bids[0][0] + asks[0][0]) / 2
                spread = round(asks[0][0] - bids[0][0], 4)
                qb = sum(s for p, s in bids if (mid - p) * 100 <= maxspread and s >= minsz)
                qa = sum(s for p, s in asks if (p - mid) * 100 <= maxspread and s >= minsz)
                comp = min(qb, qa)          # the payout takes min of the two book sides
            share = minsz / (minsz + comp) if (minsz + comp) > 0 else 1.0
            est = pool * share
            out.append({
                "slug": m.get("slug"),
                "question": m.get("question"),
                "pool_usd_day": pool,
                "competition_shares": round(comp, 1),
                "est_daily_usd": round(est, 2),
                "capital_usd": round(minsz, 2),
                "return_pct_day": round(est / minsz * 100, 1) if minsz else None,
                "min_size": minsz, "max_spread_c": maxspread,
                "mid": round(mid, 4) if mid else None, "spread": spread,
                "end": m.get("endDate"),
                "fees_enabled": bool(m.get("feesEnabled")),
                "condition_id": m.get("conditionId"),
                "tokens": toks,
            })
        out.sort(key=lambda x: -(x["est_daily_usd"]))
        return {
            "scanned_markets": len(rows),
            "reward_markets": len(cands),
            "total_live_pool_usd_day": round(sum(c[1] for c in cands), 2),
            "top": out[:limit],
        }

    @mcp.tool()
    def polymarket_scan_negrisk(limit: int = 15, max_pages: int = 30) -> dict[str, Any]:
        """Scan neg-risk (multi-outcome, one-winner) events for basket
        mispricing, priced off the REAL books.

        Reports per event: sum of best ASKs across every YES leg (buy-the-field
        cost) and sum of best BIDs (sell-the-field proceeds).

        ⚠️ Read the direction asymmetry before trading either:
          * `sum_ask < 1` is NOT automatically an arb. Most Polymarket
            multi-outcome events are AUGMENTED neg-risk — they carry unnamed
            placeholder slots and an "Other" outcome, so the listed legs are
            not a complete partition. A sum below 1 is usually just the
            market's probability that the winner is unlisted.
          * `sum_bid > 1` IS a genuine arb regardless of completeness: you are
            paid more than $1 to cover a set that pays at most $1, and an
            unlisted winner makes every leg you sold expire worthless.
        `complete_set_risk` flags events whose legs may not be exhaustive.
        """
        rows: list[dict] = []
        offset = 0
        for _ in range(max_pages):
            try:
                batch = _get(_GAMMA, "/markets",
                             {"closed": "false", "limit": 100, "offset": offset})
            except httpx.HTTPStatusError:
                break
            if not isinstance(batch, list) or not batch:
                break
            rows.extend([b for b in batch if isinstance(b, dict)])
            if len(batch) < 100:
                break
            offset += 100

        groups: dict[str, list] = {}
        for m in rows:
            if m.get("negRisk") and m.get("negRiskMarketID"):
                groups.setdefault(m["negRiskMarketID"], []).append(m)
        groups = {k: v for k, v in groups.items() if len(v) >= 2}

        flat = [_jlist(m.get("clobTokenIds"))[0]
                for v in groups.values() for m in v if _jlist(m.get("clobTokenIds"))]
        books: dict[str, dict] = {}
        for i in range(0, len(flat), 250):
            try:
                r = httpx.post(f"{_CLOB}/books",
                               json=[{"token_id": t} for t in flat[i:i + 250]],
                               headers=_UA, timeout=45)
                r.raise_for_status()
                for b in r.json():
                    books[b["asset_id"]] = b
            except Exception:
                continue

        out = []
        for _k, v in groups.items():
            sa = sb = 0.0
            missing = 0
            fee = 0.0
            rate = _f((v[0].get("feeSchedule") or {}).get("rate")) if v[0].get("feesEnabled") else 0.0
            for m in v:
                t = _jlist(m.get("clobTokenIds"))
                b = books.get(t[0]) if t else None
                asks = sorted((_f(x["price"]) for x in (b or {}).get("asks", [])))
                bids = sorted((_f(x["price"]) for x in (b or {}).get("bids", [])), reverse=True)
                if asks:
                    sa += asks[0]
                else:
                    missing += 1
                if bids:
                    sb += bids[0]
                    # hitting a bid makes you the TAKER: rate * p * (1-p) per share
                    fee += rate * bids[0] * (1 - bids[0])
            ev = (v[0].get("events") or [{}])[0] if v[0].get("events") else {}
            titles = " ".join((m.get("groupItemTitle") or "") for m in v).lower()
            gross = sb - 1.0
            out.append({
                "event": ev.get("slug") or v[0].get("slug"),
                "legs": len(v), "legs_without_ask": missing,
                "sum_ask": round(sa, 4), "sum_bid": round(sb, 4),
                "sell_field_gross_edge": round(gross, 4),
                "taker_fee_cost": round(fee, 4),
                "sell_field_net_edge": round(gross - fee, 4),
                "complete_set_risk": ("other" not in titles) or missing > 0,
                "fee_free": not bool(v[0].get("feesEnabled")),
            })
        out.sort(key=lambda x: -x["sell_field_net_edge"])
        return {"events_scanned": len(groups),
                "note": ("sum_bid > 1.0 is the tradeable direction (mint a YES+NO pair for $1, "
                         "sell both into the bids). Only sell_field_net_edge > 0 is real — on a "
                         "fee-enabled market the taker fee rate*p*(1-p) per share typically "
                         "cancels a 1c gross edge exactly. fee_free markets (Geopolitics and "
                         "world events) are where a thin edge survives. "
                         "sum_ask < 1.0 is usually just an incomplete outcome set, not an arb."),
                "best_sell_field": out[:limit],
                "cheapest_buy_field": sorted(out, key=lambda x: x["sum_ask"])[:limit]}

    @mcp.tool()
    def polymarket_get_combo_markets(limit: int = 25, search: str = "") -> dict[str, Any]:
        """Catalog of markets usable as COMBO legs (multi-leg conjunction
        positions priced by RFQ), plus whether combo trading is actually open.

        A combo YES pays only if EVERY leg pays; the NO is the complement. Legs
        are quoted by competing market makers in a 400ms auction, so a combo is
        the way to express a correlated multi-market view without legging in
        (and without paying the spread on each leg separately).

        `rfq_live` reports whether quoting is enabled yet — while every market
        reports `pending`, the catalog exists but no RFQ can be executed."""
        params: dict[str, Any] = {"limit": min(limit, 100)}
        if search:
            params["search"] = search
        d = httpx.get("https://combos-rfq-api.polymarket.com/v1/rfq/combo-markets",
                      params=params, headers=_UA, timeout=30).json()
        mkts = d.get("markets") or []
        rows = [{
            "slug": m.get("slug"), "title": m.get("title"),
            "prices": m.get("outcome_prices"), "volume": _f(m.get("volume")),
            "pending": m.get("pending"), "tags": m.get("tags"),
            "condition_id": m.get("condition_id"),
            "position_ids": m.get("position_ids"),
        } for m in mkts[:limit]]
        return {"rfq_live": any(not r["pending"] for r in rows),
                "count": len(rows), "markets": rows}

    @mcp.tool()
    def polymarket_get_clob_market_info(condition_id: str) -> dict[str, Any]:
        """Authoritative CLOB-level parameters for one market in a single call —
        tick size, minimum order size, taker/maker base fees, the live rewards
        configuration and RFQ status. Use this (not gamma) before quoting: the
        tick size decides your minimum price improvement and gamma's copy of the
        reward config can lag."""
        d = _get(_CLOB, f"/markets/{condition_id}")
        return d if isinstance(d, dict) else {"raw": str(d)}

    @mcp.tool()
    def polymarket_get_price_history(
        token_id: str, interval: str = "1w", fidelity: int = 60
    ) -> dict[str, Any]:
        """Price time series for a token. interval: 1h/6h/1d/1w/1m/max,
        fidelity = minutes per point. Returns the series plus range, realised
        volatility and drift — enough to judge whether a resting quote will be
        run over before its reward accrues."""
        d = _get(_CLOB, "/prices-history",
                 {"market": token_id, "interval": interval, "fidelity": fidelity})
        h = d.get("history") or []
        px = [_f(p.get("p")) for p in h]
        if not px:
            return {"points": 0}
        rets = [px[i] - px[i - 1] for i in range(1, len(px))]
        vol = statistics.pstdev(rets) if len(rets) > 1 else 0.0
        return {
            "points": len(px), "first": px[0], "last": px[-1],
            "min": min(px), "max": max(px),
            "drift": round(px[-1] - px[0], 4),
            "vol_per_point": round(vol, 5),
            "series": [{"t": p.get("t"), "p": _f(p.get("p"))} for p in h[-200:]],
        }

    @mcp.tool()
    def polymarket_scan_cheap_longshots(
        max_price: float = 0.10,
        min_volume24h: float = 0,
        min_liquidity: float = 500,
        limit: int = 25,
        max_pages: int = 30,
    ) -> dict[str, Any]:
        """Screen cheap outcomes for asymmetric payoff — small stake, large
        multiple if it hits. Ranked by payoff multiple with the liquidity to
        actually get filled and out.

        Reports `fee_free` (Geopolitics and world-event markets charge NO taker
        fee — on every other category a taker pays rate*p*(1-p) per share, which
        at a 5c entry is small but not zero) and `holding_rewards` (the venue
        flags some long-dated markets as holding-reward eligible).

        This is a SCREEN, not a recommendation: a 20x payoff priced at 5c is the
        market saying 5%, and it is usually right. Read the market description
        with polymarket_get_market before staking anything — resolution wording,
        not the headline, decides these."""
        rows: list[dict] = []
        offset = 0
        for _ in range(max_pages):
            try:
                batch = _get(_GAMMA, "/markets",
                             {"closed": "false", "limit": 100, "offset": offset})
            except httpx.HTTPStatusError:
                break
            if not isinstance(batch, list) or not batch:
                break
            rows.extend([b for b in batch if isinstance(b, dict)])
            if len(batch) < 100:
                break
            offset += 100
        out = []
        for m in rows:
            toks = _jlist(m.get("clobTokenIds"))
            prices = [_f(p) for p in _jlist(m.get("outcomePrices"))]
            outcomes = _jlist(m.get("outcomes"))
            liq = _f(m.get("liquidityNum") or m.get("liquidity"))
            if len(toks) != 2 or len(prices) != 2 or liq < min_liquidity:
                continue
            if _f(m.get("volume24hr")) < min_volume24h:
                continue
            for i, p in enumerate(prices):
                if 0 < p <= max_price:
                    out.append({
                        "slug": m.get("slug"), "question": m.get("question"),
                        "outcome": outcomes[i] if i < len(outcomes) else str(i),
                        "price": p, "payoff_multiple": round(1 / p, 1),
                        "token_id": toks[i],
                        "liquidity": round(liq, 0),
                        "volume24h": round(_f(m.get("volume24hr")), 0),
                        "fee_free": not bool(m.get("feesEnabled")),
                        "holding_rewards": bool(m.get("holdingRewardsEnabled")),
                        "tick": _f(m.get("orderPriceMinTickSize")),
                        "end": m.get("endDate"),
                        "condition_id": m.get("conditionId"),
                    })
        out.sort(key=lambda x: -x["payoff_multiple"])
        return {"scanned": len(rows), "found": len(out), "candidates": out[:limit]}

    count += 7

    # ----- Portfolio (needs wallet address only) --------------------------

    if _wallet():
        @mcp.tool()
        def polymarket_get_positions() -> dict[str, Any]:
            """Wallet portfolio: on-chain pUSD balance (if POLYGON_RPC_URL set),
            open positions (entry vs mark, uPnL, end date) and redeemable
            (resolved, claimable) positions. NOTE: if a position exists in a
            market, adjust it (close/increase) — never open an independent bet."""
            user = _wallet()
            pos = _get(_DATA, "/positions", {"user": user, "sizeThreshold": "0.01", "limit": 200})
            pos = pos if isinstance(pos, list) else []
            bal = None
            rpc = os.environ.get("POLYGON_RPC_URL")
            if rpc:
                try:
                    addr = user.lower().removeprefix("0x")
                    r = httpx.post(rpc, json={
                        "jsonrpc": "2.0", "id": 1, "method": "eth_call",
                        "params": [{"to": _PUSD, "data": "0x70a08231" + "0" * 24 + addr}, "latest"]},
                        timeout=15).json()
                    bal = int(r["result"], 16) / 1e6
                except Exception:
                    bal = None
            def row(p):
                return {"title": p.get("title"), "outcome": p.get("outcome"),
                        "size": _f(p.get("size")), "avgPrice": _f(p.get("avgPrice")),
                        "curPrice": _f(p.get("curPrice")), "value": _f(p.get("currentValue")),
                        "uPnl": _f(p.get("cashPnl")), "end": p.get("endDate"),
                        "conditionId": p.get("conditionId"), "token": p.get("asset")}
            openp = [row(p) for p in pos if not p.get("redeemable")]
            redeem = [row(p) for p in pos
                      if p.get("redeemable") and _f(p.get("currentValue")) >= 0.01]
            return {"wallet": user, "balance_usd": bal, "open": openp,
                    "redeemable": redeem,
                    "redeemable_total_usd": round(sum(r["value"] for r in redeem), 2)}

        @mcp.tool()
        def polymarket_get_redeemable() -> list[dict[str, Any]]:
            """Resolved-but-unclaimed positions worth redeeming (value ≥ $0.01).
            Redemption execution runs via the pm-scout/engine path, not this MCP."""
            pos = _get(_DATA, "/positions", {"user": _wallet(), "sizeThreshold": "0.01",
                                             "redeemable": "true", "limit": 200})
            pos = pos if isinstance(pos, list) else []
            return [{"title": p.get("title"), "outcome": p.get("outcome"),
                     "value": _f(p.get("currentValue")), "conditionId": p.get("conditionId")}
                    for p in pos if _f(p.get("currentValue")) >= 0.01]

        @mcp.tool()
        def polymarket_get_activity(kind: str = "all", limit: int = 60) -> dict[str, Any]:
            """Account activity ledger from the data-api. kind filters the type:
            'all', 'trade', 'redeem' (resolved-position payouts),
            'rebate' (MAKER_REBATE — maker's share of counterparty fees),
            'reward' (REWARD if present), 'conversion'. Returns per-type totals
            (redeemed $, rebate $, trade count) plus the most recent rows."""
            rows = _get(_DATA, "/activity", {"user": _wallet(), "limit": 500})
            rows = rows if isinstance(rows, list) else []
            kmap = {"trade": "TRADE", "redeem": "REDEEM", "rebate": "MAKER_REBATE",
                    "reward": "REWARD", "conversion": "CONVERSION", "split": "SPLIT",
                    "merge": "MERGE"}
            totals: dict[str, dict] = {}
            for r in rows:
                t = r.get("type", "?")
                d = totals.setdefault(t, {"count": 0, "usd": 0.0})
                d["count"] += 1
                d["usd"] = round(d["usd"] + _f(r.get("usdcSize")), 4)
            want = kmap.get(kind.lower())
            sel = rows if kind == "all" else [r for r in rows if r.get("type") == want]
            recent = [{
                "type": r.get("type"), "side": r.get("side"),
                "usd": _f(r.get("usdcSize")), "size": _f(r.get("size")),
                "price": _f(r.get("price")), "outcome": r.get("outcome"),
                "title": (r.get("title") or "")[:60],
                "time": r.get("timestamp"), "tx": r.get("transactionHash"),
            } for r in sel[:limit]]
            return {"wallet": _wallet(), "totals_by_type": totals,
                    "n_returned": len(recent), "activity": recent}

        @mcp.tool()
        def polymarket_get_transfers(direction: str = "both", limit: int = 25) -> dict[str, Any]:
            """On-chain pUSD money movements (deposits / withdrawals / settlements)
            via the Polygon RPC (needs POLYGON_RPC_URL). direction: 'in', 'out',
            'both'. Incoming from the zero address = a MINT (a deposit OR a
            redemption payout — cross-check polymarket_get_activity REDEEM to tell
            them apart); outgoing to an external address = a withdrawal; other
            moves are order settlements. Returns rows + net flow."""
            rpc = os.environ.get("POLYGON_RPC_URL")
            if not rpc:
                return {"error": "POLYGON_RPC_URL not configured"}
            user = _wallet()

            def fetch(key):
                body = {"jsonrpc": "2.0", "id": 1, "method": "alchemy_getAssetTransfers",
                        "params": [{key: user, "category": ["erc20"],
                                    "withMetadata": True, "excludeZeroValue": True,
                                    "maxCount": hex(min(limit, 100)), "order": "desc"}]}
                r = httpx.post(rpc, json=body, timeout=25).json()
                return r.get("result", {}).get("transfers", [])

            def norm(t, io):
                cp = (t.get("from") if io == "in" else t.get("to")) or ""
                return {"dir": io, "value": _f(t.get("value")),
                        "asset": t.get("asset"), "counterparty": cp,
                        "mint": cp.lower().startswith("0x0000000000"),
                        "time": t.get("metadata", {}).get("blockTimestamp"),
                        "tx": t.get("hash")}
            out = []
            if direction in ("in", "both"):
                out += [norm(t, "in") for t in fetch("toAddress")]
            if direction in ("out", "both"):
                out += [norm(t, "out") for t in fetch("fromAddress")]
            out.sort(key=lambda x: x.get("time") or "", reverse=True)
            inflow = round(sum(x["value"] for x in out if x["dir"] == "in"), 4)
            outflow = round(sum(x["value"] for x in out if x["dir"] == "out"), 4)
            return {"wallet": user, "inflow_usd": inflow, "outflow_usd": outflow,
                    "net_usd": round(inflow - outflow, 4),
                    "transfers": out[:limit]}

        count += 4

    # ----- Trading (needs wallet key) -------------------------------------

    if _creds_present():
        @mcp.tool()
        def polymarket_place_order(
            token_id: str,
            price: float,
            shares: float,
            side: str = "BUY",
            execution: str = "maker",
        ) -> dict[str, Any]:
            """Place a CLOB order. execution='maker' (default) posts a GTC
            post-only limit — the exchange REJECTS it if it would cross, a hard
            maker guarantee (zero fee + rebates/rewards). execution='taker'
            posts FAK (fill available up to price, kill rest) — only for
            time-critical theses. side: BUY or SELL."""
            from py_clob_client_v2 import OrderArgs, OrderType

            client = _clob_client()
            args = OrderArgs(token_id=token_id, price=price, size=shares,
                             side=side.upper(), expiration=0)
            signed = client.create_order(args)
            if execution == "maker":
                resp = client.post_order(signed, OrderType.GTC, post_only=True)
            else:
                resp = client.post_order(signed, OrderType.FAK)
            return {"order_id": resp.get("orderID") or resp.get("order_id"),
                    "status": resp.get("status"), "success": resp.get("success"),
                    "making": resp.get("makingAmount"), "taking": resp.get("takingAmount"),
                    "error": resp.get("errorMsg") or None}

        @mcp.tool()
        def polymarket_get_open_orders() -> list[dict[str, Any]]:
            """All resting (unfilled/partially-filled) CLOB orders for the wallet:
            side, price, original vs matched size, market, order id."""
            try:
                orders = _clob_client().get_open_orders()
            except Exception as exc:
                return [{"error": str(exc)}]
            orders = orders if isinstance(orders, list) else []
            return [{
                "order_id": o.get("id") or o.get("orderID"),
                "side": o.get("side"), "price": _f(o.get("price")),
                "size": _f(o.get("original_size") or o.get("size")),
                "matched": _f(o.get("size_matched")),
                "market": o.get("market"), "asset_id": o.get("asset_id"),
                "outcome": o.get("outcome"), "created": o.get("created_at"),
            } for o in orders]

        @mcp.tool()
        def polymarket_get_rewards(days: int = 7) -> dict[str, Any]:
            """Maker income, split correctly into the TWO distinct mechanisms:
            (1) liquidity REWARDS — daily pool payments for resting quotes near
            mid (CLOB earnings ledger); (2) maker REBATES — the maker's share of
            the counterparty's taker fee (data-api MAKER_REBATE). Returns per-day
            rewards for the last `days` + lifetime rebate total. Note: on markets
            whose live taker fee is 0 bps, rebates are structurally $0."""
            import datetime as _dt
            clob = _clob_client()
            reward_days = []
            reward_total = 0.0
            base = _dt.date.today()
            for i in range(days):
                d = (base - _dt.timedelta(days=i)).isoformat()
                try:
                    tot = clob.get_total_earnings_for_user_for_day(d)
                    day_usd = round(sum(_f(x.get("earnings")) for x in tot), 6) if tot else 0.0
                except Exception:
                    day_usd = 0.0
                reward_days.append({"date": d, "reward_usd": day_usd})
                reward_total += day_usd
            # rebates from the activity ledger
            act = _get(_DATA, "/activity", {"user": _wallet(), "limit": 500})
            act = act if isinstance(act, list) else []
            rebates = [a for a in act if a.get("type") == "MAKER_REBATE"]
            rebate_total = round(sum(_f(a.get("usdcSize")) for a in rebates), 6)
            return {"wallet": _wallet(),
                    "liquidity_rewards": {"last_days": reward_days,
                                          "total_usd": round(reward_total, 6)},
                    "maker_rebates": {"count": len(rebates),
                                      "total_usd": rebate_total}}

        @mcp.tool()
        def polymarket_get_reward_percentages() -> dict[str, Any]:
            """Live share of each reward market's pool this wallet is currently
            earning — the real-time feedback loop for reward farming. A market
            you are quoting that shows a 0% share means your orders are NOT
            scoring: too small (< rewardsMinSize), too far from the midpoint
            (> rewardsMaxSpread), or one-sided in a market whose midpoint sits
            outside [0.10, 0.90], where scoring requires BOTH sides."""
            clob = _clob_client()
            for meth in ("get_reward_percentages", "get_user_reward_percentages"):
                fn = getattr(clob, meth, None)
                if fn:
                    try:
                        d = fn()
                        return {"wallet": _wallet(), "markets": d}
                    except Exception as exc:
                        return {"wallet": _wallet(), "error": str(exc), "method": meth}
            return {"wallet": _wallet(),
                    "error": "client exposes no reward-percentage method",
                    "available": [m for m in dir(clob) if "reward" in m.lower()]}

        @mcp.tool()
        def polymarket_check_order_scoring(order_id: str) -> dict[str, Any]:
            """Is this resting order currently earning liquidity rewards?
            Check after placing a farming quote — an order can be live on the
            book and still score nothing."""
            clob = _clob_client()
            fn = getattr(clob, "is_order_scoring", None)
            if not fn:
                return {"error": "client exposes no order-scoring method",
                        "available": [m for m in dir(clob) if "scor" in m.lower()]}
            try:
                return {"order_id": order_id, "scoring": fn(order_id)}
            except Exception as exc:
                return {"order_id": order_id, "error": str(exc)}

        count += 2

        @mcp.tool()
        def polymarket_get_order(order_id: str) -> dict[str, Any]:
            """Order status: live/matched/cancelled, size_matched, price."""
            o = _clob_client().get_order(order_id)
            return o if isinstance(o, dict) else {"raw": str(o)}

        @mcp.tool()
        def polymarket_cancel_order(order_id: str) -> dict[str, Any]:
            """Cancel a resting order by id."""
            from py_clob_client_v2 import OrderPayload

            resp = _clob_client().cancel_order(OrderPayload(orderID=order_id))
            return resp if isinstance(resp, dict) else {"raw": str(resp)}

        count += 5

    return count
