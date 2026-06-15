"""Strategy interface (§2.3, §7.1).

The contract is deliberately narrow: given read-only market state, return a
:class:`Forecast` (or None to abstain). A strategy:

* never sees the portfolio, never issues orders, never knows about other
  strategies — it only expresses a view (§7.1);
* declares its :class:`RiskTier`, which sets its static risk budget and how
  aggressively the regime gate treats it (§6.2);
* is pure w.r.t. the state passed in, so backtest and live are identical (NFR1)
  and the run is replayable from logged forecasts (NFR7).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from ..core.clock import Clock
from ..core.types import Bar, Forecast, RiskTier, StrategyId, Symbol


@dataclass
class MarketState:
    """Read-only snapshot handed to a strategy on each event (point-in-time)."""

    clock: Clock
    latest_bar: Bar
    features: dict[str, float] = field(default_factory=dict)
    # Cross-sectional strategies need the whole universe's latest features:
    universe_features: dict[Symbol, dict[str, float]] = field(default_factory=dict)


class Strategy(Protocol):
    id: StrategyId
    tier: RiskTier

    def on_data(self, state: MarketState) -> Forecast | None:
        """Return a continuous forecast in ~[-1, +1], or None to abstain."""
        ...


class BaseStrategy:
    """Convenience base with id/tier wiring. Subclasses implement ``on_data``."""

    id: StrategyId
    tier: RiskTier

    def __init__(self, id: str, tier: RiskTier) -> None:
        self.id = StrategyId(id)
        self.tier = tier

    def on_data(self, state: MarketState) -> Forecast | None:  # pragma: no cover - abstract
        raise NotImplementedError
