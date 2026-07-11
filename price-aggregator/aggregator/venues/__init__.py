from .base import VenueFeed
from .binance import BinanceFeed

REGISTRY = {
    "binance": BinanceFeed,
}

__all__ = ["VenueFeed", "BinanceFeed", "REGISTRY"]
