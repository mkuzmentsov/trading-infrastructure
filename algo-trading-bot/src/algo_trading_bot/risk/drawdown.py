"""Tiered drawdown circuit breaker (§2.5, §5).

Survival before profit (principle #5). Two tiers off the NAV high-water mark:
  * threshold 1 (de-risk): scale all targets down by a factor < 1;
  * threshold 2 (halt): flatten everything and stop opening, until manual reset.
"""

from __future__ import annotations

from ..config import RiskConfig


class DrawdownBreaker:
    def __init__(self, risk: RiskConfig) -> None:
        self.risk = risk
        self._hwm: float = 0.0
        self.halted: bool = False
        self.factor: float = 1.0  # latest risk multiplier; read by the RiskGate

    def update(self, nav: float) -> float:
        """Update with latest NAV; return a risk multiplier in [0, 1].

        1.0 above threshold 1; a linear de-risk between t1 and t2; 0.0 (and
        ``halted=True``) at/below threshold 2. Once halted, stays halted until reset.
        """
        self._hwm = max(self._hwm, nav)
        if self._hwm <= 0:
            self.factor = 1.0
            return self.factor
        dd = 1.0 - nav / self._hwm
        t1, t2 = self.risk.drawdown_derisk, self.risk.drawdown_halt
        if self.halted or dd >= t2:
            self.halted = True
            self.factor = 0.0
        elif dd >= t1 and t2 > t1:
            # linearly scale exposure from 1.0 at t1 down to 0.0 at t2
            self.factor = max(0.0, 1.0 - (dd - t1) / (t2 - t1))
        else:
            self.factor = 1.0
        return self.factor

    def reset(self) -> None:
        """Manual re-arm after a halt (ops decision, never automatic)."""
        self.halted = False
