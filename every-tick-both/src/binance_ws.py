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

from btc_next_bar_model import BinanceBarHistory
from config import BINANCE_WS_URL, log


class BinanceState:
    def __init__(self) -> None:
        self.current_price: float = 0.0
        self.ready: bool = False
        self.last_updated_at: float = 0.0
        self.price_updates: int = 0
        self.session_id: int = 0
        self.last_error: str = ""

        # Rolling price history for returns: (wall_time, log_price)
        self._prices: deque[tuple[float, float]] = deque(maxlen=600)
        self._bar_history = BinanceBarHistory()

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
