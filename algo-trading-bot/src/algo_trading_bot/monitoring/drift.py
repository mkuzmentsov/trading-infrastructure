"""Live-vs-expected drift detection with automatic model disable (§2.7, FR9).

Edges decay (principle #10). This compares the live realized distribution (hit
rate, per-trade PnL, Sharpe, forecast calibration) against the OOS expectation the
model was approved with. On a statistically significant degradation it auto-disables
the model — zeroing its forecast weight and alerting — *before* the drawdown breaker
has to (which would be later and more expensive).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DriftBaseline:
    """The OOS expectation captured at approve-for-live time (§4 gate)."""

    expected_sharpe: float
    expected_hit_rate: float
    expected_mean_pnl: float
    expected_pnl_std: float


class DriftMonitor:
    def __init__(self, baseline: DriftBaseline, window: int = 100, alpha: float = 0.01) -> None:
        self.baseline = baseline
        self.window = window
        self.alpha = alpha
        self.disabled: bool = False

    def update(self, recent_pnls) -> bool:
        """Test the recent window against the baseline. Returns True if the model should
        be disabled (degradation significant at level ``alpha``)."""
        raise NotImplementedError(
            "rolling test (e.g. t-test / PSR drop) of recent vs baseline; "
            "set self.disabled and signal the arbitration layer to zero this model's weight."
        )
