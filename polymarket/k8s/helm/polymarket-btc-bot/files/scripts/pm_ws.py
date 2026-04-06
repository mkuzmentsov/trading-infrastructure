"""
Polymarket CLOB WebSocket — real-time UP/DOWN book state.

On startup and every MARKET_REFRESH_SECS, fetches the active BTC 5-min
UP/DOWN market from the Gamma REST API and subscribes to its token IDs.

Book events update pm_state.up_bid / up_ask / down_bid / down_ask in place.
A market is considered ready only after both sides have received live book data.
"""
from __future__ import annotations

import asyncio
import json
import time

import websockets

from btc_ws import btc_state
from config import MARKET_REFRESH_SECS, POLYMARKET_WS, WS_HEARTBEAT_SECS, log
from gamma import fetch_btc_5m_market, get_market_window, get_up_down_tokens


class PMState:
    def __init__(self) -> None:
        self.condition_id: str = ""
        self.question: str = ""
        self.token_id_up: str = ""
        self.token_id_down: str = ""
        self.up_bid: float = 0.5
        self.up_ask: float = 0.5
        self.down_bid: float = 0.5
        self.down_ask: float = 0.5
        self.taker_fee: int = 0
        self.market_start_ts: int = 0
        self.market_end_ts: int = 0
        self.ready: bool = False
        self.up_live: bool = False
        self.down_live: bool = False
        self.last_up_book_ts: float = 0.0
        self.last_down_book_ts: float = 0.0
        self.book_events: int = 0
        self.last_heartbeat_ts: float = 0.0
        self.ws_connect_count: int = 0
        self.ws_session_id: int = 0
        self.last_ws_connect_at: float = 0.0
        self.last_ws_message_at: float = 0.0
        self.last_ws_message_kind: str = "never"

    def reset_live_state(self) -> None:
        self.ready = False
        self.up_live = False
        self.down_live = False
        self.last_up_book_ts = 0.0
        self.last_down_book_ts = 0.0
        self.book_events = 0
        self.last_heartbeat_ts = 0.0


pm_state = PMState()


def _apply_market(market: dict) -> list[str] | None:
    """Update pm_state metadata from a Gamma market dict."""
    up, down = get_up_down_tokens(market)
    if not up or not down:
        log.warning("PM market parse failed: missing up/down tokens")
        return None

    new_condition = market.get("conditionId") or market.get("condition_id", "")
    market_start_ts, market_end_ts = get_market_window(market)
    if (
        new_condition != pm_state.condition_id
        or market_start_ts != pm_state.market_start_ts
        or market_end_ts != pm_state.market_end_ts
    ):
        log.info(
            "PM market applied  old_condition=%s new_condition=%s window=%s->%s question=%s",
            pm_state.condition_id[:16] if pm_state.condition_id else "-",
            new_condition[:16] if new_condition else "-",
            market_start_ts,
            market_end_ts,
            market.get("question", "")[:90],
        )
    if new_condition != pm_state.condition_id:
        pm_state.reset_live_state()

    pm_state.condition_id = new_condition
    pm_state.question = market.get("question", "")
    pm_state.token_id_up = up["token_id"]
    pm_state.token_id_down = down["token_id"]
    pm_state.taker_fee = int(market.get("takerBaseFee", 0))
    pm_state.market_start_ts = market_start_ts
    pm_state.market_end_ts = market_end_ts

    # Seed prices from REST, but do not mark the book as live until WS updates arrive.
    pm_state.up_bid = pm_state.up_ask = float(up.get("price", 0.5))
    pm_state.down_bid = pm_state.down_ask = float(down.get("price", 0.5))
    return [pm_state.token_id_up, pm_state.token_id_down]


def _handle_book(msg: dict) -> None:
    asset_id = msg.get("asset_id", "")
    bids = msg.get("bids", [])
    asks = msg.get("asks", [])

    best_bid = max((float(b["price"]) for b in bids), default=0.0)
    best_ask = min((float(a["price"]) for a in asks), default=1.0)
    if best_bid > 0 and best_ask < 1 and best_bid > best_ask:
        log.warning(
            "PM WS crossed book  asset=%s bid=%.3f ask=%.3f — clamping",
            asset_id[:16],
            best_bid,
            best_ask,
        )
        midpoint = round((best_bid + best_ask) / 2, 3)
        best_bid = midpoint
        best_ask = midpoint

    if asset_id == pm_state.token_id_up:
        if 0 < best_bid:
            pm_state.up_bid = best_bid
        if 0 < best_ask < 1:
            pm_state.up_ask = best_ask
        pm_state.up_live = True
        pm_state.last_up_book_ts = time.time()
    elif asset_id == pm_state.token_id_down:
        if 0 < best_bid:
            pm_state.down_bid = best_bid
        if 0 < best_ask < 1:
            pm_state.down_ask = best_ask
        pm_state.down_live = True
        pm_state.last_down_book_ts = time.time()

    pm_state.book_events += 1

    pm_state.ready = (
        pm_state.up_live
        and pm_state.down_live
        and pm_state.up_bid > 0
        and pm_state.down_bid > 0
        and 0 < pm_state.up_ask < 1
        and 0 < pm_state.down_ask < 1
    )


def _log_book_heartbeat(force: bool = False) -> None:
    now = time.time()
    if not force and now - pm_state.last_heartbeat_ts < WS_HEARTBEAT_SECS:
        return
    pm_state.last_heartbeat_ts = now
    up_age = now - pm_state.last_up_book_ts if pm_state.last_up_book_ts > 0 else -1
    down_age = now - pm_state.last_down_book_ts if pm_state.last_down_book_ts > 0 else -1
    log.info(
        "PM WS heartbeat  session=%d market=%s  ready=%s  events=%d  up=%.3f/%.3f age=%.1fs  down=%.3f/%.3f age=%.1fs msg_age=%.1fs",
        pm_state.ws_session_id,
        pm_state.question[:50],
        pm_state.ready,
        pm_state.book_events,
        pm_state.up_bid,
        pm_state.up_ask,
        up_age,
        pm_state.down_bid,
        pm_state.down_ask,
        down_age,
        now - pm_state.last_ws_message_at if pm_state.last_ws_message_at > 0 else -1,
    )


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
            await btc_state.set_market_window(pm_state.market_start_ts, pm_state.market_end_ts)

            log.info("Connecting to Polymarket WS  market=%s", pm_state.question[:70])
            async with websockets.connect(POLYMARKET_WS, ping_interval=20, ping_timeout=30) as ws:
                pm_state.ws_session_id += 1
                pm_state.ws_connect_count += 1
                pm_state.last_ws_connect_at = time.time()
                log.info(
                    "PM WS subscribe  session=%d token_ids=%s",
                    pm_state.ws_session_id,
                    token_ids,
                )
                await ws.send(json.dumps({"type": "market", "assets_ids": token_ids}))
                log.info("Polymarket WS connected  session=%d", pm_state.ws_session_id)
                backoff = 1

                last_refresh = asyncio.get_event_loop().time()

                async for raw in ws:
                    pm_state.last_ws_message_at = time.time()
                    if not raw or not raw.strip():
                        pm_state.last_ws_message_kind = "empty"
                        _log_book_heartbeat()
                        continue
                    log.debug("PM WS RAW  %s", raw[:500].replace("\n", "\\n"))
                    stripped = raw.strip()
                    if stripped == "INVALID OPERATION":
                        pm_state.last_ws_message_kind = "invalid_operation"
                        log.warning("PM WS reported INVALID OPERATION — reconnecting  session=%d", pm_state.ws_session_id)
                        break
                    if stripped[0] not in "[{":
                        pm_state.last_ws_message_kind = "control"
                        log.info("PM WS control message: %s", stripped[:120])
                        _log_book_heartbeat()
                        continue
                    try:
                        msgs = json.loads(raw)
                        if not isinstance(msgs, list):
                            msgs = [msgs]
                        for msg in msgs:
                            if msg.get("event_type") == "book":
                                _handle_book(msg)
                                pm_state.last_ws_message_kind = f"book:{msg.get('asset_id', '')[:12]}"
                        _log_book_heartbeat()
                    except Exception as exc:
                        snippet = raw[:200].replace("\n", "\\n")
                        log.error("PM WS processing error: %s  raw=%s", exc, snippet)

                    now = asyncio.get_event_loop().time()
                    if now - last_refresh >= MARKET_REFRESH_SECS:
                        last_refresh = now
                        try:
                            fresh = fetch_btc_5m_market()
                            if fresh:
                                new_ids = _apply_market(fresh)
                                await btc_state.set_market_window(pm_state.market_start_ts, pm_state.market_end_ts)
                                if new_ids and set(new_ids) != set(token_ids):
                                    await ws.send(json.dumps({"type": "market", "assets_ids": new_ids}))
                                    token_ids = new_ids
                                    log.info(
                                        "PM WS: subscribed to new market  session=%d market=%s token_ids=%s",
                                        pm_state.ws_session_id,
                                        pm_state.question[:70],
                                        token_ids,
                                    )
                        except Exception as exc:
                            log.warning("PM WS market refresh error: %s", exc)
                log.warning(
                    "PM WS loop ended  session=%d close_code=%s close_reason=%s last_msg_kind=%s",
                    pm_state.ws_session_id,
                    getattr(ws, "close_code", None),
                    getattr(ws, "close_reason", None),
                    pm_state.last_ws_message_kind,
                )

        except (websockets.ConnectionClosed, ConnectionError, OSError) as exc:
            log.warning("PM WS disconnected: %s — reconnect in %ds", exc, backoff)
        except Exception as exc:
            log.exception("PM WS unexpected error: %s — reconnect in %ds", exc, backoff)

        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, 60)
