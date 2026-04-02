"""
Live market data: fetches BTC/USDT OHLCV candles from Binance via ccxt.
"""
from __future__ import annotations

import ccxt
import pandas as pd

from config import CANDLES_NEEDED

_exchange = ccxt.binance({"enableRateLimit": True})


def fetch_btc_ohlcv(n: int = CANDLES_NEEDED) -> pd.DataFrame:
    """Fetch last n 5-minute BTC/USDT candles from Binance."""
    raw = _exchange.fetch_ohlcv("BTC/USDT", timeframe="5m", limit=n)
    df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = df["timestamp"] // 1000  # ms → seconds
    # Binance doesn't provide trade count; approximate from volume/close
    df["trades"] = (df["volume"] / df["close"] * 1000).round().astype(int).clip(lower=1)
    return df
