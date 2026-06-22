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
    __slots__ = ("ema_fast", "ema_slow", "prev_close", "rets", "n", "closes", "vol_hist")

    def __init__(self) -> None:
        self.ema_fast: float | None = None
        self.ema_slow: float | None = None
        self.prev_close: float | None = None
        self.rets: deque[float] = deque()
        self.n: int = 0
        self.closes: deque[float] = deque()     # for the Kaufman efficiency ratio
        self.vol_hist: deque[float] = deque()    # trailing ret_vol distribution -> percentile


class RollingFeaturePipeline:
    """Reference pipeline: per-symbol EMAs + realized vol + regime features, strictly causal.

    Regime features (consumed by ``TrendRangeDetector``):
      - ``efficiency_ratio`` — Kaufman ER over ``er_window``: |net move| / sum|bar moves|.
        ~1 = clean trend, ~0 = chop/range. The trend-strength axis.
      - ``vol_pct`` — percentile rank of the current ``ret_vol`` within its trailing
        ``vol_pct_window`` distribution (computed vs PAST values only). The high-vol axis.
      - ``regime_ready`` — 1.0 once both have enough history to be meaningful.
    """

    def __init__(self, fast: int = 20, slow: int = 100, vol_window: int = 48,
                 er_window: int = 20, vol_pct_window: int = 100, vol_pct_min: int = 40) -> None:
        self.fast = fast
        self.slow = slow
        self.vol_window = vol_window
        self.er_window = er_window
        self.vol_pct_window = vol_pct_window
        self.vol_pct_min = vol_pct_min
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

        # --- regime features (causal) ---
        st.closes.append(c)
        if len(st.closes) > self.er_window + 1:
            st.closes.popleft()
        efficiency_ratio = _efficiency_ratio(st.closes, self.er_window)

        # percentile of current ret_vol vs the trailing distribution (PAST only -> no lookahead)
        vol_pct = _percentile_rank(st.vol_hist, ret_vol) if st.vol_hist else 0.5
        if ret_vol > 0:
            st.vol_hist.append(ret_vol)
            if len(st.vol_hist) > self.vol_pct_window:
                st.vol_hist.popleft()

        regime_ready = (
            ready and len(st.closes) > self.er_window and len(st.vol_hist) >= self.vol_pct_min
        )
        return {
            "close": c,
            "ema_fast": st.ema_fast,
            "ema_slow": st.ema_slow,
            "ret_vol": ret_vol,  # per-bar stdev of log returns
            "ready": 1.0 if ready else 0.0,
            "efficiency_ratio": efficiency_ratio,
            "vol_pct": vol_pct,
            "regime_ready": 1.0 if regime_ready else 0.0,
        }

    def warmup_bars(self) -> int:
        return max(self.slow, self.vol_window, self.er_window + 1)


def _std(values) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    mean = sum(values) / n
    var = sum((v - mean) ** 2 for v in values) / (n - 1)
    return math.sqrt(var)


def _efficiency_ratio(closes, window: int) -> float:
    """Kaufman efficiency ratio over the last ``window`` bars: net directional move
    divided by the total path length. 0 when the path hasn't formed yet."""
    if len(closes) <= window:
        return 0.0
    seq = list(closes)[-(window + 1):]
    net = abs(seq[-1] - seq[0])
    path = sum(abs(seq[i] - seq[i - 1]) for i in range(1, len(seq)))
    return net / path if path > 0 else 0.0


def _percentile_rank(history, value: float) -> float:
    """Fraction of ``history`` <= ``value`` (∈[0,1]). Trailing distribution only."""
    n = len(history)
    if n == 0:
        return 0.5
    return sum(1 for h in history if h <= value) / n
