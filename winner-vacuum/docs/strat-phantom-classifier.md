# Phantom-ask classifier (Hunt A, 2026-09-13) — it WORKS and is worth ~nothing directly. The real finding is bar-level adverse selection, and one actionable idea: a retry allocator.

Question: bug #23 + the 09-01 ghost measurement say 84% of our FAK kills hit
asks that never traded. With v2 10-level ladders + the print tape, can we
tell a REAL (liftable) ask from a phantom BEFORE firing — and raise fill rate
on a lane already proven +EV? Analysis only, nothing deployed.
Artifacts: scratchpad `huntA_VERDICT.md`, `huntA_build.py`, `huntA_leak.py`,
`huntA_fires.parquet`.

## 1. The classifier is real
8,385 live `PF_TE_WHALE_ORDER` fires joined to strictly-pre-fire book state
(1,841 inside the parquet window). Day-split OOS **AUC 0.936** vs a
**0.555** price-band baseline. Fill rate by predicted quartile:
**44.4% → 96.7% → 97.8% → 98.9%**. Drivers: print recency, 3-level ask
depth, spread, pair-sum, ask age.

⚠️ **Leakage caught and removed** (worth remembering): the first run read
0.942 with `ev_1s` at 67% importance — the ledger stamps `t` AFTER the venue
replies (`ms` p50 363ms), so a matched order's OWN book events sat inside the
"pre-fire" window. Re-cut with the window ending at `t − ms/1000 − δ`:
0.866 / 0.864 / 0.860 / **0.861 at δ=1.0s** — flat, so the residual signal is
genuine. *Rule: when joining a live ledger to book state, the event timestamp
is the REPLY time, not the decision time.*

## 2. …and it is worth ~nothing directly
A killed FAK costs **nothing** — no fill, no fee. So "skip the phantoms"
saves zero dollars. And sizing up on predicted-real fires has no headroom:
those already fill **98.9%**, and side-accuracy is flat across quartiles
(94.44% → 96.67%, n=90 each = noise). A better fill-probability estimate
does not by itself make money on this lane.

## 3. ⭐ The real finding: missed bars are BETTER bars
386 bars got zero fills (~35/day). They are **98.96% side-correct** vs
**96.65%** on filled bars (**p=0.0008**). That is bar-level, live proof of
adverse selection — we get filled precisely when someone wants to sell to us,
and we get skipped when the market agrees with us. It is the
[[taker-side-adverse-selection]] wall, now measured at the bar level on our
own fires rather than inferred from snapshots.

## 4. The prize is small and mostly unbuyable
Tape-confirmed: only **32.8%** of missed bars saw any subsequent print. The
honest convertible set is **14.2 bars/day at +0.0585/share** (day-clustered
+0.0607 ± 0.0150, 7/8 days positive) — and that is an UPPER bound with
hindsight in it. A naive "+1 tick on the killed limit" model was rejected by
the agent itself: it read **+$42/day** against a fleet that actually earns
~+$19/day — a kill means nothing was there at that price, so re-pricing into
the void is fantasy.

## 5. The one actionable idea — a RETRY ALLOCATOR (not deployed)
The binding constraint is **timing, not price**: in 70% of convertible bars
the later print was at or below our killed limit; the bot caps at 3 attempts;
**45% of missed bars exhaust all three**, 51% try only once, and the median
miss still has **9.7s of `tl` left**. So the classifier's sensible use is to
spend the capped retries where liquidity is predicted real, rather than
uniformly. Bounded by ≤14 bars/day and realistically much less.
**Only a live A/B against the pod ledger could settle it** — per the 09-10
supersession, no replay dollar figure on this fleet is trustworthy.

## Not tested (budget)
Depth levels 2-10 → outcome (`lad10.parquet` unbuilt). Sweep-precursor depth
is already closed by bug #36.
