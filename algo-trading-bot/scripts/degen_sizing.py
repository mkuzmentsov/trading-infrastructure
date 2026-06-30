"""Experiment #21 — risk-of-ruin & sizing rule for the degen sleeve (the capstone of Direction 3).

#20 gave the 1-year terminal-multiple distribution per leverage (with real mark-price liquidation). #21
turns that into an actionable sizing rule, in dollars, and pins the one decision that matters:

  Is the sleeve a COMPOUNDING book (bet repeatedly, reinvest) or a ONE-SHOT LOTTERY (a fixed stake you
  are willing to lose once)? They have OPPOSITE sizing rules.

Two formal lenses on the #20 distribution:
  * Repeated-betting growth: g = E[ln(terminal_multiple)]. A path that liquidates → multiple 0 → ln = −∞,
    so ANY leverage with P(liq)>0 has g = −∞ → repeated betting is GUARANTEED RUIN. Only leverage with 0%
    liquidation AND median>1 is growth-positive (safe to compound). This is the math behind "don't roll it".
  * One-shot lottery in dollars: on a fully-losable stake, show E[$], median $, P(total loss), P(≥2×), and
    the 95th/99th-pct moonshot — so the bet is chosen by its actual payoff distribution, never by its mean.

Sizing rule that falls out (printed): COMPOUND only at the top leverage that is growth-positive (≈2–3×);
for any higher leverage, the sleeve is a lottery and its size = capital you can lose 100% of without it
mattering — never sized by the upside.

Usage:  PYTHONPATH=src python3 scripts/degen_sizing.py [--bankroll 100000 --degen-frac 0.03]
"""

from __future__ import annotations

import argparse
import sys

import numpy as np

from degen_liquidation import (BLOCK, HORIZON, LEVERAGES, N_BOOT,  # sibling module in scripts/
                               build_bars, load, simulate)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bankroll", type=float, default=100_000.0)
    ap.add_argument("--degen-frac", type=float, default=0.03)
    args = ap.parse_args()
    stake = args.bankroll * args.degen_frac

    df = load(); bars = build_bars(df); n = len(bars["ret"])
    rng = np.random.default_rng(0)
    n_blocks = int(np.ceil(HORIZON / BLOCK))
    starts = rng.integers(0, n - BLOCK, size=(N_BOOT, n_blocks))
    paths = [np.concatenate([np.arange(s, s + BLOCK) for s in starts[k]])[:HORIZON] for k in range(N_BOOT)]

    print("=== Degen sleeve: risk-of-ruin & sizing rule (1-year horizon, trend signal) ===")
    print(f"bankroll ${args.bankroll:,.0f}   ring-fenced degen stake = {args.degen_frac:.0%} = "
          f"${stake:,.0f}  (the MOST you can lose — guaranteed by #19's isolation)\n")

    hdr = (f"{'lev':>4} {'P(total loss)':>13} {'P(>=2x)':>8} {'median $':>10} {'mean $':>11} "
           f"{'95th $':>11} {'99th $':>12} {'ln-growth g':>12}")
    print(hdr); print("-" * len(hdr))
    rows = []
    for lev in LEVERAGES:
        term = np.array([simulate(p, lev, "trend", bars) for p in paths])
        dollars = term * stake
        ruin = float((term == 0.0).mean())
        g = float(np.mean(np.log(np.where(term > 0, term, 1e-300))))   # -inf-ish if any ruin
        g_disp = "−∞ (ruin)" if ruin > 0 else f"{g:+.3f}"
        rows.append((lev, ruin, g, term))
        print(f"{lev:>3}× {ruin:>12.1%} {float((term>=2).mean()):>8.1%} "
              f"${np.median(dollars):>8,.0f} ${dollars.mean():>9,.0f} "
              f"${np.percentile(dollars,95):>9,.0f} ${np.percentile(dollars,99):>10,.0f} {g_disp:>12}")

    # The sizing rule, derived from the table above.
    compoundable = [lev for lev, ruin, g, _ in rows if ruin == 0.0 and g > 0]
    cap = max(compoundable) if compoundable else None
    print("\n— SIZING RULE —")
    if cap:
        print(f"• COMPOUND (reinvest, let it grow): cap leverage at {cap}× — the highest leverage with 0%")
        print(f"  liquidation AND positive ln-growth (g>0). Above {cap}×, g=−∞: repeated betting is")
        print(f"  mathematically certain ruin no matter how good the signal. This is the 'don't roll it' wall.")
    print(f"• LOTTERY (high leverage, ≥5–10×): typical outcome is $0 (median≈0, P(total loss) high). Size it")
    print(f"  ONLY as fully-losable capital — the ${stake:,.0f} stake here, lost 100% with no effect on the")
    print(f"  ${args.bankroll - stake:,.0f} core. NEVER size by the mean/95th: those are the survivorship")
    print(f"  moonshots the leaderboard shows you. Pick leverage by the payoff distribution you accept.")
    print(f"• The ${stake:,.0f} cap is the whole point of #19: it is the maximum the sleeve can ever cost you.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
