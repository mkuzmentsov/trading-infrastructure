"""Point-in-time feature pipeline (§2.2).

A FeaturePipeline maintains rolling state per symbol and, on each new bar, emits a
feature vector computed *only* from data already knowable. The same pipeline runs
in backtest and live (NFR1) — there is no separate "training feature builder",
which is how subtle lookahead usually creeps in.

This v0.1 pipeline computes the minimal set the trend baseline needs: fast/slow
EMAs of close and the realized per-bar volatility of log returns. Richer families
(fracdiff, order-flow, cross-asset, funding context) plug in here later.
"""

from __future__ import annotations

import math
from collections import deque
from typing import Protocol

from ..core.types import Bar, Symbol


class FeaturePipeline(Protocol):
    def update(self, bar: Bar) -> dict[str, float]: ...
    def warmup_bars(self) -> int: ...


class _SymbolState:
    __slots__ = ("ema_fast", "ema_slow", "prev_close", "rets", "n")

    def __init__(self) -> None:
        self.ema_fast: float | None = None
        self.ema_slow: float | None = None
        self.prev_close: float | None = None
        self.rets: deque[float] = deque()
        self.n: int = 0


class RollingFeaturePipeline:
    """Reference pipeline: per-symbol EMAs + realized vol, strictly causal."""

    def __init__(self, fast: int = 20, slow: int = 100, vol_window: int = 48) -> None:
        self.fast = fast
        self.slow = slow
        self.vol_window = vol_window
        self._a_fast = 2.0 / (fast + 1)
        self._a_slow = 2.0 / (slow + 1)
        self._state: dict[Symbol, _SymbolState] = {}

    def update(self, bar: Bar) -> dict[str, float]:
        """Ingest one bar, return the feature vector knowable at ``bar.known_at()``.

        Features are NaN-free only after warmup; ``ready`` flags when they are valid.
        """
        st = self._state.setdefault(bar.symbol, _SymbolState())
        c = bar.close
        st.ema_fast = c if st.ema_fast is None else st.ema_fast + self._a_fast * (c - st.ema_fast)
        st.ema_slow = c if st.ema_slow is None else st.ema_slow + self._a_slow * (c - st.ema_slow)
        if st.prev_close is not None and st.prev_close > 0:
            st.rets.append(math.log(c / st.prev_close))
            if len(st.rets) > self.vol_window:
                st.rets.popleft()
        st.prev_close = c
        st.n += 1

        ret_vol = _std(st.rets) if len(st.rets) >= 2 else 0.0
        ready = st.n >= self.slow and len(st.rets) >= self.vol_window and ret_vol > 0
        return {
            "close": c,
            "ema_fast": st.ema_fast,
            "ema_slow": st.ema_slow,
            "ret_vol": ret_vol,  # per-bar stdev of log returns
            "ready": 1.0 if ready else 0.0,
        }

    def warmup_bars(self) -> int:
        return max(self.slow, self.vol_window)


def _std(values) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    mean = sum(values) / n
    var = sum((v - mean) ** 2 for v in values) / (n - 1)
    return math.sqrt(var)
