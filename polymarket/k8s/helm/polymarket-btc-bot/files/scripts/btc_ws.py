"""
Binance WebSocket — real-time BTC state.

Streams (combined):
  btcusdt@kline_5m      → bar open + current price (updated on every trade)
  btcusdt@depth20@100ms → top-of-book volumes for imbalance

Maintains a 1-second-sampled price history for ret_30s / ret_60s / sigma_5m.
"""
from __future__ import annotations

import asyncio
import json
import math
from collections import deque
from datetime import datetime, timezone

import websockets

from config import log

_WS_URL = (
    "wss://stream.binance.com:9443/stream"
    "?streams=btcusdt@kline_5m/btcusdt@depth20@100ms"
)


class BTCState:
    def __init__(self) -> None:
        self.bar_open: float = 0.0
        self.current_price: float = 0.0
        self.bid_vol_top: float = 0.0   # sum of top-5 bid levels (BTC)
        self.ask_vol_top: float = 0.0
        self.ready: bool = False

        # 1-sample-per-second price log buffer (up to 10 minutes)
        self._prices: deque[tuple[int, float]] = deque(maxlen=600)
        self._last_sec: int = 0

    # ── Price history ─────────────────────────────────────────────────────────

    def _record(self, price: float) -> None:
        now = int(datetime.now(tz=timezone.utc).timestamp())
        self.current_price = price
        if now > self._last_sec:
            self._last_sec = now
            self._prices.append((now, math.log(price)))

    def ret_since(self, seconds: int) -> float:
        """Log return over the last `seconds` seconds."""
        if len(self._prices) < 2:
            return 0.0
        now_ts, now_lp = self._prices[-1]
        cutoff = now_ts - seconds
        for ts, lp in self._prices:
            if ts >= cutoff:
                return now_lp - lp
        return now_lp - self._prices[0][1]

    def sigma_5m(self) -> float:
        """
        Estimated 5-minute log-return std dev.
        Computed from recent 1s returns then scaled by sqrt(300).
        Falls back to 0.0025 (~0.25% per bar) when insufficient data.
        """
        if len(self._prices) < 10:
            return 0.0025
        log_prices = [lp for _, lp in self._prices]
        rets = [log_prices[i] - log_prices[i - 1] for i in range(1, len(log_prices))]
        if len(rets) < 2:
            return 0.0025
        mean = sum(rets) / len(rets)
        var  = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
        return math.sqrt(var) * math.sqrt(300)


# Singleton shared with main.py
btc_state = BTCState()


# ── WebSocket processing ──────────────────────────────────────────────────────

async def _process(raw: str) -> None:
    msg    = json.loads(raw)
    stream = msg.get("stream", "")
    data   = msg.get("data", {})

    if "@kline_5m" in stream:
        k          = data.get("k", {})
        bar_open   = float(k.get("o", 0))
        close      = float(k.get("c", 0))
        if bar_open > 0:
            btc_state.bar_open = bar_open
        if close > 0:
            btc_state._record(close)
            btc_state.ready = True

    elif "@depth" in stream:
        bids = data.get("bids", [])
        asks = data.get("asks", [])
        if bids:
            btc_state.bid_vol_top = sum(float(b[1]) for b in bids[:5])
        if asks:
            btc_state.ask_vol_top = sum(float(a[1]) for a in asks[:5])


async def run_btc_ws() -> None:
    backoff = 1
    while True:
        try:
            async with websockets.connect(_WS_URL, ping_interval=20, ping_timeout=30) as ws:
                log.info("Binance BTC WebSocket connected")
                backoff = 1
                async for raw in ws:
                    try:
                        await _process(raw)
                    except Exception as exc:
                        log.error("BTC WS processing error: %s", exc)
        except (websockets.ConnectionClosed, ConnectionError, OSError) as exc:
            log.warning("BTC WS disconnected: %s — reconnect in %ds", exc, backoff)
        except Exception as exc:
            log.exception("BTC WS unexpected error: %s — reconnect in %ds", exc, backoff)
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, 60)
