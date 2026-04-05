"""
Polymarket CLOB WebSocket — real-time UP/DOWN book state.

On startup and every MARKET_REFRESH_SECS, fetches the active BTC 5-min
UP/DOWN market from the Gamma REST API and subscribes to its token IDs.

Book events update pm_state.up_bid / up_ask / down_bid / down_ask in place.
"""
from __future__ import annotations

import asyncio
import json

import websockets

from config import MARKET_REFRESH_SECS, POLYMARKET_WS, log
from gamma import fetch_btc_5m_market, get_up_down_tokens


class PMState:
    def __init__(self) -> None:
        self.condition_id: str = ""
        self.question: str     = ""
        self.token_id_up: str   = ""
        self.token_id_down: str = ""
        self.up_bid: float   = 0.5
        self.up_ask: float   = 0.5
        self.down_bid: float = 0.5
        self.down_ask: float = 0.5
        self.taker_fee: int  = 0
        self.ready: bool     = False


# Singleton shared with main.py
pm_state = PMState()


# ── Market parsing ────────────────────────────────────────────────────────────

def _apply_market(market: dict) -> list[str] | None:
    """Update pm_state metadata from a Gamma market dict. Returns token ID list or None."""
    up, down = get_up_down_tokens(market)
    if not up or not down:
        return None
    pm_state.condition_id  = market.get("conditionId") or market.get("condition_id", "")
    pm_state.question      = market.get("question", "")
    pm_state.token_id_up   = up["token_id"]
    pm_state.token_id_down = down["token_id"]
    pm_state.taker_fee     = int(market.get("takerBaseFee", 0))
    # Seed from REST prices until first book event arrives
    pm_state.up_bid = pm_state.up_ask = float(up.get("price", 0.5))
    pm_state.down_bid = pm_state.down_ask = float(down.get("price", 0.5))
    return [pm_state.token_id_up, pm_state.token_id_down]


# ── Book event handler ────────────────────────────────────────────────────────

def _handle_book(msg: dict) -> None:
    asset_id = msg.get("asset_id", "")
    bids     = msg.get("bids", [])
    asks     = msg.get("asks", [])

    best_bid = max((float(b["price"]) for b in bids), default=0.0)
    best_ask = min((float(a["price"]) for a in asks), default=1.0)

    if asset_id == pm_state.token_id_up:
        if 0 < best_bid: pm_state.up_bid = best_bid
        if best_ask < 1: pm_state.up_ask = best_ask
        pm_state.ready = True
    elif asset_id == pm_state.token_id_down:
        if 0 < best_bid: pm_state.down_bid = best_bid
        if best_ask < 1: pm_state.down_ask = best_ask
        pm_state.ready = True


# ── Main WebSocket loop ───────────────────────────────────────────────────────

async def run_pm_ws() -> None:
    backoff = 1
    while True:
        try:
            market = fetch_btc_5m_market()
            if not market:
                log.warning("No active BTC 5m market — retry in 30s")
                await asyncio.sleep(30)
                continue

            token_ids = _apply_market(market)
            if not token_ids:
                log.warning("Could not parse market tokens — retry in 30s")
                await asyncio.sleep(30)
                continue

            log.info("Connecting to Polymarket WS  market=%s", pm_state.question[:70])
            async with websockets.connect(POLYMARKET_WS, ping_interval=20, ping_timeout=30) as ws:
                await ws.send(json.dumps({"type": "market", "assets_ids": token_ids}))
                log.info("Polymarket WS connected")
                backoff = 1

                last_refresh = asyncio.get_event_loop().time()

                while True:
                    # Wait for a message, but time out after MARKET_REFRESH_SECS
                    # so market refresh fires even when the WS goes silent (e.g. after expiry)
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=MARKET_REFRESH_SECS)
                        if raw and raw.strip():
                            try:
                                msgs = json.loads(raw)
                                if not isinstance(msgs, list):
                                    msgs = [msgs]
                                for msg in msgs:
                                    if msg.get("event_type") == "book":
                                        _handle_book(msg)
                            except Exception as exc:
                                log.error("PM WS processing error: %s", exc)
                    except asyncio.TimeoutError:
                        pass  # no message — fall through to refresh

                    # Refresh market subscription periodically
                    now = asyncio.get_event_loop().time()
                    if now - last_refresh >= MARKET_REFRESH_SECS:
                        last_refresh = now
                        try:
                            fresh = fetch_btc_5m_market()
                            if fresh:
                                new_ids = _apply_market(fresh)
                                if new_ids and set(new_ids) != set(token_ids):
                                    await ws.send(json.dumps({"type": "market", "assets_ids": new_ids}))
                                    token_ids = new_ids
                                    log.info("PM WS: subscribed to new market  %s", pm_state.question[:70])
                        except Exception as exc:
                            log.warning("PM WS market refresh error: %s", exc)

        except (websockets.ConnectionClosed, ConnectionError, OSError) as exc:
            log.warning("PM WS disconnected: %s — reconnect in %ds", exc, backoff)
        except Exception as exc:
            log.exception("PM WS unexpected error: %s — reconnect in %ds", exc, backoff)

        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, 60)
