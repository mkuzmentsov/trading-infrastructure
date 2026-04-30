"""
BTC state for the Polymarket 15m bot.

The 15m up/down market resolves on Binance data, so this bot drives btc_state
directly from the Binance aggTrade stream (the same stream that binance_ws.py
also reads). No Polymarket RTDS / Chainlink subscription is opened.

The exposed `btc_state` interface (current_price, bar_open, ret_since,
sigma_5m, set_market_window, apply_price_tick, apply_price_points) matches
the original Chainlink-fed module so the rest of main.py works unchanged.
"""
from __future__ import annotations

import asyncio
import json
import math
import time
from collections import deque

import websockets

from config import BINANCE_WS_URL, log


class BTCState:
    def __init__(self) -> None:
        self.bar_open: float = 0.0
        self.current_price: float = 0.0
        self.ready: bool = False
        self.last_round_id: int = 0
        self.last_updated_at: int = 0
        self.last_price_poll_at: float = 0.0
        self.market_start_ts: int = 0
        self.market_end_ts: int = 0
        self.price_updates: int = 0
        self.price_source: str = "binance_aggtrade"
        # RTDS-shaped fields kept for diagnostic compatibility with main.py logging.
        self.rtds_session_id: int = 0
        self.rtds_connect_count: int = 0
        self.last_rtds_connect_at: float = 0.0
        self.last_rtds_disconnect_at: float = 0.0
        self.last_rtds_message_at: float = 0.0
        self.last_rtds_message_kind: str = "binance_only"
        self.last_rtds_close_reason: str = ""
        self.last_rtds_error: str = ""

        self._prices: deque[tuple[int, float]] = deque(maxlen=2000)
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

    def _bar_open_from_history(self, start_ts: int) -> float:
        if start_ts <= 0:
            return 0.0
        for ts, log_price in self._prices:
            if ts >= start_ts:
                return math.exp(log_price)
        return 0.0

    async def set_market_window(self, start_ts: int, end_ts: int) -> None:
        async with self._lock:
            if start_ts == self.market_start_ts and end_ts == self.market_end_ts:
                return
            self.market_start_ts = start_ts
            self.market_end_ts = end_ts
            self.bar_open = self._bar_open_from_history(start_ts)
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


async def _run_binance_btc_state() -> None:
    """Fill btc_state from the Binance aggTrade stream.

    Runs alongside binance_ws.run_binance_ws(), which fills binance_state.
    Both consumers open independent connections to the same public endpoint.
    """
    if not BINANCE_WS_URL:
        log.warning("Binance WS URL is empty — btc_state will stay unready")
        return

    backoff = 1
    last_heartbeat = 0.0

    while True:
        try:
            btc_state.rtds_connect_count += 1
            btc_state.rtds_session_id += 1
            btc_state.last_rtds_connect_at = time.time()
            btc_state.last_rtds_close_reason = ""
            btc_state.last_rtds_error = ""
            log.info(
                "Binance btc_state WS connecting  session=%d url=%s",
                btc_state.rtds_session_id,
                BINANCE_WS_URL,
            )
            async with websockets.connect(
                BINANCE_WS_URL, ping_interval=20, ping_timeout=30
            ) as ws:
                log.info("Binance btc_state WS connected  session=%d", btc_state.rtds_session_id)
                backoff = 1

                async for raw in ws:
                    btc_state.last_rtds_message_at = time.time()
                    if not raw:
                        continue
                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        continue

                    price_str = msg.get("p")
                    trade_ts = msg.get("T")  # ms
                    if price_str and trade_ts:
                        try:
                            price = float(price_str)
                            updated_at_ms = int(trade_ts)
                        except (TypeError, ValueError):
                            continue
                        await btc_state.apply_price_tick(price, updated_at_ms)
                        btc_state.last_rtds_message_kind = "aggTrade"

                    now = time.time()
                    if now - last_heartbeat >= 30:
                        last_heartbeat = now
                        log.info(
                            "btc_state heartbeat  session=%d price=%.2f updates=%d ready=%s",
                            btc_state.rtds_session_id,
                            btc_state.current_price,
                            btc_state.price_updates,
                            btc_state.ready,
                        )

        except (websockets.ConnectionClosed, ConnectionError, OSError) as exc:
            btc_state.last_rtds_error = str(exc)
            btc_state.last_rtds_disconnect_at = time.time()
            log.warning("Binance btc_state WS disconnected: %s — reconnect in %ds", exc, backoff)
        except Exception as exc:
            btc_state.last_rtds_error = str(exc)
            btc_state.last_rtds_disconnect_at = time.time()
            log.exception("Binance btc_state WS error: %s — reconnect in %ds", exc, backoff)

        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, 60)


async def run_btc_ws() -> None:
    await _run_binance_btc_state()
