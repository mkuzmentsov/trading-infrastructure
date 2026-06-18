"""Concrete venue adapters (§2.1, §8). One venue is active per run (§2.1, NFR5).

Each adapter implements both sides behind a clean boundary:
  * market data feed  -> data.source.LiveSource
  * order I/O         -> execution.adapter.ExecutionAdapter

The existing `trading-mcp` server is kept SEPARATE; if used at all it is reached
only through one of these adapters, never imported across the boundary (§0).
"""

from __future__ import annotations

from ..config import VenueConfig


def make_adapter(cfg: VenueConfig):
    """Factory: return the execution+data adapter for the configured venue."""
    name = cfg.name.lower()
    if name == "hyperliquid":
        from .hyperliquid import HyperliquidAdapter

        return HyperliquidAdapter(cfg)
    if name == "krakenfutures":
        from .kraken import KrakenFuturesAdapter

        return KrakenFuturesAdapter(cfg)
    if name == "kraken":
        from .kraken import KrakenAdapter

        return KrakenAdapter(cfg)
    raise ValueError(
        f"unknown venue: {cfg.name!r} (expected 'hyperliquid' | 'krakenfutures' | 'kraken')"
    )
