"""
Hyperliquid (perpetual) <-> WhiteBIT (spot) Arbitrage Strategy
==============================================================

Two complementary approaches run simultaneously:

1. INSTANT PRICE ARB
   Buy on the cheaper leg, sell on the expensive leg when the net spread
   (after fees on both sides) exceeds `min_profitability`.

2. BASIS / FUNDING ARB  (delta-neutral carry)
   When HL perpetual trades at a persistent premium over WB spot AND
   the funding rate is positive (longs pay shorts):
     - Buy WB spot  +  Short HL perp   → earn premium convergence + funding
   Unwind when basis narrows below `close_basis_threshold`.

Configuration is loaded from conf/scripts/hl_wb_arb.yml (templated by Helm).
"""

from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from pydantic import Field

from hummingbot.client.config.config_data_types import BaseClientModel
from hummingbot.connector.connector_base import ConnectorBase
from hummingbot.core.data_type.common import OrderType, TradeType
from hummingbot.strategy.script_strategy_base import ScriptStrategyBase


# ---------------------------------------------------------------------------
# Configuration schema (loaded from conf/scripts/hl_wb_arb.yml)
# ---------------------------------------------------------------------------

class PairConfig(BaseClientModel):
    hl: str = Field("BTC-USDC", description="Hyperliquid perpetual trading pair")
    wb: str = Field("BTC_USDT", description="WhiteBIT spot trading pair")
    order_amount: Decimal = Field(Decimal("0.001"), description="Order size in base asset")


class HLWBArbitrageConfig(BaseClientModel):
    script_file_name: str = Field(default_factory=lambda: os.path.basename(__file__))

    # Connectors
    hl_connector: str = Field("hyperliquid_perpetual", description="Hyperliquid connector name")
    wb_connector: str = Field("whitebit", description="WhiteBIT connector name")

    # Pairs to trade
    trading_pairs: List[PairConfig] = Field(
        default=[
            PairConfig(hl="BTC-USDC", wb="BTC_USDT", order_amount=Decimal("0.001")),
            PairConfig(hl="ETH-USDC", wb="ETH_USDT", order_amount=Decimal("0.01")),
        ],
        description="List of pair configurations"
    )

    # Instant arb
    min_profitability: Decimal = Field(Decimal("0.002"), description="Min net profit % to execute instant arb")

    # Basis/funding arb
    open_basis_threshold: Decimal = Field(Decimal("0.003"), description="Open carry trade when basis > this")
    close_basis_threshold: Decimal = Field(Decimal("0.0005"), description="Close carry trade when basis < this")
    min_funding_rate: Decimal = Field(Decimal("0.0001"), description="Minimum HL funding rate to open carry trade")

    # Exchange fees (taker)
    hl_fee_pct: Decimal = Field(Decimal("0.00035"), description="Hyperliquid taker fee")
    wb_fee_pct: Decimal = Field(Decimal("0.001"), description="WhiteBIT taker fee")


# ---------------------------------------------------------------------------
# Strategy
# ---------------------------------------------------------------------------

import os
import time


class HLWBArbitrage(ScriptStrategyBase):
    """
    Hyperliquid-WhiteBIT cross-exchange arbitrage.
    Supports BTC, ETH, or any pair configured in the YAML config.
    """

    # Populated dynamically from config
    markets: Dict[str, set] = {}

    @classmethod
    def init_markets(cls, config: HLWBArbitrageConfig):
        hl_pairs = {p.hl for p in config.trading_pairs}
        wb_pairs = {p.wb for p in config.trading_pairs}
        cls.markets = {
            config.hl_connector: hl_pairs,
            config.wb_connector: wb_pairs,
        }

    def __init__(self, connectors: Dict[str, ConnectorBase], config: HLWBArbitrageConfig):
        super().__init__(connectors)
        self.config = config
        self._last_trade_ts: Dict[str, float] = {}  # pair → last trade timestamp
        self._cooldown_s = 30  # seconds between trades on same pair
        self._carry_positions: Dict[str, str] = {}  # pair → "long_wb_short_hl" | "long_hl_short_wb"

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def on_tick(self):
        for pair in self.config.trading_pairs:
            if self._is_cooling_down(pair.hl):
                continue
            prices = self._get_prices(pair)
            if prices is None:
                continue
            hl_bid, hl_ask, wb_bid, wb_ask = prices

            # 1. Try instant arb first (fastest profit)
            if self._try_instant_arb(pair, hl_bid, hl_ask, wb_bid, wb_ask):
                self._last_trade_ts[pair.hl] = time.time()
                continue

            # 2. Try basis/funding carry trade
            self._manage_carry_trade(pair, hl_bid, hl_ask, wb_bid, wb_ask)

    # ------------------------------------------------------------------
    # Instant price arbitrage
    # ------------------------------------------------------------------

    def _try_instant_arb(
        self,
        pair: PairConfig,
        hl_bid: Decimal, hl_ask: Decimal,
        wb_bid: Decimal, wb_ask: Decimal,
    ) -> bool:
        """Returns True if an arb order was placed."""

        # Direction 1: HL at premium → sell HL perp, buy WB spot
        prof_1 = self._net_profit(buy_price=wb_ask, sell_price=hl_bid,
                                   buy_fee=self.config.wb_fee_pct,
                                   sell_fee=self.config.hl_fee_pct)

        # Direction 2: HL at discount → buy HL perp, sell WB spot
        prof_2 = self._net_profit(buy_price=hl_ask, sell_price=wb_bid,
                                   buy_fee=self.config.hl_fee_pct,
                                   sell_fee=self.config.wb_fee_pct)

        if prof_1 >= self.config.min_profitability:
            self.logger().info(
                f"[INSTANT ARB] {pair.hl} Dir1 | profit={prof_1:.4%} "
                f"| Buy WB @ {wb_ask} | Sell HL @ {hl_bid}"
            )
            self.buy(self.config.wb_connector, pair.wb, pair.order_amount, OrderType.MARKET)
            self.sell(self.config.hl_connector, pair.hl, pair.order_amount, OrderType.MARKET)
            return True

        if prof_2 >= self.config.min_profitability:
            self.logger().info(
                f"[INSTANT ARB] {pair.hl} Dir2 | profit={prof_2:.4%} "
                f"| Buy HL @ {hl_ask} | Sell WB @ {wb_bid}"
            )
            self.buy(self.config.hl_connector, pair.hl, pair.order_amount, OrderType.MARKET)
            self.sell(self.config.wb_connector, pair.wb, pair.order_amount, OrderType.MARKET)
            return True

        return False

    # ------------------------------------------------------------------
    # Basis / funding carry trade
    # ------------------------------------------------------------------

    def _manage_carry_trade(
        self,
        pair: PairConfig,
        hl_bid: Decimal, hl_ask: Decimal,
        wb_bid: Decimal, wb_ask: Decimal,
    ):
        basis = (hl_bid - wb_ask) / wb_ask  # positive = HL premium
        funding = self._get_funding_rate(pair.hl)
        position = self._carry_positions.get(pair.hl)

        if position is None:
            # Open: HL premium + positive funding → short HL, long WB spot
            if basis >= self.config.open_basis_threshold and funding >= self.config.min_funding_rate:
                self.logger().info(
                    f"[CARRY OPEN] {pair.hl} | basis={basis:.4%} | funding={funding:.6f} "
                    f"| Buy WB @ {wb_ask} | Short HL @ {hl_bid}"
                )
                self.buy(self.config.wb_connector, pair.wb, pair.order_amount, OrderType.MARKET)
                self.sell(self.config.hl_connector, pair.hl, pair.order_amount, OrderType.MARKET)
                self._carry_positions[pair.hl] = "long_wb_short_hl"
                self._last_trade_ts[pair.hl] = time.time()

            # Open: HL discount + negative funding → long HL, short WB spot
            elif basis <= -self.config.open_basis_threshold and funding <= -self.config.min_funding_rate:
                self.logger().info(
                    f"[CARRY OPEN] {pair.hl} | basis={basis:.4%} | funding={funding:.6f} "
                    f"| Buy HL @ {hl_ask} | Sell WB @ {wb_bid}"
                )
                self.buy(self.config.hl_connector, pair.hl, pair.order_amount, OrderType.MARKET)
                self.sell(self.config.wb_connector, pair.wb, pair.order_amount, OrderType.MARKET)
                self._carry_positions[pair.hl] = "long_hl_short_wb"
                self._last_trade_ts[pair.hl] = time.time()

        else:
            # Close when basis converges
            if abs(basis) <= self.config.close_basis_threshold:
                self.logger().info(
                    f"[CARRY CLOSE] {pair.hl} | basis={basis:.4%} | closing position: {position}"
                )
                if position == "long_wb_short_hl":
                    # Unwind: sell WB spot, buy back HL perp (close short)
                    self.sell(self.config.wb_connector, pair.wb, pair.order_amount, OrderType.MARKET)
                    self.buy(self.config.hl_connector, pair.hl, pair.order_amount, OrderType.MARKET)
                else:
                    # Unwind: sell HL perp, buy back WB spot
                    self.sell(self.config.hl_connector, pair.hl, pair.order_amount, OrderType.MARKET)
                    self.buy(self.config.wb_connector, pair.wb, pair.order_amount, OrderType.MARKET)

                del self._carry_positions[pair.hl]
                self._last_trade_ts[pair.hl] = time.time()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_prices(self, pair: PairConfig) -> Optional[Tuple[Decimal, Decimal, Decimal, Decimal]]:
        try:
            hl = self.connectors[self.config.hl_connector]
            wb = self.connectors[self.config.wb_connector]
            hl_bid = hl.get_price(pair.hl, is_buy=False)
            hl_ask = hl.get_price(pair.hl, is_buy=True)
            wb_bid = wb.get_price(pair.wb, is_buy=False)
            wb_ask = wb.get_price(pair.wb, is_buy=True)
            if not all([hl_bid, hl_ask, wb_bid, wb_ask]):
                return None
            return hl_bid, hl_ask, wb_bid, wb_ask
        except Exception as e:
            self.logger().warning(f"Price fetch error for {pair.hl}: {e}")
            return None

    def _get_funding_rate(self, hl_pair: str) -> Decimal:
        """Returns current HL perpetual funding rate, or 0 on error."""
        try:
            hl = self.connectors[self.config.hl_connector]
            funding_info = hl.get_funding_info(hl_pair)
            return Decimal(str(funding_info.rate)) if funding_info else Decimal("0")
        except Exception:
            return Decimal("0")

    @staticmethod
    def _net_profit(buy_price: Decimal, sell_price: Decimal,
                    buy_fee: Decimal, sell_fee: Decimal) -> Decimal:
        cost = buy_price * (1 + buy_fee)
        revenue = sell_price * (1 - sell_fee)
        return (revenue - cost) / cost

    def _is_cooling_down(self, hl_pair: str) -> bool:
        last = self._last_trade_ts.get(hl_pair, 0)
        return (time.time() - last) < self._cooldown_s

    # ------------------------------------------------------------------
    # Status display
    # ------------------------------------------------------------------

    def format_status(self) -> str:
        lines = [
            "",
            "  Hyperliquid ↔ WhiteBIT Arbitrage",
            "  " + "=" * 42,
        ]
        for pair in self.config.trading_pairs:
            prices = self._get_prices(pair)
            carry = self._carry_positions.get(pair.hl, "none")
            if prices:
                hl_bid, hl_ask, wb_bid, wb_ask = prices
                basis = (hl_bid - wb_ask) / wb_ask * 100
                funding = self._get_funding_rate(pair.hl)
                prof_1 = self._net_profit(wb_ask, hl_bid, self.config.wb_fee_pct, self.config.hl_fee_pct)
                prof_2 = self._net_profit(hl_ask, wb_bid, self.config.hl_fee_pct, self.config.wb_fee_pct)
                lines += [
                    f"  {pair.hl} / {pair.wb}",
                    f"    HL  bid={hl_bid:.4f}  ask={hl_ask:.4f}",
                    f"    WB  bid={wb_bid:.4f}  ask={wb_ask:.4f}",
                    f"    Basis:   {basis:+.4f}%   Funding: {float(funding):.6f}",
                    f"    Arb P/L: Dir1={prof_1:.4%}  Dir2={prof_2:.4%}",
                    f"    Carry position: {carry}",
                    "",
                ]
            else:
                lines.append(f"  {pair.hl}: waiting for prices...")
        return "\n".join(lines)
