from __future__ import annotations

from config import (
    AGGRESSIVE_EXIT_SLIPPAGE,
    ENTRY_ORDER_MODE,
    HOLD_TO_EXPIRY_DEFAULT,
    MIN_EXIT_BID,
    SIGNAL_EXIT_EDGE,
    SL_ARM_DELAY_SECS,
    TRAILING_ARM_GAIN,
    TRAILING_STOP_GAP,
    log,
)
from math_signal import generate_signal
from positions import Position

from .base import PositionDecision, StrategyContext


class Profit1Strategy:
    name = "profit_1"

    def startup_details(self) -> list[str]:
        return [
            f"STRATEGY={self.name}",
            f"ENTRY_MODE={self.entry_order_mode()}",
            f"HOLD_TO_EXPIRY={HOLD_TO_EXPIRY_DEFAULT}  ACTIVE_EXITS={not HOLD_TO_EXPIRY_DEFAULT}  SL_ARM_DELAY={SL_ARM_DELAY_SECS}s",
            f"TRAIL_ARM={TRAILING_ARM_GAIN:.2f}  TRAIL_GAP={TRAILING_STOP_GAP:.2f}",
        ]

    def entry_order_mode(self) -> str:
        return ENTRY_ORDER_MODE

    def entry_hold_to_expiry(self) -> bool:
        return HOLD_TO_EXPIRY_DEFAULT

    def evaluate_entry(self, ctx: StrategyContext):
        return generate_signal(
            cash_amount=ctx.cash_amount,
            seconds_left=ctx.seconds_left,
            bar_open=ctx.bar_open,
            current_price=ctx.current_price,
            ret_30s=ctx.ret_30s,
            ret_60s=ctx.ret_60s,
            bid_vol_top=ctx.up_bid_size,
            ask_vol_top=ctx.up_ask_size,
            sigma_5m=ctx.sigma_5m,
            up_bid=ctx.up_bid,
            up_ask=ctx.up_ask,
            down_bid=ctx.down_bid,
            down_ask=ctx.down_ask,
            require_budget=True,
            model_p_up=ctx.ml_p_up,
            binance_price=ctx.binance_price,
        )

    def evaluate_position(self, ctx: StrategyContext, pos: Position, current_bid: float, now: float) -> PositionDecision:
        signal = generate_signal(
            cash_amount=0,
            seconds_left=ctx.seconds_left,
            bar_open=ctx.bar_open,
            current_price=ctx.current_price,
            ret_30s=ctx.ret_30s,
            ret_60s=ctx.ret_60s,
            bid_vol_top=ctx.up_bid_size,
            ask_vol_top=ctx.up_ask_size,
            sigma_5m=ctx.sigma_5m,
            up_bid=ctx.up_bid,
            up_ask=ctx.up_ask,
            down_bid=ctx.down_bid,
            down_ask=ctx.down_ask,
            require_budget=False,
            model_p_up=ctx.ml_p_up,
            binance_price=ctx.binance_price,
        )
        opposite_action = "BUY_DOWN" if pos.direction == "UP" else "BUY_UP"
        if signal.action == opposite_action and signal.edge >= SIGNAL_EXIT_EDGE:
            log.info("SIGNAL_FLIP  holding=%s  new=%s  edge=%.4f", pos.direction, signal.action, signal.edge)
            return PositionDecision(signal=signal, exit_reason="signal_flip")

        if pos.direction == "UP":
            current_side_edge = float(signal.debug.get("net_up", signal.edge if signal.action == "BUY_UP" else 0.0))
        else:
            current_side_edge = float(signal.debug.get("net_down", signal.edge if signal.action == "BUY_DOWN" else 0.0))

        return PositionDecision(signal=signal, current_side_edge=current_side_edge)


def exit_target_price(current_bid: float, reason: str) -> float:
    if reason in {"stop_loss", "signal_flip"}:
        return max(MIN_EXIT_BID, current_bid - AGGRESSIVE_EXIT_SLIPPAGE)
    return max(current_bid, MIN_EXIT_BID)