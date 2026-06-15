"""RiskGate — the single chokepoint every target passes through before execution.

Composes the risk components in strict precedence (§7.2 rank 1, absolute):

    kill switch  ->  drawdown breaker  ->  stops  ->  hard limits

Each stage can only REDUCE risk. The output is the *risk-approved* target the OMS
is allowed to work toward. Nothing — no strategy, no combined forecast — can route
around this gate (principle #7, NFR6 audited).
"""

from __future__ import annotations

from ..core.types import Position, Symbol, TargetPosition
from .drawdown import DrawdownBreaker
from .kill_switch import KillSwitch
from .limits import LimitChecker
from .stops import StopManager


class RiskGate:
    def __init__(
        self,
        kill: KillSwitch,
        drawdown: DrawdownBreaker,
        stops: StopManager,
        limits: LimitChecker,
    ) -> None:
        self.kill = kill
        self.drawdown = drawdown
        self.stops = stops
        self.limits = limits

    def approve(
        self,
        target: TargetPosition,
        positions: dict[Symbol, Position],
        last_price: float,
        venue,
    ) -> TargetPosition:
        """Apply all risk stages in precedence order; return the approved target.

        1. kill switch tripped -> force flat.
        2. drawdown halt -> force flat; de-risk -> scale down.
        3. stop breached for this symbol -> force flat.
        4. limit check -> clamp to caps.
        """
        raise NotImplementedError("apply stages top-to-bottom; each may only shrink the target")
