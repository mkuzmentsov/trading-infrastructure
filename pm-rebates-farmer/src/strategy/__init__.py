"""Strategy package: maker_rebate + pluggable side rules.
Re-exports the old `strategy` shim API so `from strategy import ...` works."""
from .base import PositionDecision, Strategy, StrategyContext
from .factory import build_strategy

__all__ = ["PositionDecision", "Strategy", "StrategyContext", "build_strategy"]
