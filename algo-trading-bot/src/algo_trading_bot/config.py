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


class BotConfig(BaseModel):
    name: str = "atb"
    horizon: Horizon = Horizon.SWING
    venue: VenueConfig
    universe: list[str] = Field(default_factory=lambda: ["BTC"], description="symbols to trade")
    bar_interval: str = "1h"  # default 1h swing / 1d position; see core/types.Horizon
    friction: FrictionConfig = FrictionConfig()
    risk: RiskConfig = RiskConfig()
    validation: ValidationConfig = ValidationConfig()
    data_dir: str = "./data"

    model_config = {"use_enum_values": False}
