"""Hard limits + pre-trade checks (§2.5, §5).

Every order passes a pre-trade limit check. Limits: per-instrument position,
gross/net exposure, leverage ceiling, per-venue capital cap (NFR5). A target that
violates a limit is clamped down to the limit — never up.
"""

from __future__ import annotations

from ..config import RiskConfig
from ..core.types import Position, Symbol, TargetPosition, VenueId


class LimitChecker:
    def __init__(self, risk: RiskConfig, venue_caps: dict[VenueId, float]) -> None:
        self.risk = risk
        self.venue_caps = venue_caps

    def clamp_target(
        self,
        target: TargetPosition,
        positions: dict[Symbol, Position],
        venue: VenueId,
    ) -> TargetPosition:
        """Return ``target`` shrunk to satisfy all limits. Pure reduction (§7.2)."""
        raise NotImplementedError(
            "clamp |notional| to max_position_notional; enforce gross leverage across "
            "positions; enforce per-venue capital cap."
        )

    def check_order(self, order, positions, venue: VenueId) -> bool:
        """Final pre-trade gate on an individual order. False -> reject, do not send."""
        raise NotImplementedError
