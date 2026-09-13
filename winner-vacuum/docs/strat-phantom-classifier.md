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

---

# HUNT B — event-time microstructure (same session). No new lane; two keepers and a recorder fix.

Data: `bookev` 4.77M cur-market book events (09-02…09-09, 7 coins); median
inter-event gap btc 61ms / alts 250ms-1.1s; arrival−venue_ts p50 26ms.
Artifacts: scratchpad `huntB/`.

| # | question | verdict |
|---|---|---|
| 1 | cross-coin lead-lag at ms resolution | **DEAD** |
| 2 | ask lifetime / event-driven firing | **NO EDGE** (keeper measurements) |
| 3 | `tick_size_change` as a state signal | **ARTIFACT, then marginal** |
| 4 | RB reconcile as a stale-book gate | **NOT USABLE as-is** |
| — | recorder | **DEFECT FOUND + FIXED** |

**1. Cross-coin lead-lag — statistically enormous, economically negative.**
On btc mid-jumps (≥2¢/0.5s, n=49,526) followers move sign-aligned +0.94¢
(eth, 200ms) to +1.86¢ (2s), **t=18-61** cluster-robust, placebo ≈0.00-0.03¢.
But followers had already moved **1.85¢ in the 0.5s BEFORE** btc's jump ⇒
common shock, not a lead. Economics: all-displayed −2.43¢/sh (n=22,046),
tape-confirmed **−1.45¢/sh** (n=6,674, 3,510 clusters, t=−2.81), **1/8 days
positive**. The drift lives inside the spread — exactly as the 07-29
structure hunt predicted. *This is the ms-resolution rerun that closes the
question the old 100ms-aliased test left ambiguous.*

**2. Ask lifetime — the numbers are keepers, the EV story is a price artifact.**
38,695 favourite-ask episodes (tl 3-30, ask ≤0.99): **median episode lives
236ms**; **60.4% are shorter than our 0.4s poll**, 40.3% shorter than 0.15s;
**btc median 99ms** (a 0.4s poller structurally sees a minority of btc
supply); 64.4% are tape-confirmed and the market's takers hit them at **74ms
median** (p90 199ms). The tempting gradient (missed <0.4s supply +2.42¢/sh vs
seen +0.99¢/sh, monotone over six buckets) **dies under the within-ask-level
control**: short episodes are simply cheaper asks (0.846 vs 0.917); holding
the level fixed the diff is +0.26¢/sh, short wins 18/32 levels, no level
significant (largest |t|=2.03, negative), dear-band day-split 5/8.
⇒ **Do not justify an event-driven rewrite on EV grounds.** The latency
figures remain valid input for future execution work.

**3. `tick_size_change`** — ⚠️ trap worth recording: a per-token test returns
**exactly 50.0% in every cell** because the transition is a MARKET-level
event (99.9% of markets flip both tokens, gap p50/p90 = 0.000s). Market-level
and in-bar only (74% are post-close, bug #39): n=207, favourite holds
97.1-97.4% vs 90.75% baseline, +1.98¢/sh (t=+2.09) — tiny n, ~26 events/day,
and it is the same dear-favourite trade the lane already makes.

**4. RB reconcile** — match rate 44.9% (btc) → 98.5% (zec), rank-ordered by
book churn: it measures how fast `price_change` erodes the stored hash, not
staleness. Confirms the documented 35-40% btc baseline; would need per-coin
churn normalisation to gate anything.

**⭐ Recorder defect found and FIXED same session.** `price_change` events
(96% of the stream — 191,649 of 199,999 in a sample hour) carried no
`ws`/`tok` attribution: the row was stamped only from the top-level
`asset_id`, which `price_change` omits, and the per-change `U`/`D` is
ambiguous across the 4 tracked markets (cur + next1-3). `ev2pq.py` dropped
them entirely, so the HF layer was unusable for bar-level work. Fix: each
change now carries its own resolved bar — `ch = [ws, tok, side, px, sz]`.
Verified 100% attribution locally, rolled to all 17 recorders 2026-09-13.
⚠️ Parsers of `mrecev` must handle BOTH shapes: 4-element entries before
09-13 ~18:00 UTC, 5-element after.
