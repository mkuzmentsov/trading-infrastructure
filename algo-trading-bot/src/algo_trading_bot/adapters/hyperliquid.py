"""Hyperliquid adapter (§2.1, §8) — native hyperliquid-python-sdk (perps).

Provides the live market feed and order I/O for HL. Funding is native and frequent;
it is surfaced as a context feature (FundingPoint), never as a strategy (§2.1).
Credentials (API wallet / private key) come from env/secret store, never config.

Requires the ``venues`` extra (hyperliquid-python-sdk, eth-account).
"""

from __future__ import annotations

from ..config import VenueConfig
from ..core.types import Fill, Order, Position, Symbol


class HyperliquidAdapter:
    def __init__(self, cfg: VenueConfig) -> None:
        self.cfg = cfg
        # self._info / self._exchange initialized lazily from the HL SDK.

    # --- ExecutionAdapter ---
    def place(self, order: Order) -> None:
        raise NotImplementedError("hyperliquid Exchange.order(...)")

    def cancel(self, client_id: str) -> None:
        raise NotImplementedError("hyperliquid Exchange.cancel(...)")

    def open_orders(self) -> list[Order]:
        raise NotImplementedError

    def positions(self) -> dict[Symbol, Position]:
        raise NotImplementedError

    def poll_fills(self) -> list[Fill]:
        raise NotImplementedError

    # --- market data ---
    def stream(self):
        raise NotImplementedError("HL websocket candles + funding -> Bar/FundingPoint")
