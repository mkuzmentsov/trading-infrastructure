# Adversarial hunt 2026-09-01 (optimist × pessimist agent pair) — 7 candidates, 0 survive. Two keeper measurements.

User mandate: mine the printed data + our own trade tape (wins AND kills)
from new angles, read more venue docs, run an optimist-ideator against a
pessimist-realist, statistics-first, no dev, fleet untouched. Data: full
raw archive now through 09-01 18:00 UTC (~10.5 cl-truth days); 6,418 live
vacmaker FAK orders; openlag probe tape; 192k pre-open prints.
Artifacts: session scratchpad `openhunt/pess_*`.

## New docs knowledge absorbed first (both agents inherited it)
- Crypto taker delay (50ms since 08-17): the taker is HELD and **cannot
  cancel** during the delay; makers can still pull. Delayed marketable GTC
  that misses RESTS on the book ("unmatched" state).
- Matching-engine restarts: announced ~2d ahead (Telegram/Discord); 425s
  during restart; **2-minute post-only mode** after (takers rejected 503).
- Maker rebates: 20% of taker fees per market, **fee-curve weighted**
  (share ∝ p(1−p) of your filled maker liquidity within that market).
- Chainlink TWAP: sampling/rounding/tie rules **unpublished** by Chainlink;
  do not reproduce independently.

## The candidates and their fates

| # | idea (optimist) | verdict (pessimist, with the numbers) |
|---|---|---|
| 1 | **Taker-delay leakage** — do makers see our uncancellable delayed order and pull? (Probe tape: 80% of targets vanished vs 5.74% ambient fade = 14×) | **DEAD, refuted hard.** 6,418 vacmaker FAKs joined to 100ms tape with matched placebo (same bars, submit±5s, no order in flight): fresh-view target-fade within ~150ms of submit **3.5% vs placebo 8.9%** — z=−9.2 in the WRONG direction; our submits correlate with FEWER fades. cl velocity at our fade events BELOW placebo. No leak. The probe's 4/5 pulls were n=4 signal-fade + retry racing its own repriced view. |
| 1′ | (emergent) **Ghost-kills** | **WALL quantified, no exploit.** 84% of joined kills (1,563/1,852) show a matchable ask persisting 15s with zero consuming prints after our "no orders found" kill; 60% of those are the ≥0.90 tick-cross artifact, ~622 are genuine mid-band phantoms (hype/xrp/doge ~0.85). This is bug #23 (ua≡1−db, displayed ask = un-liftable maker bid) measured at scale — THE mechanical explanation for the 11% cheap-fill rate and the 7× snapshot-sim overstatement. Un-takeable by construction; resting behind them = the −0.47c maker wall. |
| 2 | **Counterparty fingerprinting** of our loss tape | **PARKED.** data-api /trades is one-sided (proxyWallet+side per row); pairing needs txHash self-joins + full labeled fill history. Premise (persistent toxic quoters) died with C1/C3 — nothing demonstrated to fingerprint. |
| 3 | **Quote-fade as signal** (the pull is information) | **DEAD.** 138,695 in-band fade events, era-pure, 7 coins: faded side wins **49.5%** — coin flip; +0.27c/sh pre-haircut, cluster-mean +0.13c (1454/2876 positive) → deeply negative after the 7× fill haircut. The probe's "puller was right 3/4" was n=4. |
| 4 | **Probe-ping active inference** (sonar FAKs) | **DEAD** — parent hypotheses (1,3) refuted; and the ghost result shows the ping's own reads are mostly phantom. |
| 5 | **hype as the soft venue** (no Binance spot → worst-priced book; Brier +0.6% softer) | **PARKED** — a routing tie-breaker for a lane that must first exist, not a strategy. |
| 6 | **Post-restart post-only window** (2 min with zero takers; bars settling inside it have no settlement flow) | **PARKED, watch-item** — no restart in the archive window to measure; announcements come ~2d ahead; zero marginal cost to watch. The one abuse-adjacent idea still alive in principle. |
| 7 | **Maker-rebate concentration** in empty markets + September program | **PARKED** — arithmetic caps at 20% of tiny per-market fee flow; no September program documented as of 09-01 (August's expired). Watch docs/programs. |

## The two keeper measurements (why this round was worth running)
1. **The placebo-controlled kill-timing design** (`pess_` artifacts) — first
   causal-grade test of the fill machinery; cleanly separates "market fades
   at signal moments" from "market reacts to OUR order." Answer: nobody
   sees us; the venue's taker delay leaks nothing. Reusable design for any
   future execution question.
2. **Ghost-kill quantification** — 84% of our kills are phantom-ask events.
   Folded into bug ledger #23 as the at-scale number. Any future taker-lane
   EV model should discount displayed in-band liquidity by ~this factor
   BEFORE any economics are computed.

## Bottom line
The adversarial round confirms the standing verdict from both directions:
the 5m book is efficient-minus-spread, the residual walls are mechanical
(phantom displayed liquidity + maker adverse selection), and the open items
are EXTERNAL events (venue restarts, a new rewards program), not signals in
the data. Watch-items: restart announcements, docs/programs page, the two
frozen re-check pipelines (openlag seam, premm census).
