from __future__ import annotations

import math

from config import (
    HOLD_TO_EXPIRY_DEFAULT,
    SIGNAL_EXIT_EDGE,
    SL_ARM_DELAY_SECS,
    SL_MIN_ADVERSE_BTC,
    STOP_LOSS,
    TAKE_PROFIT,
    THESIS_EDGE_FRACTION,
    THESIS_MIN_BTC_DISTANCE,
    THESIS_MIN_EDGE,
    THESIS_PROFIT_LOCK,
    TRAILING_ARM_GAIN,
    TRAILING_STOP_GAP,
    ULTRA_CHEAP_SL_DELAY_SECS,
    ULTRA_CHEAP_TAIL_PRICE,
    log,
)
from math_signal import (
    LATE_ENTRY_EDGE_DISCOUNT,
    LATE_ENTRY_SECS,
    MIN_BTC_DISTANCE,
    MIN_BOOK_DIVERGENCE,
    generate_signal,
)
from positions import Position

from .base import PositionDecision, StrategyContext


class LatencyArbHoldStrategy:
    name = "latency_arb_hold"

    def startup_details(self) -> list[str]:
        return [
            f"STRATEGY={self.name}",
            f"HOLD_TO_EXPIRY={HOLD_TO_EXPIRY_DEFAULT}  MIN_BTC_DIST={MIN_BTC_DISTANCE:.5f}  MIN_BOOK_DIV={MIN_BOOK_DIVERGENCE:.3f}",
            f"LATE_SECS={LATE_ENTRY_SECS}  LATE_DISCOUNT={LATE_ENTRY_EDGE_DISCOUNT:.2f}",
        ]

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
            model_p_up=ctx.ml_p_up,
            binance_price=ctx.binance_price,
        )

    def evaluate_position(self, ctx: StrategyContext, pos: Position, current_bid: float, now: float) -> PositionDecision:
        unrealized = current_bid - pos.entry_price
        trailing_armed = pos.peak_bid >= pos.entry_price + TRAILING_ARM_GAIN
        trailing_in_profit = unrealized >= max(THESIS_PROFIT_LOCK, TRAILING_STOP_GAP)
        if trailing_armed and trailing_in_profit and current_bid <= pos.peak_bid - TRAILING_STOP_GAP and not pos.sell_order_id:
            log.info(
                "TRAILING_STOP  bid=%.4f  peak=%.4f  entry=%.4f  drawdown=%.4f",
                current_bid,
                pos.peak_bid,
                pos.entry_price,
                pos.peak_bid - current_bid,
            )
            return PositionDecision(exit_reason="trailing_stop")

        if unrealized >= TAKE_PROFIT and not (pos.sell_order_id and pos.exit_reason == "take_profit"):
            if not pos.take_profit_armed:
                pos.take_profit_armed = True
                pos.take_profit_floor = pos.entry_price + 0.01
                log.info(
                    "TAKE_PROFIT_ARMED  entry=%.4f  floor=%.4f",
                    pos.entry_price,
                    pos.take_profit_floor,
                )
            log.info(
                "TAKE_PROFIT  bid=%.4f  entry=%.4f  pnl=%.4f  threshold=%.4f  floor=%.4f",
                current_bid,
                pos.entry_price,
                unrealized,
                TAKE_PROFIT,
                pos.take_profit_floor,
            )
            return PositionDecision(exit_reason="take_profit")

        stop_loss_gap = STOP_LOSS
        if ctx.seconds_left <= 90:
            stop_loss_gap *= 0.75

        if (
            pos.sell_order_id
            and pos.exit_reason == "take_profit"
            and current_bid <= pos.entry_price - stop_loss_gap
        ):
            log.info(
                "TAKE_PROFIT abandoned — bid=%.4f fell to SL line  entry=%.4f  gap=%.4f  order=%s",
                current_bid, pos.entry_price, stop_loss_gap, pos.sell_order_id,
            )

        if ctx.seconds_left <= 45 and unrealized <= -0.05:
            stale_tp_resting = pos.sell_order_id and pos.exit_reason in {"take_profit", "thesis_decay", "trailing_stop"}
            if not pos.sell_order_id or stale_tp_resting:
                log.info(
                    "LATE_BAR_CUT  secs_left=%d  bid=%.4f  entry=%.4f  pnl=%.4f",
                    ctx.seconds_left, current_bid, pos.entry_price, unrealized,
                )
                return PositionDecision(exit_reason="late_bar_cut")

        time_held = now - pos.entry_time
        is_ultra_cheap = pos.entry_price <= ULTRA_CHEAP_TAIL_PRICE
        sl_delay = ULTRA_CHEAP_SL_DELAY_SECS if is_ultra_cheap else SL_ARM_DELAY_SECS
        sl_armed = time_held >= sl_delay

        hard_exit_active = pos.sell_order_id and pos.exit_reason in {"stop_loss", "trailing_stop", "take_profit"}
        if current_bid <= pos.entry_price - stop_loss_gap and not hard_exit_active:
            if not sl_armed:
                log.debug(
                    "STOP_LOSS suppressed — hold time %.0fs < delay %ds  bid=%.4f  entry=%.4f",
                    time_held, sl_delay, current_bid, pos.entry_price,
                )
            else:
                btc_distance = math.log(ctx.current_price / ctx.bar_open) if ctx.bar_open > 0 else 0.0
                adverse_move = btc_distance if pos.direction == "DOWN" else -btc_distance
                bid_collapse = current_bid <= pos.entry_price - 2 * stop_loss_gap
                gate_active = adverse_move < SL_MIN_ADVERSE_BTC and ctx.seconds_left > 60 and not bid_collapse
                if gate_active:
                    log.info(
                        "STOP_LOSS suppressed — BTC not adverse enough  bid=%.4f  entry=%.4f  adverse_btc=%.4f  required=%.4f  secs_left=%d",
                        current_bid, pos.entry_price, adverse_move, SL_MIN_ADVERSE_BTC, ctx.seconds_left,
                    )
                else:
                    log.info(
                        "STOP_LOSS  bid=%.4f  entry=%.4f  loss=%.4f  threshold=%.4f  held=%.0fs  adverse_btc=%.4f  late_bar=%s  bid_collapse=%s",
                        current_bid, pos.entry_price, pos.entry_price - current_bid, stop_loss_gap, time_held, adverse_move,
                        ctx.seconds_left <= 60, bid_collapse,
                    )
                    return PositionDecision(exit_reason="stop_loss")

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
            model_p_up=ctx.ml_p_up,
            require_budget=False,
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

        thesis_floor = max(THESIS_MIN_EDGE, pos.entry_edge * THESIS_EDGE_FRACTION)
        btc_distance = math.log(ctx.current_price / ctx.bar_open) if ctx.bar_open > 0 else 0.0
        bar_winning = (
            (pos.direction == "DOWN" and btc_distance < -THESIS_MIN_BTC_DISTANCE)
            or (pos.direction == "UP" and btc_distance > THESIS_MIN_BTC_DISTANCE)
        )
        if (
            unrealized >= THESIS_PROFIT_LOCK
            and current_side_edge < thesis_floor
            and not bar_winning
            and not (pos.sell_order_id and pos.exit_reason == "thesis_decay")
        ):
            log.info(
                "THESIS_DECAY  dir=%s  bid=%.4f  entry=%.4f  pnl=%.4f  edge_now=%.4f  edge_floor=%.4f  btc_dist=%.4f",
                pos.direction,
                current_bid,
                pos.entry_price,
                unrealized,
                current_side_edge,
                thesis_floor,
                btc_distance,
            )
            return PositionDecision(signal=signal, current_side_edge=current_side_edge, exit_reason="thesis_decay")
        if bar_winning and unrealized >= THESIS_PROFIT_LOCK and current_side_edge < thesis_floor:
            log.info(
                "THESIS_DECAY suppressed — bar winning  dir=%s  bid=%.4f  entry=%.4f  pnl=%.4f  btc_dist=%.4f  threshold=%.4f  edge_now=%.4f",
                pos.direction, current_bid, pos.entry_price, unrealized, btc_distance, THESIS_MIN_BTC_DISTANCE, current_side_edge,
            )

        return PositionDecision(signal=signal, current_side_edge=current_side_edge)
