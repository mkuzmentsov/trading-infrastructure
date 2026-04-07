"""
BTC state for the Polymarket bot.

Price comes from Polymarket RTDS `crypto_prices_chainlink` for `btc/usd`.
Binance is kept only for order-book imbalance features.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import math
import time
from collections import deque
from typing import Any

import websockets

from config import BINANCE_WS, POLYMARKET_RTDS_SYMBOL, POLYMARKET_RTDS_WS, log

RTDS_TOPICS = {"crypto_prices_chainlink", "crypto_prices"}


class BTCState:
    def __init__(self) -> None:
        self.bar_open: float = 0.0
        self.current_price: float = 0.0
        self.bid_vol_top: float = 0.0
        self.ask_vol_top: float = 0.0
        self.ready: bool = False
        self.last_round_id: int = 0
        self.last_updated_at: int = 0
        self.last_price_poll_at: float = 0.0
        self.market_start_ts: int = 0
        self.market_end_ts: int = 0
        self.last_depth_update_ts: float = 0.0
        self.depth_updates: int = 0
        self.price_updates: int = 0
        self.price_source: str = "polymarket_rtds_chainlink"
        self.rtds_session_id: int = 0
        self.rtds_connect_count: int = 0
        self.last_rtds_connect_at: float = 0.0
        self.last_rtds_disconnect_at: float = 0.0
        self.last_rtds_message_at: float = 0.0
        self.last_rtds_message_kind: str = "never"
        self.last_rtds_close_reason: str = ""
        self.last_rtds_error: str = ""

        self._prices: deque[tuple[int, float]] = deque(maxlen=600)
        self._lock = asyncio.Lock()

    def _record(self, ts: int, price: float) -> None:
        if price <= 0:
            return
        self.current_price = price
        if self._prices and ts < self._prices[-1][0]:
            return
        if self._prices and ts == self._prices[-1][0]:
            self._prices[-1] = (ts, math.log(price))
            return
        self._prices.append((ts, math.log(price)))

    def ret_since(self, seconds: int) -> float:
        if len(self._prices) < 2:
            return 0.0
        now_ts, now_lp = self._prices[-1]
        cutoff = now_ts - seconds
        for ts, lp in self._prices:
            if ts >= cutoff:
                return now_lp - lp
        return now_lp - self._prices[0][1]

    def sigma_5m(self) -> float:
        if len(self._prices) < 5:
            return 0.0025
        log_prices = [lp for _, lp in self._prices]
        rets = [log_prices[i] - log_prices[i - 1] for i in range(1, len(log_prices))]
        if len(rets) < 2:
            return 0.0025
        mean = sum(rets) / len(rets)
        var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
        horizon = max(1.0, min(300.0, float(len(rets))))
        return math.sqrt(var) * math.sqrt(horizon)

    def _refresh_ready(self) -> None:
        self.ready = (
            self.bar_open > 0
            and self.current_price > 0
            and self.last_updated_at > 0
            and self.market_start_ts > 0
            and self.market_end_ts > self.market_start_ts
        )

    async def set_market_window(self, start_ts: int, end_ts: int) -> None:
        async with self._lock:
            if start_ts == self.market_start_ts and end_ts == self.market_end_ts:
                return
            self.market_start_ts = start_ts
            self.market_end_ts = end_ts
            self.bar_open = self.current_price if self.current_price > 0 else 0.0
            self._refresh_ready()

    async def apply_price_tick(self, price: float, updated_at_ms: int) -> None:
        updated_at = max(0, updated_at_ms // 1000)
        async with self._lock:
            if price <= 0 or updated_at <= 0:
                return
            self.current_price = price
            self.last_updated_at = updated_at
            self.last_round_id = updated_at_ms
            self.last_price_poll_at = time.time()
            self.price_updates += 1
            self._record(updated_at, price)
            if self.market_start_ts > 0 and self.bar_open <= 0 and updated_at >= self.market_start_ts:
                self.bar_open = price
            self._refresh_ready()

    async def apply_price_points(self, points: list[tuple[int, float]]) -> int:
        applied = 0
        async with self._lock:
            for updated_at_ms, price in points:
                updated_at = max(0, updated_at_ms // 1000)
                if price <= 0 or updated_at <= 0:
                    continue
                self.current_price = price
                self.last_updated_at = updated_at
                self.last_round_id = updated_at_ms
                self.last_price_poll_at = time.time()
                self.price_updates += 1
                self._record(updated_at, price)
                if self.market_start_ts > 0 and self.bar_open <= 0 and updated_at >= self.market_start_ts:
                    self.bar_open = price
                applied += 1
            self._refresh_ready()
        return applied


btc_state = BTCState()


def _build_rtds_subscribe() -> str:
    return json.dumps(
        {
            "action": "subscribe",
            "subscriptions": [
                {
                    "topic": "crypto_prices_chainlink",
                    "type": "*",
                    "filters": json.dumps({"symbol": POLYMARKET_RTDS_SYMBOL}, separators=(",", ":")),
                }
            ],
        }
    )


def _coerce_payload(payload: Any) -> dict:
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, str):
        try:
            decoded = json.loads(payload)
            if isinstance(decoded, dict):
                return decoded
        except Exception:
            return {}
    return {}


def _extract_rtds_points(msg: Any) -> list[tuple[int, float]]:
    if isinstance(msg, list):
        points: list[tuple[int, float]] = []
        for item in msg:
            points.extend(_extract_rtds_points(item))
        return points
    if not isinstance(msg, dict):
        return []

    payload = _coerce_payload(msg.get("payload") or {})
    points: list[tuple[int, float]] = []

    data = payload.get("data")
    if data is None and isinstance(msg.get("data"), list):
        data = msg.get("data")
    if isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            try:
                ts = int(item.get("timestamp") or 0)
                price = float(item.get("value") or 0.0)
            except (TypeError, ValueError):
                continue
            if ts > 0 and price > 0:
                points.append((ts, price))
        if points:
            return points

    try:
        price = float(payload.get("value") or 0.0)
        updated_at_ms = int(payload.get("timestamp") or msg.get("timestamp") or 0)
    except (TypeError, ValueError):
        return []
    if updated_at_ms > 0 and price > 0:
        return [(updated_at_ms, price)]
    return []


async def _run_polymarket_rtds() -> None:
    backoff = 1
    last_tick_log_at = 0.0
    while True:
        try:
            next_session_id = btc_state.rtds_session_id + 1
            log.info(
                "RTDS connect attempt  session=%d url=%s backoff=%ds symbol=%s",
                next_session_id,
                POLYMARKET_RTDS_WS,
                backoff,
                POLYMARKET_RTDS_SYMBOL,
            )
            async with websockets.connect(POLYMARKET_RTDS_WS, ping_interval=None, ping_timeout=None) as ws:
                subscribe_payload = _build_rtds_subscribe()
                btc_state.rtds_session_id = next_session_id
                btc_state.rtds_connect_count += 1
                btc_state.last_rtds_connect_at = time.time()
                btc_state.last_rtds_close_reason = ""
                btc_state.last_rtds_error = ""
                log.info(
                    "RTDS subscribe  session=%d payload=%s",
                    btc_state.rtds_session_id,
                    subscribe_payload,
                )
                await ws.send(subscribe_payload)
                log.info(
                    "Polymarket RTDS connected  session=%d topic=crypto_prices_chainlink symbol=%s",
                    btc_state.rtds_session_id,
                    POLYMARKET_RTDS_SYMBOL,
                )
                backoff = 1
                try:
                    async for raw in ws:
                        btc_state.last_rtds_message_at = time.time()
                        if not raw or not raw.strip():
                            btc_state.last_rtds_message_kind = "empty"
                            continue
                        if raw.strip() == "PONG":
                            btc_state.last_rtds_message_kind = "pong"
                            log.info("RTDS PONG  session=%d", btc_state.rtds_session_id)
                            continue
                        btc_state.last_rtds_message_kind = "raw"
                        log.info(
                            "RTDS RAW  session=%d len=%d body=%s",
                            btc_state.rtds_session_id,
                            len(raw),
                            raw[:500].replace("\n", "\\n"),
                        )
                        try:
                            msg = json.loads(raw)
                        except Exception as exc:
                            snippet = raw[:200].replace("\n", "\\n")
                            btc_state.last_rtds_error = f"json:{exc}"
                            log.error("Polymarket RTDS JSON error: %s  raw=%s", exc, snippet)
                            continue
                        if isinstance(msg, dict):
                            topic = msg.get("topic")
                            event = msg.get("event")
                        else:
                            topic = None
                            event = None
                        if topic or event:
                            btc_state.last_rtds_message_kind = f"topic={topic or '-'} event={event or '-'}"
                        if topic and topic not in RTDS_TOPICS:
                            log.info(
                                "RTDS skipping message  session=%d topic=%s event=%s",
                                btc_state.rtds_session_id,
                                topic,
                                event,
                            )
                            continue
                        try:
                            points = _extract_rtds_points(msg)
                            if not points:
                                log.warning(
                                    "RTDS message had no usable price points  session=%d topic=%s event=%s keys=%s",
                                    btc_state.rtds_session_id,
                                    topic,
                                    event,
                                    sorted(msg.keys()) if isinstance(msg, dict) else [],
                                )
                                continue
                            applied = await btc_state.apply_price_points(points)
                            if applied <= 0:
                                log.warning(
                                    "RTDS extracted price points but none were applied  session=%d",
                                    btc_state.rtds_session_id,
                                )
                                continue
                            now = time.time()
                            if now - last_tick_log_at >= 30:
                                last_tick_log_at = now
                                log.info(
                                    "RTDS heartbeat  session=%d latest=%.2f ts=%d total_updates=%d ready=%s",
                                    btc_state.rtds_session_id,
                                    btc_state.current_price,
                                    btc_state.last_round_id,
                                    btc_state.price_updates,
                                    btc_state.ready,
                                )
                        except Exception as exc:
                            btc_state.last_rtds_error = f"process:{exc}"
                            log.error("Polymarket RTDS price processing error: %s", exc)
                    btc_state.last_rtds_close_reason = "async_for_completed"
                    log.warning(
                        "RTDS message loop ended  session=%d close_code=%s close_reason=%s",
                        btc_state.rtds_session_id,
                        getattr(ws, "close_code", None),
                        getattr(ws, "close_reason", None),
                    )
                finally:
                    btc_state.last_rtds_disconnect_at = time.time()
                    log.info(
                        "RTDS session cleanup  session=%d close_code=%s close_reason=%s local_reason=%s msg_age=%.1fs last_msg_kind=%s",
                        btc_state.rtds_session_id,
                        getattr(ws, "close_code", None),
                        getattr(ws, "close_reason", None),
                        btc_state.last_rtds_close_reason or "unknown",
                        (
                            time.time() - btc_state.last_rtds_message_at
                            if btc_state.last_rtds_message_at > 0
                            else -1.0
                        ),
                        btc_state.last_rtds_message_kind,
                    )
                    log.info(
                        "RTDS scheduling reconnect  next_backoff=%ds session=%d last_error=%s",
                        backoff,
                        btc_state.rtds_session_id,
                        btc_state.last_rtds_error or "-",
                    )
        except (websockets.ConnectionClosed, ConnectionError, OSError) as exc:
            btc_state.last_rtds_error = str(exc)
            log.warning("Polymarket RTDS disconnected: %s — reconnect in %ds", exc, backoff)
        except Exception as exc:
            btc_state.last_rtds_error = str(exc)
            log.exception("Polymarket RTDS unexpected error: %s — reconnect in %ds", exc, backoff)
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, 60)


async def _process_depth(raw: str) -> None:
    msg = json.loads(raw)
    data = msg.get("data", {})
    bids = data.get("bids", [])
    asks = data.get("asks", [])
    if bids:
        btc_state.bid_vol_top = sum(float(b[1]) for b in bids[:5])
    if asks:
        btc_state.ask_vol_top = sum(float(a[1]) for a in asks[:5])
    btc_state.last_depth_update_ts = time.time()
    btc_state.depth_updates += 1


async def _run_binance_depth_ws() -> None:
    backoff = 1
    while True:
        try:
            async with websockets.connect(BINANCE_WS, ping_interval=20, ping_timeout=30) as ws:
                log.info("Binance depth WebSocket connected")
                backoff = 1
                async for raw in ws:
                    log.debug("Binance RAW  %s", raw[:300].replace("\n", "\\n"))
                    try:
                        await _process_depth(raw)
                    except Exception as exc:
                        log.error("Binance depth WS processing error: %s", exc)
        except (websockets.ConnectionClosed, ConnectionError, OSError) as exc:
            log.warning("Binance depth WS disconnected: %s — reconnect in %ds", exc, backoff)
        except Exception as exc:
            log.exception("Binance depth WS unexpected error: %s — reconnect in %ds", exc, backoff)
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, 60)


async def run_btc_ws() -> None:
    await asyncio.gather(
        _run_polymarket_rtds(),
        _run_binance_depth_ws(),
    )
