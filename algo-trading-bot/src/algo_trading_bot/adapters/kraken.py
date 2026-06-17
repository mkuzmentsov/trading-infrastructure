"""Kraken adapter (§2.1, §8) — Kraken spot via ccxt.

Thin credential wrapper over CcxtBroker. Keys come from the environment, never config
or code: ATB_KRAKEN_API_KEY / ATB_KRAKEN_API_SECRET. Kraken spot has no short
positions, so positions() returns {} and the book is long/flat only.
"""

from __future__ import annotations

import os

from ..config import VenueConfig
from ..execution.ccxt_broker import CcxtBroker


class KrakenAdapter(CcxtBroker):
    def __init__(self, cfg: VenueConfig, client=None) -> None:
        ccxt_config = {
            "apiKey": os.environ.get("ATB_KRAKEN_API_KEY", ""),
            "secret": os.environ.get("ATB_KRAKEN_API_SECRET", ""),
            "enableRateLimit": True,
        }
        super().__init__("kraken", ccxt_config=ccxt_config, client=client)
        self.cfg = cfg
