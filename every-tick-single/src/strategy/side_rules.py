"""Pluggable side rules for BRACKET_SIDES=one.

A rule answers: which side does this bar's single resting bid go on?
Keep rules pure (state in/out) so they are unit-testable and swappable via
BRACKET_SIDE_RULE without touching the strategy loop.

Rules:
  alternate — flip per bar (control experiment: removes market-drift bias,
              isolates maker-discount/adverse-selection economics; E4)
  signal    — the p_up estimate's side (measured degenerate ~always-UP at
              bar open; kept for conviction-gating experiments)
"""
from __future__ import annotations


def pick_side(rule: str, p_up: float, source: str, last_alt_side: str) -> tuple[str, str, str]:
    """→ (side, source, new_last_alt_side). Behavior-identical to the
    original inline block in maker_rebate."""
    if rule == "alternate":
        side = "DOWN" if last_alt_side == "UP" else "UP"
        return side, "alternate", side
    return ("UP" if p_up >= 0.5 else "DOWN"), source, last_alt_side
