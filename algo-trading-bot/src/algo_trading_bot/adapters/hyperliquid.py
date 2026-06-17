"""Hyperliquid adapter (§2.1, §8) — HL perps via ccxt.

Thin credential wrapper over CcxtBroker. HL signs with an API wallet: credentials come
from the environment, never config or code — ATB_HL_WALLET_ADDRESS / ATB_HL_PRIVATE_KEY.
HL is a perp venue, so positions() returns signed net positions (long/short).

Funding is native and frequent; it is surfaced as a context feature, not a strategy
(§2.1). Funding settlement in the live PnL is a follow-up (flagged, not silently
omitted).
"""

from __future__ import annotations

import os

from ..config import VenueConfig
from ..execution.ccxt_broker import CcxtBroker


class HyperliquidAdapter(CcxtBroker):
    def __init__(self, cfg: VenueConfig, client=None) -> None:
        ccxt_config = {
            "walletAddress": os.environ.get("ATB_HL_WALLET_ADDRESS", ""),
            "privateKey": os.environ.get("ATB_HL_PRIVATE_KEY", ""),
            "enableRateLimit": True,
        }
        if cfg.testnet:
            ccxt_config["sandbox"] = True
        super().__init__("hyperliquid", ccxt_config=ccxt_config, client=client)
        self.cfg = cfg
