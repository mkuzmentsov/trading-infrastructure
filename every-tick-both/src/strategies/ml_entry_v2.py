from __future__ import annotations

from config import (
    ENTRY_GATE_CHEAP_OVERRIDE_EDGE,
    ENTRY_GATE_CHEAP_OVERRIDE_SCORE,
    ENTRY_GATE_MIN_PRICE,
    ENTRY_GATE_THRESHOLD,
)
from entry_gate_v2 import MODEL_PATH_V2, predict_entry_score_v2

from .ml_entry import MLEntryStrategy


class MLEntryV2Strategy(MLEntryStrategy):
    name = "pm_btc_ml-entry-v2"

    def startup_details(self) -> list[str]:
        details = super().startup_details()
        details[0] = f"STRATEGY={self.name}"
        details[1] = f"ENTRY_MODE={self.entry_order_mode()}  ENTRY_GATE_V2={MODEL_PATH_V2}"
        return details

    def evaluate_entry(self, ctx):
        signal = self._generate_entry_signal(ctx)
        if signal.action not in {"BUY_UP", "BUY_DOWN"}:
            return signal

        gate = predict_entry_score_v2(ctx, signal)
        if gate is None:
            signal.action = "NO_TRADE"
            signal.price = None
            signal.size = 0
            signal.reason = "Entry gate v2 unavailable"
            return signal

        calibrated = float(gate.get("calibrated", 0.0))
        signal.debug["entry_gate_score_raw"] = round(float(gate.get("raw", 0.0)), 4)
        signal.debug["entry_gate_score"] = round(calibrated, 4)
        signal.debug["entry_gate_closed_form_side_prob"] = round(float(gate.get("closed_form_side_prob", 0.0)), 4)

        if calibrated < ENTRY_GATE_THRESHOLD:
            signal.action = "NO_TRADE"
            signal.price = None
            signal.size = 0
            signal.reason = f"Entry gate v2 below threshold ({calibrated:.3f} < {ENTRY_GATE_THRESHOLD:.3f})"
            return signal

        price = float(signal.price or 0.0)
        if price < ENTRY_GATE_MIN_PRICE:
            cheap_override = calibrated >= ENTRY_GATE_CHEAP_OVERRIDE_SCORE and signal.edge >= ENTRY_GATE_CHEAP_OVERRIDE_EDGE
            signal.debug["cheap_override"] = cheap_override
            if not cheap_override:
                signal.action = "NO_TRADE"
                signal.price = None
                signal.size = 0
                signal.reason = (
                    f"Cheap entry veto v2 (price={price:.3f} < {ENTRY_GATE_MIN_PRICE:.3f}, "
                    f"score={calibrated:.3f}, edge={signal.edge:.3f})"
                )
                return signal

        return signal
