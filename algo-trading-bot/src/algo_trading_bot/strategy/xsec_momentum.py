"""Tier-2 cross-sectional momentum (§6.2).

Rank the universe by trailing momentum; long the strongest, short the weakest,
dollar-neutral. Diversifies single-asset trend. Needs an asset universe (so the
arbitration layer must run over multiple symbols at once). Moderate risk budget.
"""

from __future__ import annotations

from ..core.types import Forecast, RiskTier, Symbol
from .base import BaseStrategy, MarketState


class CrossSectionalMomentum(BaseStrategy):
    def __init__(self, lookback: int = 14, n_long: int = 3, n_short: int = 3,
                 id: str = "xsec_momentum") -> None:
        super().__init__(id=id, tier=RiskTier.CORE)
        self.lookback = lookback
        self.n_long = n_long
        self.n_short = n_short

    def forecasts(self, state: MarketState) -> dict[Symbol, Forecast]:
        """Cross-sectional strategies score the whole universe at once, so they emit a
        dict of forecasts. The engine reconciles this with the per-symbol on_data path."""
        raise NotImplementedError(
            "rank universe_features by `mom{lookback}`; +1 to top n_long, -1 to bottom n_short, "
            "0 to the rest; demean to keep it dollar-neutral."
        )

    def on_data(self, state: MarketState) -> Forecast | None:
        # Single-symbol entrypoint is not meaningful for a cross-sectional model.
        raise NotImplementedError("use forecasts(state) for the cross-sectional book")
