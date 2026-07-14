"""
Binance BTC/USDT real-time price feed.

Connects to Binance aggTrade stream to get sub-second BTC price updates.
This feed is structurally faster than the Chainlink oracle that Polymarket
uses — typical lead time is 1-3 seconds. The latency arb signal exploits
this gap: when Binance shows a BTC move but the PM book is still priced
off the stale oracle, we can buy the cheap side and hold to expiry.

Graceful degradation: if Binance is unreachable, the bot falls back to
Chainlink-only pricing (no latency arb, just book-vs-oracle divergence).
"""
from __future__ import annotations

import asyncio
import json
import math
import time
from collections import deque

import websockets

from config import BINANCE_WS_URL, log
from execution.tickbus import tick_bus


class _MinuteBars:
    """Minimal 1m OHLC tracker (replaces the deleted btc_next_bar_model
    BinanceBarHistory — only completed_bars() consumers remain, and the sole
    caller was the removed ML prior; kept for the feed heartbeat/diagnostics)."""

    def __init__(self) -> None:
        self._bars: dict[int, dict] = {}

    def update(self, wall_time: float, price: float, quantity: float = 0.0,
               buyer_is_maker: bool | None = None) -> None:
        ts = int(wall_time // 60 * 60)
        bar = self._bars.setdefault(ts, {"ts": ts, "open": price, "high": price,
                                         "low": price, "close": price, "volume": 0.0})
        bar["high"] = max(bar["high"], price)
        bar["low"] = min(bar["low"], price)
        bar["close"] = price
        bar["volume"] += quantity
        if len(self._bars) > 300:
            for k in sorted(self._bars)[:-300]:
                self._bars.pop(k, None)

    def completed_bars(self, before_ts: int | None = None, limit: int = 64) -> list[dict]:
        now_bar = int(__import__("time").time() // 60 * 60)
        keys = [k for k in sorted(self._bars) if k < now_bar
                and (before_ts is None or k < before_ts)]
        return [self._bars[k] for k in keys[-limit:]]


class BinanceState:
    def __init__(self) -> None:
        self.current_price: float = 0.0
        self.ready: bool = False
        self.last_updated_at: float = 0.0
        self.price_updates: int = 0
        self.session_id: int = 0
        self.last_error: str = ""
        # delivery latency: local arrival − exchange trade time (ms), EWMA'd.
        # Includes local clock offset; useful relatively (before/after, hel/us).
        self.last_delay_ms: float = 0.0
        self.delay_ewma_ms: float = 0.0

        # Rolling price history for returns: (wall_time, log_price)
        self._prices: deque[tuple[float, float]] = deque(maxlen=600)
        self._bar_history = _MinuteBars()

    def _record(self, wall_time: float, price: float, quantity: float = 0.0, buyer_is_maker: bool | None = None) -> None:
        if price <= 0:
            return
        self.current_price = price
        self.last_updated_at = wall_time
        self.price_updates += 1
        self.ready = True
        lp = math.log(price)
        if self._prices and wall_time <= self._prices[-1][0]:
            self._prices[-1] = (wall_time, lp)
        else:
            self._prices.append((wall_time, lp))
        self._bar_history.update(wall_time, price, quantity=quantity, buyer_is_maker=buyer_is_maker)

    def ret_since(self, seconds: float) -> float:
        """Log-return over the last `seconds` seconds."""
        if len(self._prices) < 2:
            return 0.0
        now_t, now_lp = self._prices[-1]
        cutoff = now_t - seconds
        for t, lp in self._prices:
            if t >= cutoff:
                return now_lp - lp
        return now_lp - self._prices[0][1]

    def age(self) -> float:
        """Seconds since last price update."""
        if self.last_updated_at <= 0:
            return float("inf")
        return time.time() - self.last_updated_at

    def completed_bars(self, before_ts: int | None = None, limit: int = 64) -> list[dict]:
        return self._bar_history.completed_bars(before_ts=before_ts, limit=limit)

    def bar_open_at(self, ts: int) -> float | None:
        """Open of the 1m bar starting at `ts` (works for any 60s-grid window
        start, so also 5m/15m bar opens). None if we have no trade there."""
        bar = self._bar_history._bars.get(int(ts))
        return bar["open"] if bar else None

    def ret_windowed(self, seconds: float, tol: float = 4.0) -> float | None:
        """Log-return over the last ~`seconds` seconds, only if a sample exists
        within ±tol of the target age (sparse tape → None, like the legacy
        momentum sampler); ret_since() would silently shorten the window."""
        if len(self._prices) < 2:
            return None
        now_t, now_lp = self._prices[-1]
        for t, lp in reversed(self._prices):
            if seconds - tol <= now_t - t <= seconds + tol:
                return now_lp - lp
            if now_t - t > seconds + tol:
                break
        return None

    def seed_minute_bars(self, rows: list[tuple[int, float, float, float, float]]) -> None:
        """Seed 1m OHLC history from REST klines (ts, open, high, low, close)
        so sigma and bar opens are available immediately after a restart."""
        for ts, o, h, l, c in rows:
            self._bar_history._bars.setdefault(
                int(ts), {"ts": int(ts), "open": o, "high": h, "low": l,
                          "close": c, "volume": 0.0})


binance_state = BinanceState()


async def run_binance_ws() -> None:
    """Connect to Binance aggTrade stream and update binance_state."""
    if not BINANCE_WS_URL:
        log.info("Binance WS disabled (BINANCE_WS_URL empty)")
        return

    backoff = 1
    last_heartbeat = 0.0

    while True:
        try:
            binance_state.session_id += 1
            log.info(
                "Binance WS connecting  session=%d url=%s",
                binance_state.session_id,
                BINANCE_WS_URL,
            )
            async with websockets.connect(
                BINANCE_WS_URL, ping_interval=20, ping_timeout=30
            ) as ws:
                log.info("Binance WS connected  session=%d", binance_state.session_id)
                backoff = 1

                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        continue

                    # aggTrade message format:
                    # {"e":"aggTrade","s":"BTCUSDT","p":"84532.10","T":1713200000000,...}
                    price_str = msg.get("p")
                    qty_str = msg.get("q")
                    buyer_is_maker = msg.get("m")
                    trade_ts = msg.get("T")  # ms
                    if price_str and trade_ts:
                        price = float(price_str)
                        quantity = float(qty_str or 0.0)
                        wall_time = float(trade_ts) / 1000.0
                        binance_state._record(wall_time, price, quantity=quantity, buyer_is_maker=buyer_is_maker)
                        delay_ms = (time.time() - wall_time) * 1000.0
                        binance_state.last_delay_ms = delay_ms
                        binance_state.delay_ewma_ms = (
                            delay_ms if binance_state.delay_ewma_ms == 0.0
                            else 0.05 * delay_ms + 0.95 * binance_state.delay_ewma_ms)
                        tick_bus.fire("binance", wall_time)

                    now = time.time()
                    if now - last_heartbeat >= 30:
                        last_heartbeat = now
                        log.info(
                            "Binance heartbeat  session=%d price=%.2f updates=%d age=%.1fs",
                            binance_state.session_id,
                            binance_state.current_price,
                            binance_state.price_updates,
                            binance_state.age(),
                        )

        except (websockets.ConnectionClosed, ConnectionError, OSError) as exc:
            binance_state.last_error = str(exc)
            log.warning("Binance WS disconnected: %s — reconnect in %ds", exc, backoff)
        except Exception as exc:
            binance_state.last_error = str(exc)
            log.exception("Binance WS error: %s — reconnect in %ds", exc, backoff)

        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, 60)
