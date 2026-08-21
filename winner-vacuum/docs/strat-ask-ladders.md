# Mint + two-sided ASK ladders (the "pro archetype"). VERDICT: DEAD — FINAL (full-bar skewed-MM sim, 2026-08-13 evening).

The July-2026 leaderboard forensics identified the consistent maker earners
as two-sided ladder MMs who MINT pairs ($1 → UP+DOWN), quote asks on both
sides, and MERGE/recycle instantly — never appearing in settlement holders.
With the CtfCollateralAdapter mint+merge confirmed IN OUR STACK
(mintsalvage/sweeper — see commons.md), this became mechanically copyable
on 2026-08-13. This doc records what copying it would mean and what's been
measured.

## Measured 2026-08-13 (flat ask levels, OPTIMISTIC fill model: every buyer
print ≥L fills us, no queue, cap 100sh/side, 7d / 2,025 bars, btc 5m)

| where | levels | PnL |
|---|---|---|
| in-bar (0–255s) | 0.52 / 0.55 / 0.60 / 0.70 | **−$2,618 / −$2,252 / −$1,651 / −$880 per day** |
| pre-open | 0.50–0.55 | −$195 to −$705/day (see strat-preopen.md) |

Deeper into the flow = worse. The unsold residual is systematically the
LOSING token (informed buyers lift the winner). An optimistic model losing
this hard closes the flat-level branch beyond argument.

## Why the July winners still won (and we couldn't copy then either)
- July program DID mechanically copy two validated winners tick-for-tick:
  both copies −EV. Conclusion recorded then: **"the edge is selection, not
  rule"** — when to quote, when to pull, inventory skew.
- Their era advantage: pre-fee ("fee-free ladders"); fees since arrived,
  though makers stay fee-free and now ALSO get the 20% rebate pool.
- Rebate math today: makers earn ≈0.26% of matched notional (20% of the
  0.07·p(1−p) taker fee) — our measured $21.69/day at our volume. The
  adverse-selection cost measured is 10-20× larger. Rebates do NOT close
  the gap at flat pricing.

## ⚠️ DATASET CAVEAT on the flat-level numbers above (added 17:50)
The in-bar flat-ask sim matched FULL-BAR prints against a flat level — it
counts selling the runaway winner at 0.52 all bar long, biasing it NEGATIVE.
Conversely the first skewed-MM sim ran on `postI.pkl`, whose snapshots are
LATE-WINDOW ONLY → sparse/stale mids vs full-bar prints = clairvoyant BIAS
POSITIVE (+$1,600/day mirage; tells: queue haircut IMPROVED PnL, and it
contradicted the flat sim by $4k/day). BOTH 5m in-bar numbers are unreliable.
The 1h skewed-MM run used the full-bar 1h dataset and IS trustworthy:
**−$70/day**. The honest 5m answer requires `/tmp/btc-5mfull.pkl` (full-bar
1s extract, built 08-13 evening). See docs/README.md §4 checklist.

## FINAL RESULT (2026-08-13 ~18:30, mm2_stream.py on 7d raw, 2,016 full bars)
Mid-relative bid+ask both tokens, inventory skew, instant merge, rebate
credited, controls included:
D2/K.0004/QH1 −$3,151/day · D2/K.001 −$2,594 · D3/K.001 −$2,208 ·
D1/K.0004 −$2,860 · **K=0 control −$16,411** (skew = 7× damage limiter,
not an edge) · QH0 −$2,285 (through-prints are the MOST toxic fills —
checklist note: for a −EV maker, stricter fills can reduce loss; the
"haircut must lower PnL" rule applies to +EV candidates only).
1h full-bar benchmark: −$70/day. The archetype loses at every fidelity we
can implement; the pros' edge is the SELECTION layer (third confirmation
after July's two tick-for-tick copy failures). Branch CLOSED.

## (superseded) The cell as it was framed before the run
A full-fidelity MM sim: quotes RELATIVE to the moving mid on both tokens
(bid+ask), INVENTORY-SKEWED pricing (shade quotes against held exposure),
matched pairs MERGED instantly (capital recycles, no settlement variance),
realistic queue haircut. This has never been run — all prior sims were flat
levels or bid-only. Prior expectation: negative (skew limits damage, it
doesn't source information), but it is the honest last word on the
archetype. Data ready: 7d btc 5m + fresh 15m recordings.

## If it ever goes live (requirements list)
mint sizing + gas/nonce budget (relayer), merge loop, per-side + aggregate
inventory caps, the poolfarm sticky halt, on-chain inventory reconcile at
startup, and the informed-flow kill-switch: if residual win-rate < 45% over
N bars, stop.
