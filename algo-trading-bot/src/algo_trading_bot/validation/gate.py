"""Approve-for-live gate (§4) — itself a deliverable.

"Approved for live" requires clearing EVERY check below. The gate is a hard,
auditable checklist; a model that fails any item does not go live, regardless of how
good its headline Sharpe looks. This encodes principle #4 (beat a dumb baseline or
don't ship) and principle #1 (the harness is the product).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..config import ValidationConfig

# Conventional significance threshold for the Deflated Sharpe Ratio: we require at
# least 95% probability the true Sharpe beats the expected-max-under-null.
DSR_THRESHOLD = 0.95


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

        Only checks whose evidence is present are added, so a partial run (e.g. the
        rule-based baseline, which has no ML PBO yet) yields a partial — but honest —
        verdict. Recognized keys:

          oos_sharpe          : OOS Sharpe after costs   -> positive_oos_sharpe, beats_baseline_oos
          baseline_sharpe     : comparator Sharpe (default 0.0)
          deflated_sharpe     : DSR probability (deflated_sharpe.py)  >= DSR_THRESHOLD
          pbo                 : Prob. of Backtest Overfitting (cpcv)  <= max_pbo
          regime_robust       : bool (§4.7)
          stress_safe         : bool (stress.py)
          paper_passed        : bool (§4.9), required iff require_paper_gate
        """
        checks: list[GateCheck] = []

        if "oos_sharpe" in evidence:
            sr = evidence["oos_sharpe"]
            base = evidence.get("baseline_sharpe", 0.0)
            checks.append(GateCheck("positive_oos_sharpe", sr > 0, f"OOS Sharpe={sr:.2f}"))
            checks.append(GateCheck("beats_baseline_oos", sr > base,
                                    f"OOS Sharpe={sr:.2f} vs baseline={base:.2f}"))
        if "deflated_sharpe" in evidence:
            dsr = evidence["deflated_sharpe"]
            checks.append(GateCheck("deflated_sharpe", dsr >= DSR_THRESHOLD,
                                    f"DSR={dsr:.3f} (need >= {DSR_THRESHOLD})"))
        if "pbo" in evidence:
            pbo = evidence["pbo"]
            checks.append(GateCheck("pbo", pbo <= self.config.max_pbo,
                                    f"PBO={pbo:.2f} (need <= {self.config.max_pbo})"))
        if "regime_robust" in evidence:
            checks.append(GateCheck("regime_robust", bool(evidence["regime_robust"]), ""))
        if "stress_safe" in evidence:
            checks.append(GateCheck("stress_safe", bool(evidence["stress_safe"]), ""))
        if self.config.require_paper_gate and "paper_passed" in evidence:
            checks.append(GateCheck("paper_passed", bool(evidence["paper_passed"]), ""))

        return GateResult(checks=checks)
