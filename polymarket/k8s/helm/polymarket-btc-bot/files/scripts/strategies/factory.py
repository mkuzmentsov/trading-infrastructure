from __future__ import annotations

from .base import Strategy
from .latency_arb_hold import LatencyArbHoldStrategy
from .profit_1 import Profit1Strategy


def build_strategy(name: str) -> Strategy:
    normalized = (name or "").strip().lower()
    if normalized in {"", "latency_arb_hold"}:
        return LatencyArbHoldStrategy()
    if normalized == "profit_1":
        return Profit1Strategy()
    raise ValueError(f"Unknown strategy: {name}")
