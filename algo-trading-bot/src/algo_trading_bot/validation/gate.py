"""Approve-for-live gate (§4) — itself a deliverable.

"Approved for live" requires clearing EVERY check below. The gate is a hard,
auditable checklist; a model that fails any item does not go live, regardless of how
good its headline Sharpe looks. This encodes principle #4 (beat a dumb baseline or
don't ship) and principle #1 (the harness is the product).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..config import ValidationConfig


@dataclass
class GateCheck:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class GateResult:
    checks: list[GateCheck] = field(default_factory=list)

    @property
    def approved(self) -> bool:
        return bool(self.checks) and all(c.passed for c in self.checks)

    def summary(self) -> str:
        lines = [("PASS" if c.passed else "FAIL") + f"  {c.name}: {c.detail}" for c in self.checks]
        verdict = "APPROVED FOR LIVE" if self.approved else "REJECTED"
        return verdict + "\n" + "\n".join(lines)


class ApproveForLiveGate:
    """Runs the full §4 checklist and returns a GateResult."""

    def __init__(self, config: ValidationConfig) -> None:
        self.config = config

    def evaluate(self, evidence: dict) -> GateResult:
        """Assemble the checklist from collected validation evidence.

        Required evidence keys (each produced by the modules above):
          beats_baseline_oos  : strategy Sharpe > baseline Sharpe OOS, after costs (§4 / principle #4)
          pbo                 : Probability of Backtest Overfitting (cpcv.py)         <= max_pbo
          deflated_sharpe     : DSR probability (deflated_sharpe.py)                  >= min_deflated_sharpe
          purged_cv_clean     : no label leakage; all tuning inside folds (purged_cv) == True
          regime_robust       : acceptable in every regime, not one-regime wonder (§4.7)
          stress_safe         : all stress scenarios behaved safely (stress.py)       == True
          paper_passed        : paper-trading gate cleared (§4.9)        == True if require_paper_gate
        """
        raise NotImplementedError(
            "build GateCheck list from `evidence` against ValidationConfig thresholds; "
            "approved == all passed."
        )
