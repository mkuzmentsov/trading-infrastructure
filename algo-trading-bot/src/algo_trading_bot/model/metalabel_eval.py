"""The decisive economic test for the meta-label (principle #4).

OOS AUC says the model *ranks* setups; it does not say the strategy *makes money*.
This module answers the only question that matters: trained on the TRAIN segment and
run OUT-OF-SAMPLE through the same engine and cost model, does meta-labeling lift the
baseline trend's Sharpe after costs?

Method (no leakage):
1. Build the causal labeled dataset over the full series.
2. Time-split events into train / (embargo) / test.
3. Fit the GBT on TRAIN only; predict P(correct) for every event.
4. Run two backtests over the full series — raw trend, and a meta-labeled strategy
   that takes the trend side scaled by the model's confidence (abstaining below the
   training base rate). Measure each on the TEST segment only (same warmup, apples
   to apples).

The meta strategy here reads *precomputed* per-bar predictions; features are causal,
so this is the same feature/label definition as live, computed in batch. Wiring the
incremental live feature path is a separate productionization step.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from ..backtest import metrics as M
from ..config import BotConfig
from ..core.types import Forecast, RiskTier, StrategyId
from ..data.bars import PERIODS_PER_YEAR
from ..features.dataset import build_labeled_dataset
from ..strategy.base import BaseStrategy, MarketState
from ..strategy.baseline_trend import _VALIDITY


class PrecomputedMetaLabel(BaseStrategy):
    """Meta-labeled trend strategy driven by precomputed P(correct) per bar.

    forecast = side * confidence_magnitude, abstaining when the model's probability is
    below the training base rate (a below-average setup -> don't act). Sizing by
    confidence is the whole point of meta-labeling: separate side from size.
    """

    def __init__(self, lookup: dict, threshold: float, interval: str, id: str = "meta_label") -> None:
        super().__init__(id=id, tier=RiskTier.CORE)
        self.lookup = lookup
        self.threshold = threshold
        self.interval = interval

    def on_data(self, state: MarketState) -> Forecast | None:
        entry = self.lookup.get(pd.Timestamp(state.latest_bar.ts))
        if entry is None:
            return None
        side, p = entry
        if side == 0 or p <= self.threshold:
            return None
        mag = (p - self.threshold) / (1.0 - self.threshold)  # in (0, 1]
        valid = timedelta(minutes=_VALIDITY.get(self.interval, 60))
        return Forecast(
            strategy=StrategyId(self.id),
            symbol=state.latest_bar.symbol,
            ts=state.latest_bar.ts,
            value=float(side * mag),
            confidence=float(p),
            valid_until=state.latest_bar.ts + valid,
        )


@dataclass
class EconomicTestResult:
    split_ts: datetime
    oos_bars: int
    base_rate: float
    baseline: M.MetricsReport
    meta: M.MetricsReport
    baseline_oos_sharpe: float
    meta_oos_sharpe: float


def _oos_metrics(res, split_ts, ppy) -> tuple[M.MetricsReport, float]:
    eq = res.equity[res.equity.index >= split_ts]
    ret = res.returns[res.returns.index >= split_ts]
    trades = res.trades
    if not trades.empty:
        trades = trades[pd.to_datetime(trades["ts"]) >= split_ts]
    pnls = trades["realized"].to_numpy() if not trades.empty else np.array([])
    report = M.compute(eq.to_numpy(), ret.to_numpy(), pnls, periods_per_year=ppy)
    return report, report.sharpe


def evaluate_metalabel_oos(
    config: BotConfig,
    start: datetime,
    end: datetime,
    *,
    train_frac: float = 0.6,
    vertical_bars: int = 24,
) -> EconomicTestResult:
    """Train on TRAIN, run baseline vs meta-labeled OOS backtests, compare after costs."""
    from ..engine.backtest import Backtester
    from .metalabel import _make_model

    ppy = PERIODS_PER_YEAR[config.bar_interval]
    bt = Backtester(config)
    bars = bt.load_bars(start, end)

    X, y, w, spans = build_labeled_dataset(
        bars, fast=config.trend.ema_fast, slow=config.trend.ema_slow,
        vol_window=config.trend.vol_window, vertical_bars=vertical_bars,
    )
    if len(X) < 1000:
        raise RuntimeError(f"only {len(X)} labeled events — fetch more history")

    # Time split on event order, with an embargo gap.
    n = len(X)
    split_i = int(n * train_frac)
    embargo_i = min(split_i + int(n * config.validation.embargo_pct), n - 1)
    train_end_ts = X.index[split_i]
    test_start_ts = X.index[embargo_i]

    tr_mask = X.index < train_end_ts
    model = _make_model()
    model.fit(X[tr_mask].to_numpy(), y[tr_mask].to_numpy(), sample_weight=w[tr_mask].to_numpy())

    # Predict P(correct) for every event; build the per-bar lookup (side, p).
    p_all = model.predict_proba(X.to_numpy())[:, 1]
    side_all = np.sign(X["ema_spread"].to_numpy())
    lookup = {ts: (float(s), float(p)) for ts, s, p in zip(X.index, side_all, p_all)}

    base_rate = float(y[tr_mask].mean())
    meta = PrecomputedMetaLabel(lookup, threshold=base_rate, interval=config.bar_interval)

    baseline_res = bt.run(start, end, bars=bars)                       # raw trend
    meta_res = bt.run(start, end, bars=bars, strategies=[meta])        # meta-labeled

    base_m, base_sr = _oos_metrics(baseline_res, test_start_ts, ppy)
    meta_m, meta_sr = _oos_metrics(meta_res, test_start_ts, ppy)

    return EconomicTestResult(
        split_ts=test_start_ts.to_pydatetime(),
        oos_bars=int((pd.DatetimeIndex([b.ts for b in bars]) >= test_start_ts).sum()),
        base_rate=base_rate,
        baseline=base_m,
        meta=meta_m,
        baseline_oos_sharpe=base_sr,
        meta_oos_sharpe=meta_sr,
    )
