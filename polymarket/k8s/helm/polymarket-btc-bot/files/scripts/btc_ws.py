"""
BTC state for the Polymarket bot.

Price comes from Polymarket RTDS `crypto_prices_chainlink` for `btc/usd`.
Binance is kept only for order-book imbalance features.
"""
from __future__ import annotations

import asyncio
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
                    "filters": json.dumps({"symbol": POLYMARKET_RTDS_SYMBOL}),
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
            async with websockets.connect(POLYMARKET_RTDS_WS, ping_interval=20, ping_timeout=30) as ws:
                await ws.send(_build_rtds_subscribe())
                log.info(
                    "Polymarket RTDS connected  topic=crypto_prices_chainlink symbol=%s",
                    POLYMARKET_RTDS_SYMBOL,
                )
                backoff = 1
                async for raw in ws:
                    if not raw or not raw.strip():
                        continue
                    log.info("RTDS RAW  %s", raw[:500].replace("\n", "\\n"))
                    try:
                        msg = json.loads(raw)
                    except Exception as exc:
                        snippet = raw[:200].replace("\n", "\\n")
                        log.error("Polymarket RTDS JSON error: %s  raw=%s", exc, snippet)
                        continue
                    log.info("RTDS decoded  type=%s", type(msg).__name__)
                    if isinstance(msg, dict):
                        topic = msg.get("topic")
                    else:
                        topic = None
                    if topic and topic not in RTDS_TOPICS:
                        log.info("RTDS skipping message with topic=%s", topic)
                        continue
                    try:
                        points = _extract_rtds_points(msg)
                        log.info("RTDS extracted  points=%d", len(points))
                        if not points:
                            log.warning("RTDS message had no usable price points")
                            continue
                        log.info(
                            "RTDS sample  first_ts=%d first_price=%.2f last_ts=%d last_price=%.2f",
                            points[0][0],
                            points[0][1],
                            points[-1][0],
                            points[-1][1],
                        )
                        applied = await btc_state.apply_price_points(points)
                        log.info(
                            "RTDS state after apply  applied=%d current=%.2f open=%.2f last_ts=%d updates=%d ready=%s",
                            applied,
                            btc_state.current_price,
                            btc_state.bar_open,
                            btc_state.last_round_id,
                            btc_state.price_updates,
                            btc_state.ready,
                        )
                        if applied <= 0:
                            log.warning("RTDS extracted price points but none were applied")
                            continue
                        now = time.time()
                        if now - last_tick_log_at >= 30:
                            last_tick_log_at = now
                            log.info(
                                "RTDS applied  points=%d latest=%.2f ts=%d total_updates=%d ready=%s",
                                applied,
                                btc_state.current_price,
                                btc_state.last_round_id,
                                btc_state.price_updates,
                                btc_state.ready,
                            )
                    except Exception as exc:
                        log.error("Polymarket RTDS price processing error: %s", exc)
        except (websockets.ConnectionClosed, ConnectionError, OSError) as exc:
            log.warning("Polymarket RTDS disconnected: %s — reconnect in %ds", exc, backoff)
        except Exception as exc:
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
