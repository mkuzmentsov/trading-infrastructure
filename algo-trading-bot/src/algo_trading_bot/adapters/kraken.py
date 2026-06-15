"""Kraken adapter (§2.1, §8) — via CCXT (spot; derivatives where available).

Provides the live market feed and order I/O for Kraken. Symbol normalization maps
Kraken tickers (e.g. 'XBT/USD') to canonical symbols (data/bars.py). Credentials
come from env/secret store, never config.

Requires the ``venues`` extra (ccxt).
"""

from __future__ import annotations

from ..config import VenueConfig
from ..core.types import Fill, Order, Position, Symbol


class KrakenAdapter:
    def __init__(self, cfg: VenueConfig) -> None:
        self.cfg = cfg
        # self._client = ccxt.kraken({...}) initialized lazily.

    # --- ExecutionAdapter ---
    def place(self, order: Order) -> None:
        raise NotImplementedError("ccxt create_order(...)")

    def cancel(self, client_id: str) -> None:
        raise NotImplementedError("ccxt cancel_order(...)")

    def open_orders(self) -> list[Order]:
        raise NotImplementedError("ccxt fetch_open_orders(...)")

    def positions(self) -> dict[Symbol, Position]:
        raise NotImplementedError

    def poll_fills(self) -> list[Fill]:
        raise NotImplementedError("ccxt fetch_my_trades(...)")

    # --- market data ---
    def stream(self):
        raise NotImplementedError("ccxt watch_ohlcv / fetch_ohlcv -> Bar")
