"""Core domain types.

These are the vocabulary every layer speaks. Kept as plain dataclasses (not
pydantic) because they sit on the hot path of the event loop and are created
densely during backtests. Validation/IO models that cross a boundary use pydantic
(see config.py).

Key modelling choices, tied to requirements:

* A strategy never emits an order. It emits a :class:`Forecast` — a continuous,
  scaled direction*strength value with a validity window (§2.3, §7.1, §7.5).
* The arbitration layer nets forecasts into one :class:`TargetPosition` per
  instrument (§2.4, §7.1). Execution trades the gap to it (§2.6, §7.3).
* Time is always *point-in-time*: every record carries when it was *knowable*
  (``knowable_at``) distinct from the event time it describes (§2.1).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import NewType

# --- identifiers -----------------------------------------------------------

Symbol = NewType("Symbol", str)  # canonical instrument id, e.g. "BTC" / "ETH-PERP"
StrategyId = NewType("StrategyId", str)
VenueId = NewType("VenueId", str)  # "hyperliquid" | "kraken"


class Side(Enum):
    LONG = 1
    SHORT = -1
    FLAT = 0


class Horizon(Enum):
    """Holding-period regime — drives granularity, features, cost model (§6.0).

    Scalping is intentionally out of scope for v0.1 (no L2/latency infra).
    """

    SWING = "swing"        # hours–days
    POSITION = "position"  # days–weeks


# --- market data -----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Bar:
    """One OHLCV bar, point-in-time stamped.

    ``ts`` is the bar's *close* time (the event it describes). ``knowable_at`` is
    when the bar became usable without lookahead — normally == close time for a
    settled bar, but a separate field so the engine can enforce no-lookahead
    centrally rather than trusting each feature (§2.1, §2.2).
    """

    symbol: Symbol
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    venue: VenueId
    knowable_at: datetime | None = None

    def known_at(self) -> datetime:
        return self.knowable_at or self.ts


@dataclass(frozen=True, slots=True)
class FundingPoint:
    """Funding/OI context series — used as a *feature*, never as the strategy (§2.1)."""

    symbol: Symbol
    ts: datetime
    funding_rate: float
    open_interest: float | None = None
    venue: VenueId = VenueId("")


# --- strategy output -------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Forecast:
    """Continuous, scaled view of a single strategy on a single instrument.

    ``value`` is direction*strength, conventionally clipped to roughly [-1, +1]
    (Carver-style). It is *not* an order and *not* a position size — the
    arbitration layer turns combined forecasts into a target (§7.1).

    ``valid_until`` implements signal staleness (§7.5): past it the combiner
    decays the forecast toward zero. ``confidence`` in [0, 1] feeds the weight
    ``validated_edge x live_confidence x risk_budget`` (§7.2).
    """

    strategy: StrategyId
    symbol: Symbol
    ts: datetime
    value: float
    confidence: float = 1.0
    valid_until: datetime | None = None

    def is_stale(self, now: datetime) -> bool:
        return self.valid_until is not None and now > self.valid_until


# --- positions & targets ---------------------------------------------------


@dataclass(frozen=True, slots=True)
class TargetPosition:
    """The single netted target the book should hold for one instrument (§7.1).

    Expressed as signed notional in quote currency. Execution trades the gap
    between the current position and this. A deadband/min-trade threshold lives
    in the OMS, not here (§7.5).
    """

    symbol: Symbol
    notional: float  # signed; + long, - short
    ts: datetime
    reason: str = ""  # audit trail (NFR6)


@dataclass(slots=True)
class Position:
    """Current realized holding in one instrument, maintained from fills."""

    symbol: Symbol
    quantity: float = 0.0       # signed, base units
    avg_price: float = 0.0
    realized_pnl: float = 0.0

    @property
    def side(self) -> Side:
        if self.quantity > 0:
            return Side.LONG
        if self.quantity < 0:
            return Side.SHORT
        return Side.FLAT


# --- orders & fills --------------------------------------------------------


class OrderType(Enum):
    MARKET = "market"
    LIMIT = "limit"


class OrderStatus(Enum):
    NEW = "new"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELED = "canceled"
    REJECTED = "rejected"


@dataclass(slots=True)
class Order:
    """An execution intent toward the latest target. Carries ``client_id`` so the
    OMS can be idempotent and reconcile in-flight orders on restart (§2.6, §7.3)."""

    client_id: str
    symbol: Symbol
    side: Side
    quantity: float            # base units, always positive
    order_type: OrderType
    limit_price: float | None = None
    venue: VenueId = VenueId("")
    status: OrderStatus = OrderStatus.NEW
    filled_quantity: float = 0.0
    ts: datetime | None = None


@dataclass(frozen=True, slots=True)
class Fill:
    """A (partial) execution. Includes realized friction so the ledger and live
    accounting use the same cost model (§3.2)."""

    order_id: str
    symbol: Symbol
    side: Side
    quantity: float
    price: float
    fee: float
    ts: datetime
    venue: VenueId = VenueId("")
    is_maker: bool = False


# --- regime ----------------------------------------------------------------


class Regime(Enum):
    """Detected market regime — gates strategies on/off (§2.4, §6.2, §7.2)."""

    TREND_UP = "trend_up"
    TREND_DOWN = "trend_down"
    RANGE = "range"
    HIGH_VOL = "high_vol"
    UNKNOWN = "unknown"


# --- risk tiers ------------------------------------------------------------


class RiskTier(Enum):
    """Strategy risk tier — sets static risk budget and gating aggressiveness (§6.2)."""

    FOUNDATION = 1  # trend / breakout — largest budget, positive skew
    CORE = 2        # x-sectional momentum, meta-label ML, learned patterns
    TACTICAL = 3    # mean-reversion / short-horizon — smallest budget, hard stops


@dataclass(frozen=True, slots=True)
class Label:
    """Triple-barrier label for one event (§2.2).

    ``outcome`` is +1 (take-profit hit first), -1 (stop hit first) or 0 (time
    barrier). ``weight`` down-weights overlapping/concurrent labels (§2.2).
    """

    symbol: Symbol
    event_ts: datetime
    outcome: int
    ret: float
    touch_ts: datetime
    weight: float = 1.0
    meta: dict = field(default_factory=dict)
