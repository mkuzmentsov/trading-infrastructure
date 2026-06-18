"""Kraken adapters (§2.1, §8) — via ccxt.

Thin credential wrappers over CcxtBroker. Keys come from the environment, never config
or code. Two venues:

* KrakenFuturesAdapter (`krakenfutures`) — USD-settled perpetuals, long/short with
  leverage. This is what the bot trades. Keys: ATB_KRAKENFUTURES_API_KEY / _SECRET.
* KrakenAdapter (`kraken`) — spot, long/flat only. Kept for completeness/data. Keys:
  ATB_KRAKEN_API_KEY / _SECRET.
"""

from __future__ import annotations

import os

from ..config import VenueConfig
from ..execution.ccxt_broker import CcxtBroker


class KrakenFuturesAdapter(CcxtBroker):
    def __init__(self, cfg: VenueConfig, client=None) -> None:
        ccxt_config = {
            "apiKey": os.environ.get("ATB_KRAKENFUTURES_API_KEY", ""),
            "secret": os.environ.get("ATB_KRAKENFUTURES_API_SECRET", ""),
            "enableRateLimit": True,
        }
        super().__init__("krakenfutures", ccxt_config=ccxt_config, client=client)
        self.cfg = cfg


class KrakenAdapter(CcxtBroker):
    def __init__(self, cfg: VenueConfig, client=None) -> None:
        ccxt_config = {
            "apiKey": os.environ.get("ATB_KRAKEN_API_KEY", ""),
            "secret": os.environ.get("ATB_KRAKEN_API_SECRET", ""),
            "enableRateLimit": True,
        }
        super().__init__("kraken", ccxt_config=ccxt_config, client=client)
        self.cfg = cfg
