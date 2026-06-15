"""Point-in-time feature pipeline (§2.2).

A FeaturePipeline maintains rolling state per symbol and, on each new bar, emits a
feature vector computed *only* from data already knowable. The same pipeline runs
in backtest and live (NFR1) — there is no separate "training feature builder",
which is how subtle lookahead usually creeps in.

Feature families (§2.2): price/volume & TA, realized vol, order-flow/book
imbalance (short-horizon only), cross-asset & dominance, funding/OI as context,
calendar/seasonality. Fractional differentiation (fracdiff.py) is the preferred
stationarity transform — keep memory, not just differences.
"""

from __future__ import annotations

from typing import Protocol

from ..core.types import Bar, Symbol


class FeaturePipeline(Protocol):
    def update(self, bar: Bar) -> dict[str, float]:
        """Ingest one bar, return the feature vector knowable at ``bar.known_at()``."""
        ...

    def warmup_bars(self) -> int:
        """Bars required before features are valid (longest lookback window)."""
        ...


class RollingFeaturePipeline:
    """Reference pipeline: maintains per-symbol rolling windows, no lookahead."""

    def __init__(self, lookback: int = 256) -> None:
        self.lookback = lookback
        self._state: dict[Symbol, list[Bar]] = {}

    def update(self, bar: Bar) -> dict[str, float]:
        window = self._state.setdefault(bar.symbol, [])
        window.append(bar)
        if len(window) > self.lookback:
            del window[0]
        raise NotImplementedError("compute TA / realized vol / fracdiff features from `window`")

    def warmup_bars(self) -> int:
        return self.lookback
