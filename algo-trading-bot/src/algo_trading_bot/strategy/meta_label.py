"""Tier-2 meta-labeled momentum — THE PRIMARY ML STRATEGY (§3, §6.2).

Meta-labeling separates *side* from *size* (principle #3). A simple primary model
(here: a Tier-1 trend signal) decides the side; this ML layer decides only
*whether to act and how big*, by predicting P(the primary signal is right).

It is a GBT on engineered tabular features (principle #11), trained on
triple-barrier labels, validated inside purged CV (§4). Its forecast is the
primary side * predicted precision, so a low-confidence setup shrinks toward zero
rather than flipping direction. Its risk budget grows only as it beats the
baseline OOS, after costs (principle #4).
"""

from __future__ import annotations

from typing import Any

from ..core.types import Forecast, RiskTier
from .base import BaseStrategy, MarketState


class MetaLabelMomentum(BaseStrategy):
    def __init__(self, primary: BaseStrategy, model: Any | None = None,
                 id: str = "meta_label_momentum") -> None:
        super().__init__(id=id, tier=RiskTier.CORE)
        self.primary = primary
        self.model = model  # fitted LightGBM/sklearn classifier; None until trained

    def on_data(self, state: MarketState) -> Forecast | None:
        raise NotImplementedError(
            "side = sign(primary.on_data(state)); if 0 -> abstain. "
            "p = model.predict_proba(features); forecast.value = side * scale(p); "
            "confidence = p. Model must be the SAME object used in validation (NFR1)."
        )
