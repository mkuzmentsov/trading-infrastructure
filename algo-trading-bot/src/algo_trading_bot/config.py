"""Typed configuration (pydantic v2).

A run is pinned to (data snapshot + code commit + config) for reproducibility
(§3.4, NFR2). This module defines the config half; the engine stamps commit +
data snapshot at run time. One venue is active per run (§2.1, NFR5).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from .core.types import Horizon


class VenueConfig(BaseModel):
    name: str = Field(description="'hyperliquid' | 'kraken'")
    testnet: bool = True
    # Capital per exchange is bounded and configurable (NFR5, §5 counterparty risk).
    max_capital_quote: float = Field(0.0, ge=0, description="hard cap on capital at this venue")
    # Credentials are resolved from env / secret store by the adapter, never stored here.


class FrictionConfig(BaseModel):
    """Realistic friction is non-optional (§3.2)."""

    maker_fee_bps: float = 1.0
    taker_fee_bps: float = 4.5
    slippage_model: str = "size_scaled"   # see backtest/friction.py
    latency_ms: int = 250                 # signal-to-fill latency
    funding_enabled: bool = True


class RiskConfig(BaseModel):
    """Hard limits — absolute precedence over signals (§2.5, §7.2)."""

    max_gross_leverage: float = 2.0
    max_position_notional: float = Field(0.0, ge=0)  # per instrument; 0 = derive from capital
    target_annual_vol: float = 0.20                  # vol targeting (§2.4)
    kelly_fraction: float = 0.5                      # fraction-of-Kelly cap, <= 0.5 (§5)
    drawdown_derisk: float = 0.10                    # tier-1 breaker: start de-risking
    drawdown_halt: float = 0.20                      # tier-2 breaker: flatten + halt
    min_trade_notional: float = 10.0                 # don't trade dust (§7.5)
    rebalance_deadband: float = 0.05                 # hysteresis around target (§7.3)


class ValidationConfig(BaseModel):
    """The approve-for-live gate (§4)."""

    n_splits: int = 6
    embargo_pct: float = 0.01
    cpcv_groups: int = 6
    cpcv_test_groups: int = 2
    max_pbo: float = 0.30           # reject if Prob. of Backtest Overfitting exceeds
    min_deflated_sharpe: float = 0.0
    require_paper_gate: bool = True


class TrendConfig(BaseModel):
    """Tier-1 trend baseline knobs (strategy/baseline_trend.py)."""

    ema_fast: int = 20
    ema_slow: int = 100
    vol_window: int = 48
    scale: float = 10.0  # maps the trend/vol ratio into ~[-1, 1] via tanh


class RegimeConfig(BaseModel):
    """Regime gate (§2.4). ``mode`` controls how the detected regime acts on the trend
    forecast — the experiment knob for taming the flicker churn of the hard gate."""

    mode: str = "soft"            # "hard" (on/off) | "hysteresis" (debounced on/off) | "soft" (ER-scaled)
    # default "soft": validated winner on btc_1d (OOS Sharpe 0.62->0.78, DSR 0.732->0.788) — the
    # continuous ER weight de-risks chop without the flatten/reopen churn the hard gate suffers.
    er_trend: float = 0.30        # efficiency-ratio cutoff: ER>=this -> trending
    vol_pct_high: float = 0.90    # vol percentile -> HIGH_VOL
    persist: int = 3              # hysteresis: bars a new regime must persist before it switches
    soft_er_lo: float = 0.15      # soft: ER at/below this -> weight 0 (full chop)
    soft_er_hi: float = 0.45      # soft: ER at/above this -> weight 1 (full trend)


class XSecConfig(BaseModel):
    """Cross-sectional momentum (Tier-2, §6.2) — panel-backtest knobs."""

    lookback: int = 30        # momentum formation window (bars)
    skip: int = 0             # skip most-recent bars (reversal/microstructure hygiene)
    top_frac: float = 0.3     # long top frac, short bottom frac of the ranked universe
    rebalance: int = 7        # rebalance every N bars
    leverage: float = 1.0     # gross exposure multiplier (sum|w| = leverage)


class BotConfig(BaseModel):
    name: str = "atb"
    horizon: Horizon = Horizon.SWING
    venue: VenueConfig
    universe: list[str] = Field(default_factory=lambda: ["BTC"], description="symbols to trade")
    # Data is ingested independently of the trade venue (§2.1): e.g. fetch deep history
    # from Binance, trade on Hyperliquid. None -> read whatever venue is in the store.
    data_venue: str | None = None
    bar_interval: str = "1h"  # default 1h swing / 1d position; see core/types.Horizon
    starting_cash: float = 10_000.0
    trend: TrendConfig = TrendConfig()
    regime: RegimeConfig = RegimeConfig()
    xsec: XSecConfig = XSecConfig()
    friction: FrictionConfig = FrictionConfig()
    risk: RiskConfig = RiskConfig()
    validation: ValidationConfig = ValidationConfig()
    data_dir: str = "./data"

    model_config = {"use_enum_values": False}
