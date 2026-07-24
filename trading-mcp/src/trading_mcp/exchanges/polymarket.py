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
