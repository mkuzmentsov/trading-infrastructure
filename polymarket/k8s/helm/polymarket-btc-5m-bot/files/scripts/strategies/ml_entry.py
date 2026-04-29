from __future__ import annotations

import math

from config import (
    ENTRY_GATE_CHEAP_OVERRIDE_EDGE,
    ENTRY_GATE_CHEAP_OVERRIDE_SCORE,
    ENTRY_GATE_THRESHOLD,
    ENTRY_GATE_MIN_PRICE,
    ENTRY_ORDER_MODE,
    HOLD_TO_EXPIRY_DEFAULT,
    ML_ENTRY_BASE_STOP_LOSS,
    ML_ENTRY_DOMINANT_EDGE_FLOOR,
    ML_ENTRY_DOMINANT_ENTRY_FRACTION,
    ML_ENTRY_FORCE_EXIT_SECS,
    ML_ENTRY_LATE_BAR_CUT_SECS,
    ML_ENTRY_LATE_BAR_POSITIVE_FLOOR,
    ML_ENTRY_LATE_BAR_POSITIVE_SECS,
    ML_ENTRY_LATE_STOP_LOSS,
    ML_ENTRY_LATE_STOP_SECS,
    ML_ENTRY_THESIS_ENTRY_FRACTION,
    ML_ENTRY_THESIS_FLOOR_MIN,
    ML_ENTRY_THESIS_PROFIT_LOCK,
    ML_ENTRY_TRAILING_ARM_GAIN,
    ML_ENTRY_TRAILING_GAP,
    log,
)
from entry_gate_ml import MODEL_PATH as ENTRY_GATE_MODEL_PATH
from entry_gate_ml import predict_entry_score
from math_signal import generate_signal
from positions import Position

from .base import PositionDecision, StrategyContext


class MLEntryStrategy:
    name = "pm_btc_ml-entry"

    def startup_details(self) -> list[str]:
        return [
            f"STRATEGY={self.name}",
            f"ENTRY_MODE={self.entry_order_mode()}  ENTRY_GATE={ENTRY_GATE_MODEL_PATH}",
            f"GATE_TH={ENTRY_GATE_THRESHOLD:.2f}  MIN_PRICE={ENTRY_GATE_MIN_PRICE:.2f}  CHEAP_OVERRIDE_SCORE={ENTRY_GATE_CHEAP_OVERRIDE_SCORE:.2f}",
            f"HOLD_TO_EXPIRY={HOLD_TO_EXPIRY_DEFAULT}  SL={ML_ENTRY_BASE_STOP_LOSS:.2f}/{ML_ENTRY_LATE_STOP_LOSS:.2f}  TRAIL={ML_ENTRY_TRAILING_ARM_GAIN:.2f}/{ML_ENTRY_TRAILING_GAP:.2f}",
        ]

    def entry_order_mode(self) -> str:
        return ENTRY_ORDER_MODE

    def entry_hold_to_expiry(self) -> bool:
        return HOLD_TO_EXPIRY_DEFAULT

    def _generate_entry_signal(self, ctx: StrategyContext):
        signal = generate_signal(
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
        return signal

    def evaluate_entry(self, ctx: StrategyContext):
        signal = self._generate_entry_signal(ctx)
        if signal.action not in {"BUY_UP", "BUY_DOWN"}:
            return signal

        gate_score = predict_entry_score(ctx, signal)
        signal.debug["entry_gate_score"] = round(gate_score, 4) if gate_score is not None else None
        if gate_score is None:
            signal.action = "NO_TRADE"
            signal.price = None
            signal.size = 0
            signal.reason = "Entry gate model unavailable"
            return signal

        if gate_score < ENTRY_GATE_THRESHOLD:
            signal.action = "NO_TRADE"
            signal.price = None
            signal.size = 0
            signal.reason = f"Entry gate below threshold ({gate_score:.3f} < {ENTRY_GATE_THRESHOLD:.3f})"
            return signal

        price = float(signal.price or 0.0)
        if price < ENTRY_GATE_MIN_PRICE:
            cheap_override = gate_score >= ENTRY_GATE_CHEAP_OVERRIDE_SCORE and signal.edge >= ENTRY_GATE_CHEAP_OVERRIDE_EDGE
            signal.debug["cheap_override"] = cheap_override
            if not cheap_override:
                signal.action = "NO_TRADE"
                signal.price = None
                signal.size = 0
                signal.reason = (
                    f"Cheap entry veto (price={price:.3f} < {ENTRY_GATE_MIN_PRICE:.3f}, "
                    f"score={gate_score:.3f}, edge={signal.edge:.3f})"
                )
                return signal

        return signal

    def evaluate_position(self, ctx: StrategyContext, pos: Position, current_bid: float, now: float) -> PositionDecision:
        unrealized = current_bid - pos.entry_price
        pos.peak_bid = max(pos.peak_bid, current_bid)

        stop_gap = ML_ENTRY_LATE_STOP_LOSS if ctx.seconds_left <= ML_ENTRY_LATE_STOP_SECS else ML_ENTRY_BASE_STOP_LOSS
        if current_bid <= pos.entry_price - stop_gap:
            return PositionDecision(exit_reason="stop_loss")

        trailing_armed = pos.peak_bid >= pos.entry_price + ML_ENTRY_TRAILING_ARM_GAIN
        if trailing_armed and current_bid <= pos.peak_bid - ML_ENTRY_TRAILING_GAP:
            return PositionDecision(exit_reason="trailing_stop")

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
        if pos.direction == "UP":
            current_side_edge = float(signal.debug.get("net_up", signal.edge if signal.action == "BUY_UP" else 0.0))
        else:
            current_side_edge = float(signal.debug.get("net_down", signal.edge if signal.action == "BUY_DOWN" else 0.0))

        thesis_floor = max(ML_ENTRY_THESIS_FLOOR_MIN, pos.entry_edge * ML_ENTRY_THESIS_ENTRY_FRACTION)
        if unrealized >= ML_ENTRY_THESIS_PROFIT_LOCK and current_side_edge < thesis_floor:
            return PositionDecision(signal=signal, current_side_edge=current_side_edge, exit_reason="thesis_decay")

        if ctx.seconds_left <= ML_ENTRY_LATE_BAR_CUT_SECS and unrealized < 0:
            return PositionDecision(signal=signal, current_side_edge=current_side_edge, exit_reason="late_bar_cut")

        dominant_edge_floor = max(ML_ENTRY_DOMINANT_EDGE_FLOOR, pos.entry_edge * ML_ENTRY_DOMINANT_ENTRY_FRACTION)
        clearly_dominant = current_side_edge >= dominant_edge_floor
        if (
            ctx.seconds_left <= ML_ENTRY_LATE_BAR_POSITIVE_SECS
            and unrealized < ML_ENTRY_LATE_BAR_POSITIVE_FLOOR
            and not clearly_dominant
        ):
            return PositionDecision(signal=signal, current_side_edge=current_side_edge, exit_reason="late_bar_fade")

        if ctx.seconds_left <= ML_ENTRY_FORCE_EXIT_SECS:
            return PositionDecision(signal=signal, current_side_edge=current_side_edge, exit_reason="force_close")

        return PositionDecision(signal=signal, current_side_edge=current_side_edge)
