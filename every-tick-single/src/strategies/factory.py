from __future__ import annotations

from .base import Strategy
from .latency_arb_hold import LatencyArbHoldStrategy
from .maker_rebate import MakerRebateStrategy
from .math_smart import MathSmartStrategy
from .math_smart_v2 import MathSmartV2Strategy
from .ml_entry import MLEntryStrategy
from .ml_entry_v2 import MLEntryV2Strategy
from .profit_1 import Profit1Strategy


def build_strategy(name: str) -> Strategy:
    normalized = (name or "").strip().lower()
    if normalized in {"", "latency_arb_hold"}:
        return LatencyArbHoldStrategy()
    if normalized == "profit_1":
        return Profit1Strategy()
    if normalized in {"pm_btc_ml-entry", "pm_btc_ml_entry", "ml_entry"}:
        return MLEntryStrategy()
    if normalized in {"pm_btc_ml-entry-v2", "pm_btc_ml_entry_v2", "ml_entry_v2"}:
        return MLEntryV2Strategy()
    if normalized in {"math_smart", "pm_btc_math_smart", "pm_btc_math-smart"}:
        return MathSmartStrategy()
    if normalized in {"math_smart_v2", "pm_btc_math_smart_v2", "pm_btc_math-smart-v2"}:
        return MathSmartV2Strategy()
    if normalized == "maker_rebate":
        return MakerRebateStrategy()
    raise ValueError(f"Unknown strategy: {name}")
