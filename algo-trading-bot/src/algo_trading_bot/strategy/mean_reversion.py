"""Tier-3 mean reversion / counter-trend (§6.2) — handle with care.

NEGATIVE SKEW, HIGH TAIL RISK. Many small wins, rare large losses — the classic
account-killer if mis-sized (§12, §11). Therefore: smallest risk budget, hard
stops, and GATED OFF in strong trends by the regime gate. Fades extremes back
toward the mean, only in confirmed ranges.

Do NOT let this strategy's "defend the thesis" instinct leak into the system — a
genuine reversal must still flip the net target (§7.4).
"""

from __future__ import annotations

from ..core.types import Forecast, RiskTier
from .base import BaseStrategy, MarketState


class MeanReversion(BaseStrategy):
    def __init__(self, lookback: int = 20, z_entry: float = 2.0, id: str = "mean_reversion") -> None:
        super().__init__(id=id, tier=RiskTier.TACTICAL)
        self.lookback = lookback
        self.z_entry = z_entry

    def on_data(self, state: MarketState) -> Forecast | None:
        raise NotImplementedError(
            "z = (close - rolling_mean) / rolling_std; fade when |z| > z_entry. "
            "Forecast magnitude small by construction; rely on the regime gate to zero "
            "this out unless regime == RANGE."
        )
