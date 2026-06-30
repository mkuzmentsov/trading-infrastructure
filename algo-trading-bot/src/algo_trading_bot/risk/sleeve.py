"""Segregated 'degen' sleeve — a hard-capped, ring-fenced high-risk allocation (experiment #19).

The user is risk-accepting and wants a high-leverage outlet. Survival rule (principle #5): that outlet
must be PHYSICALLY UNABLE to harm the core book. This composes two fully independent `PanelPaperBook`s:

  * CORE  — the validated daily-trend book (`tstrend_multiwindow_aggr`), the bulk of capital.
  * DEGEN — a small allocation (default 3%) that may run high leverage and may go to zero.

The isolation guarantees (each is unit-tested in `tests/test_sleeve.py`):
  1. SEPARATE CASH. The two books never share cash. `core.equity` is a pure function of core fills and
     is byte-identical regardless of what degen does — a degen −100% leaves core untouched.
  2. BOUNDED LOSS. Degen cannot lose more than its allocation. Models isolated-margin: if degen equity
     hits the liquidation floor it is flattened and floored at 0 (the exchange liquidates the SUBACCOUNT;
     it cannot claw back from core). You can lose the 3%, never a cent more.
  3. PERMANENT KILL-SWITCH. A `DrawdownBreaker` on degen NAV (aggressive thresholds) de-risks then HALTS
     (flatten + stop opening) — and once halted it stays halted until a manual `reset()` (ops decision,
     never automatic). A halted sleeve cannot re-open on its own.

This is the plumbing #19 is about; the high-leverage STRATEGY that runs inside it is #20, and its
risk-of-ruin sizing is #21. Mirrors a real exchange where the degen lives in its own isolated-margin
subaccount with its own transfer-in cap.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..config import RiskConfig
from ..engine.panel_paper import PanelPaperBook
from .drawdown import DrawdownBreaker


@dataclass
class SegregatedSleeves:
    """Two isolated books (core + degen) sharing nothing but a read-only total-equity view."""

    core: PanelPaperBook
    degen: PanelPaperBook
    breaker: DrawdownBreaker
    degen_alloc: float                 # the capital ring-fenced to degen at inception (the max loss)
    liq_floor_frac: float = 0.0        # degen equity / alloc at/below which the subaccount is liquidated
    history: list[dict] = field(default_factory=list)

    @classmethod
    def new(cls, total_cash: float, *, degen_fraction: float = 0.03, fee_bps: float = 4.5,
            degen_derisk: float = 0.50, degen_halt: float = 0.90, liq_floor_frac: float = 0.0,
            ) -> "SegregatedSleeves":
        """Carve `degen_fraction` of `total_cash` into the ring-fenced book; the rest stays in core.

        `degen_derisk`/`degen_halt` are drawdown tiers on the DEGEN NAV (aggressive by design: start
        cutting at −50% of sleeve, hard-halt at −90%). `liq_floor_frac` is the isolated-margin wipeout
        level as a fraction of the original allocation (0.0 = lose it all before the account is closed).
        """
        if not 0.0 <= degen_fraction <= 0.25:
            raise ValueError(f"degen_fraction {degen_fraction} outside sane [0, 0.25] — refuse to over-allocate risk")
        degen_alloc = total_cash * degen_fraction
        core = PanelPaperBook.new(total_cash - degen_alloc, fee_bps)
        degen = PanelPaperBook.new(degen_alloc, fee_bps)
        risk = RiskConfig(drawdown_derisk=degen_derisk, drawdown_halt=degen_halt)
        return cls(core=core, degen=degen, breaker=DrawdownBreaker(risk),
                   degen_alloc=degen_alloc, liq_floor_frac=liq_floor_frac)

    # --- per-bar step ---
    def step(self, core_w: dict[str, float], degen_w: dict[str, float],
             prices: dict[str, float], ts: str) -> dict:
        """Advance both books one bar. Core rebalances to its targets unconditionally. Degen's targets
        are gated by its own kill-switch, and the sleeve is liquidated (flattened, floored at 0, halted)
        if its NAV breaches the isolated-margin floor. Returns a combined step record."""
        core_rec = self.core.rebalance_to(core_w, prices, ts)

        degen_eq = self.degen.equity(prices)
        factor = self.breaker.update(degen_eq)          # kill-switch: 1→0 across the degen DD tiers

        liquidated = degen_eq <= self.liq_floor_frac * self.degen_alloc
        if liquidated or self.breaker.halted:
            self.degen.rebalance_to({}, prices, ts)     # flatten
            if liquidated:
                self.degen.cash = max(self.degen.cash, 0.0)   # isolated margin: loss capped at allocation
                self.breaker.halted = True
        else:
            gated = {s: w * factor for s, w in degen_w.items()}
            self.degen.rebalance_to(gated, prices, ts)

        rec = {
            "ts": ts,
            "total_equity": round(self.equity(prices), 2),
            "core_equity": round(self.core.equity(prices), 2),
            "degen_equity": round(self.degen.equity(prices), 2),
            "degen_factor": round(factor, 3),
            "degen_halted": self.breaker.halted,
        }
        self.history.append(rec)
        return rec

    def equity(self, prices: dict[str, float]) -> float:
        """Total account = core + degen. Core alone is unaffected by degen's fate (guarantee #1)."""
        return self.core.equity(prices) + self.degen.equity(prices)

    def reset_degen(self) -> None:
        """Re-arm the halted sleeve — an explicit ops decision, never automatic (guarantee #3)."""
        self.breaker.reset()
