from __future__ import annotations

from .base import Strategy
from .latency_arb_hold import LatencyArbHoldStrategy
from .ml_entry import MLEntryStrategy
from .profit_1 import Profit1Strategy


def build_strategy(name: str) -> Strategy:
    normalized = (name or "").strip().lower()
    if normalized in {"", "latency_arb_hold"}:
        return LatencyArbHoldStrategy()
    if normalized == "profit_1":
        return Profit1Strategy()
    if normalized in {"pm_btc_ml-entry", "pm_btc_ml_entry", "ml_entry"}:
        return MLEntryStrategy()
    raise ValueError(f"Unknown strategy: {name}")
