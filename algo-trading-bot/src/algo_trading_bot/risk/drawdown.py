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

    def update(self, nav: float) -> float:
        """Update with latest NAV; return a risk multiplier in [0, 1].

        1.0 above threshold 1; a fractional de-risk between t1 and t2; 0.0 (and
        ``halted=True``) at/below threshold 2.
        """
        raise NotImplementedError(
            "track high-water mark; dd = 1 - nav/hwm; "
            "if dd >= drawdown_halt -> halted=True, return 0; "
            "elif dd >= drawdown_derisk -> return scaled factor; else 1.0."
        )

    def reset(self) -> None:
        """Manual re-arm after a halt (ops decision, never automatic)."""
        self.halted = False
