"""
Polymarket CLOB WebSocket — real-time UP/DOWN book state.

On startup and whenever the current 5-minute market rolls over, fetches
the active BTC UP/DOWN market from the Gamma REST API and subscribes to
its token IDs.

Book events update pm_state.up_bid / up_ask / down_bid / down_ask in place.
A market is considered ready only after both sides have received live book data.
"""
from __future__ import annotations

import asyncio
import json
import time
from collections import deque

import websockets

from btc_ws import btc_state
from config import (
    POLYMARKET_WS,
    WS_HEARTBEAT_SECS,
    log,
)
from gamma import (
    fetch_btc_5m_market,
    fetch_market_for_window,
    get_market_window,
    get_up_down_tokens,
)


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
        self.up_bid_size: float = 0.0
        self.up_ask_size: float = 0.0
        self.down_bid_size: float = 0.0
        self.down_ask_size: float = 0.0
        self.taker_fee: int = 0
        self.order_min_size: float = 5.0   # gamma orderMinSize (fallback 5)
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
        self.last_tick_size_change_at: float = 0.0
        # Trade prints (last_trade_price events). Each entry:
        # {"seq", "ts", "token_id", "price", "size", "side"}. seq is a
        # session-monotonic counter so consumers (paper fill engine) can keep
        # a cursor without index math on the bounded deque.
        self.recent_trades: "deque[dict]" = deque(maxlen=512)
        self.trade_seq: int = 0
        self.trade_events: int = 0
        self.last_trade_ts: float = 0.0

    def reset_live_state(self) -> None:
        self.ready = False
        self.up_live = False
        self.down_live = False
        self.up_bid = 0.0
        self.up_ask = 1.0
        self.down_bid = 0.0
        self.down_ask = 1.0
        self.up_bid_size = 0.0
        self.up_ask_size = 0.0
        self.down_bid_size = 0.0
        self.down_ask_size = 0.0
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
    try:
        pm_state.order_min_size = float(market.get("orderMinSize") or 5.0)
    except (TypeError, ValueError):
        pm_state.order_min_size = 5.0
    pm_state.market_start_ts = market_start_ts
    pm_state.market_end_ts = market_end_ts

    return [pm_state.token_id_up, pm_state.token_id_down]


# ── Next-bar pre-discovery (live maker latency path) ──────────────────────────
# main.py (live maker only) prefetches the NEXT bar's market at T−30s via the
# deterministic slug and caches it here; at the bar boundary the switch consumes
# the cache instead of making a blocking Gamma call. Paper mode never populates
# the cache and never enables external apply, so the paper path is unchanged.
_prefetched_market: dict = {"start_ts": 0, "market": None}
_external_apply_enabled: bool = False


def enable_external_market_apply() -> None:
    """Allow main.py (live roll hook) to apply markets to pm_state directly;
    run_pm_ws then resubscribes its WS to the new token ids in-loop."""
    global _external_apply_enabled
    _external_apply_enabled = True


def prefetch_next_market() -> bool:
    """Blocking (requests). Fetch + cache the NEXT bar's market. The next
    window starts exactly at the current market_end_ts (5m grid)."""
    next_start = pm_state.market_end_ts
    if next_start <= 0:
        return False
    if _prefetched_market["start_ts"] == next_start and _prefetched_market["market"]:
        return True
    market = fetch_market_for_window(next_start)
    if not market:
        return False
    _prefetched_market["start_ts"] = next_start
    _prefetched_market["market"] = market
    return True


def consume_prefetched_market() -> dict | None:
    """Pop the cached next market if it is valid for the current wall clock
    (its window has started and not yet ended). Returns None otherwise."""
    market = _prefetched_market["market"]
    start_ts = _prefetched_market["start_ts"]
    if not market:
        return None
    now = time.time()
    if now < start_ts - 1 or now >= start_ts + 300:
        _prefetched_market["start_ts"] = 0
        _prefetched_market["market"] = None
        return None
    _prefetched_market["start_ts"] = 0
    _prefetched_market["market"] = None
    return market


def apply_prefetched_market_now() -> bool:
    """Live roll hook: apply the cached next market to pm_state immediately
    at the bar boundary (zero Gamma calls). Returns True on success."""
    market = consume_prefetched_market()
    if not market:
        return False
    return _apply_market(market) is not None


def _coerce_float(x: object, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default


def _compute_book_top(
    bids: list[dict],
    asks: list[dict],
) -> tuple[float, float, float, float]:
    best_bid = 0.0
    best_bid_size = 0.0
    best_ask = 1.0
    best_ask_size = 0.0

    for b in bids:
        price = _coerce_float(b.get("price"), 0.0)
        size = max(0.0, _coerce_float(b.get("size"), 0.0))
        if price > best_bid:
            best_bid = price
            best_bid_size = size
        elif price == best_bid and best_bid > 0:
            best_bid_size += size

    for a in asks:
        price = _coerce_float(a.get("price"), 1.0)
        size = max(0.0, _coerce_float(a.get("size"), 0.0))
        if 0 < price < best_ask:
            best_ask = price
            best_ask_size = size
        elif price == best_ask and 0 < best_ask < 1:
            best_ask_size += size

    return best_bid, best_bid_size, best_ask, best_ask_size


def _apply_top_of_book(
    asset_id: str,
    best_bid: float,
    best_bid_size: float,
    best_ask: float,
    best_ask_size: float,
    event_type: str,
) -> None:
    now = time.time()
    has_bid = best_bid > 0
    has_ask = 0 < best_ask <= 1
    if has_bid and has_ask and best_bid > best_ask:
        log.warning(
            "PM WS crossed book  asset=%s bid=%.3f ask=%.3f — clamping",
            asset_id[:16],
            best_bid,
            best_ask,
        )
        midpoint = round((best_bid + best_ask) / 2, 3)
        best_bid = midpoint
        best_ask = midpoint
        has_bid = True
        has_ask = True

    quote_seen = has_bid or has_ask
    book_live = has_bid and has_ask

    if asset_id == pm_state.token_id_up:
        pm_state.up_bid = best_bid if has_bid else 0.0
        pm_state.up_ask = best_ask if has_ask else 1.0
        pm_state.up_bid_size = best_bid_size if has_bid else 0.0
        pm_state.up_ask_size = best_ask_size if has_ask else 0.0
        pm_state.up_live = book_live
        if quote_seen:
            pm_state.last_up_book_ts = now
    elif asset_id == pm_state.token_id_down:
        pm_state.down_bid = best_bid if has_bid else 0.0
        pm_state.down_ask = best_ask if has_ask else 1.0
        pm_state.down_bid_size = best_bid_size if has_bid else 0.0
        pm_state.down_ask_size = best_ask_size if has_ask else 0.0
        pm_state.down_live = book_live
        if quote_seen:
            pm_state.last_down_book_ts = now
    else:
        return

    pm_state.book_events += 1
    pm_state.last_ws_message_kind = f"{event_type}:{asset_id[:12]}"

    pm_state.ready = (
        pm_state.up_live
        and pm_state.down_live
        and pm_state.up_bid > 0
        and pm_state.down_bid > 0
        and 0 < pm_state.up_ask < 1
        and 0 < pm_state.down_ask < 1
    )


def _current_sizes_for_asset(asset_id: str) -> tuple[float, float]:
    if asset_id == pm_state.token_id_up:
        return pm_state.up_bid_size, pm_state.up_ask_size
    if asset_id == pm_state.token_id_down:
        return pm_state.down_bid_size, pm_state.down_ask_size
    return 0.0, 0.0


def _handle_book(msg: dict) -> None:
    asset_id = msg.get("asset_id", "")
    bids = msg.get("bids", [])
    asks = msg.get("asks", [])
    best_bid, best_bid_size, best_ask, best_ask_size = _compute_book_top(bids, asks)
    _apply_top_of_book(asset_id, best_bid, best_bid_size, best_ask, best_ask_size, "book")


def _handle_best_bid_ask(msg: dict) -> None:
    asset_id = msg.get("asset_id", "")
    best_bid = _coerce_float(msg.get("best_bid"), 0.0)
    best_ask = _coerce_float(msg.get("best_ask"), 1.0)
    # best_bid_ask does not include top-level size: keep last known sizes.
    cur_bid_size, cur_ask_size = _current_sizes_for_asset(asset_id)
    _apply_top_of_book(asset_id, best_bid, cur_bid_size, best_ask, cur_ask_size, "best_bid_ask")


def _handle_last_trade_price(msg: dict) -> None:
    """Trade print for one of our tokens. Polymarket's market channel emits
    last_trade_price with asset_id/price/size/side; the paper fill engine
    consumes these via pm_state.recent_trades."""
    asset_id = msg.get("asset_id", "")
    if asset_id not in (pm_state.token_id_up, pm_state.token_id_down):
        return
    price = _coerce_float(msg.get("price"), 0.0)
    if not (0 < price < 1):
        return
    size = max(0.0, _coerce_float(msg.get("size"), 0.0))
    side = (msg.get("side") or "").upper()
    now = time.time()
    pm_state.trade_seq += 1
    pm_state.trade_events += 1
    pm_state.last_trade_ts = now
    pm_state.recent_trades.append(
        {
            "seq": pm_state.trade_seq,
            "ts": now,
            "token_id": asset_id,
            "price": price,
            "size": size,
            "side": side,
        }
    )
    pm_state.last_ws_message_kind = f"last_trade_price:{asset_id[:12]}"


def _handle_price_change(msg: dict) -> None:
    changes = msg.get("price_changes", [])
    if not isinstance(changes, list):
        return
    for ch in changes:
        if not isinstance(ch, dict):
            continue
        asset_id = ch.get("asset_id", "")
        best_bid = _coerce_float(ch.get("best_bid"), 0.0)
        best_ask = _coerce_float(ch.get("best_ask"), 1.0)
        size = max(0.0, _coerce_float(ch.get("size"), 0.0))
        side = (ch.get("side") or "").upper()
        cur_bid_size, cur_ask_size = _current_sizes_for_asset(asset_id)
        bid_size = cur_bid_size
        ask_size = cur_ask_size
        if side == "BUY" and best_bid > 0:
            bid_size = size
        elif side == "SELL" and 0 < best_ask <= 1:
            ask_size = size
        _apply_top_of_book(asset_id, best_bid, bid_size, best_ask, ask_size, "price_change")


async def _ws_send_ping(ws) -> None:
    await ws.send("PING")


def refresh_pm_quotes_from_rest(reason: str = "") -> bool:
    market = fetch_btc_5m_market()
    if not market:
        return False

    token_ids = _apply_market(market)
    if not token_ids:
        return False

    log.info(
        "PM REST refresh%s  ready=%s  up=%.3f/%.3f  down=%.3f/%.3f",
        f" ({reason})" if reason else "",
        pm_state.ready,
        pm_state.up_bid,
        pm_state.up_ask,
        pm_state.down_bid,
        pm_state.down_ask,
    )
    return True


def _log_book_heartbeat(force: bool = False) -> None:
    now = time.time()
    if not force and now - pm_state.last_heartbeat_ts < WS_HEARTBEAT_SECS:
        return
    pm_state.last_heartbeat_ts = now
    up_age = now - pm_state.last_up_book_ts if pm_state.last_up_book_ts > 0 else -1
    down_age = now - pm_state.last_down_book_ts if pm_state.last_down_book_ts > 0 else -1
    log.info(
        "PM WS heartbeat  session=%d market=%s  ready=%s  events=%d  up=%.3f/%.3f x %.1f age=%.1fs  down=%.3f/%.3f x %.1f age=%.1fs msg_age=%.1fs",
        pm_state.ws_session_id,
        pm_state.question[:50],
        pm_state.ready,
        pm_state.book_events,
        pm_state.up_bid,
        pm_state.up_ask,
        pm_state.up_ask_size,
        up_age,
        pm_state.down_bid,
        pm_state.down_ask,
        pm_state.down_ask_size,
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
                await ws.send(json.dumps({"type": "market", "assets_ids": token_ids, "custom_feature_enabled": True}))
                log.info("Polymarket WS connected  session=%d", pm_state.ws_session_id)
                backoff = 1
                last_ping = asyncio.get_event_loop().time()

                while True:
                    now = asyncio.get_event_loop().time()
                    if now - last_ping >= 10:
                        await _ws_send_ping(ws)
                        last_ping = now
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                    except asyncio.TimeoutError:
                        raw = ""
                    pm_state.last_ws_message_at = time.time() if raw else pm_state.last_ws_message_at
                    if not raw or not raw.strip():
                        pm_state.last_ws_message_kind = "empty"
                        _log_book_heartbeat()
                    else:
                        stripped = raw.strip()
                        if stripped == "PONG":
                            pm_state.last_ws_message_kind = "pong"
                            _log_book_heartbeat()
                        elif stripped == "INVALID OPERATION":
                            pm_state.last_ws_message_kind = "invalid_operation"
                            log.warning("PM WS reported INVALID OPERATION — reconnecting  session=%d", pm_state.ws_session_id)
                            break
                        elif stripped[0] not in "[{":
                            pm_state.last_ws_message_kind = "control"
                            log.debug("PM WS control message: %s", stripped)
                            _log_book_heartbeat()
                        else:
                            log.debug("PM WS RAW  %s", raw.replace("\n", "\\n"))
                            try:
                                msgs = json.loads(raw)
                                if not isinstance(msgs, list):
                                    msgs = [msgs]
                                for msg in msgs:
                                    event_type = msg.get("event_type")
                                    if event_type == "book":
                                        _handle_book(msg)
                                    elif event_type == "price_change":
                                        _handle_price_change(msg)
                                    elif event_type == "best_bid_ask":
                                        _handle_best_bid_ask(msg)
                                    elif event_type == "last_trade_price":
                                        _handle_last_trade_price(msg)
                                    elif event_type == "tick_size_change":
                                        pm_state.last_tick_size_change_at = time.time()
                                        log.info(
                                            "PM WS tick_size_change  asset=%s old=%s new=%s",
                                            msg.get("asset_id", "")[:16],
                                            msg.get("old_tick_size"),
                                            msg.get("new_tick_size"),
                                        )
                                _log_book_heartbeat()
                            except Exception as exc:
                                snippet = raw[:200].replace("\n", "\\n")
                                log.error("PM WS processing error: %s  raw=%s", exc, snippet)

                    # Live maker only: main's roll hook applies the prefetched
                    # market directly to pm_state at the boundary — detect the
                    # externally-applied token ids and resubscribe in place.
                    if _external_apply_enabled:
                        current_ids = [pm_state.token_id_up, pm_state.token_id_down]
                        if all(current_ids) and set(current_ids) != set(token_ids):
                            try:
                                to_unsubscribe = [a for a in token_ids if a not in current_ids]
                                to_subscribe = [a for a in current_ids if a not in token_ids]
                                if to_unsubscribe:
                                    await ws.send(json.dumps({"assets_ids": to_unsubscribe, "operation": "unsubscribe"}))
                                if to_subscribe:
                                    await ws.send(
                                        json.dumps(
                                            {
                                                "assets_ids": to_subscribe,
                                                "operation": "subscribe",
                                                "custom_feature_enabled": True,
                                            }
                                        )
                                    )
                                token_ids = current_ids
                                log.info(
                                    "PM WS: resubscribed after external market apply  session=%d market=%s token_ids=%s",
                                    pm_state.ws_session_id,
                                    pm_state.question[:70],
                                    token_ids,
                                )
                            except Exception as exc:
                                log.warning("PM WS external-apply resubscribe error: %s", exc)

                    if pm_state.market_end_ts > 0 and time.time() >= pm_state.market_end_ts:
                        try:
                            # Prefetched cache first (live pre-discovery); the
                            # cache is never populated in paper mode, so paper
                            # takes the Gamma call exactly as before.
                            fresh = consume_prefetched_market() or fetch_btc_5m_market()
                            if fresh:
                                new_ids = _apply_market(fresh)
                                await btc_state.set_market_window(pm_state.market_start_ts, pm_state.market_end_ts)
                                if new_ids and set(new_ids) != set(token_ids):
                                    to_unsubscribe = [asset for asset in token_ids if asset not in new_ids]
                                    to_subscribe = [asset for asset in new_ids if asset not in token_ids]
                                    if to_unsubscribe:
                                        await ws.send(json.dumps({"assets_ids": to_unsubscribe, "operation": "unsubscribe"}))
                                    if to_subscribe:
                                        await ws.send(
                                            json.dumps(
                                                {
                                                    "assets_ids": to_subscribe,
                                                    "operation": "subscribe",
                                                    "custom_feature_enabled": True,
                                                }
                                            )
                                        )
                                    token_ids = new_ids
                                    log.info(
                                        "PM WS: switched market on boundary  session=%d market=%s token_ids=%s",
                                        pm_state.ws_session_id,
                                        pm_state.question[:70],
                                        token_ids,
                                    )
                        except Exception as exc:
                            log.warning("PM WS boundary market switch error: %s", exc)
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
