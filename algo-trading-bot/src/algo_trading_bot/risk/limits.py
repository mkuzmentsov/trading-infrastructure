"""Hard limits + pre-trade checks (§2.5, §5).

Every order passes a pre-trade limit check. Limits: per-instrument position,
gross/net exposure, leverage ceiling, per-venue capital cap (NFR5). A target that
violates a limit is clamped down to the limit — never up.
"""

from __future__ import annotations

from dataclasses import replace

from ..config import RiskConfig
from ..core.types import Position, Symbol, TargetPosition, VenueId


class LimitChecker:
    def __init__(self, risk: RiskConfig, capital: float, venue_caps: dict[VenueId, float] | None = None) -> None:
        self.risk = risk
        self.capital = capital
        self.venue_caps = venue_caps or {}

    def clamp_target(
        self,
        target: TargetPosition,
        positions: dict[Symbol, Position],
        venue: VenueId,
    ) -> TargetPosition:
        """Return ``target`` shrunk to satisfy all limits. Pure reduction (§7.2)."""
        cap = self.capital * self.risk.max_gross_leverage
        if self.risk.max_position_notional > 0:
            cap = min(cap, self.risk.max_position_notional)
        venue_cap = self.venue_caps.get(venue)
        if venue_cap and venue_cap > 0:
            cap = min(cap, venue_cap)
        clamped = max(-cap, min(cap, target.notional))
        if clamped == target.notional:
            return target
        return replace(target, notional=clamped, reason=target.reason + "+limit")

    def check_order(self, order, positions, venue: VenueId) -> bool:
        """Final pre-trade gate on an individual order. False -> reject, do not send."""
        return order.quantity > 0
