# Four-agent program: the verdict
**2026-09-15. quant-analyst · ml-engineer · portfolio-strategist · polymarket-expert.
~800k agent tokens, ~75 model configs, 81 archive rows triaged. Nothing deployed.**

User asked for a **working strategy** on **crypto 5m markets**, with permission to retest everything.

## The answer

**There is no new working strategy, and the reason is now a bound rather than a list of failures.**

> **Our estimator beats the market decisively and is still below zero at the ask.**
> tl 3-30, fee charged on the real ask: market-implied baseline **−3.093 c/share**, the live gate
> **−0.279**, a *perfect* oracle **+5.334**. The gate's lift over the market is **+0.744 c/share**
> and it does not reach zero.
>
> ⭐ **Accuracy was never the binding constraint. Price is.** Any future proposal that promises money
> from better prediction must first explain how it clears that gap — four agents could not.

Three independent confirmations that the concentration, not the signal, is the problem:
* **Sweeps are one fill.** n=100, 2.28% of fills, +$40.66, **t=+0.31** — and **−$34.16 ex the single
  best** (+$74.82, one bnb bar). The non-swept book is larger *and* cleaner: **+$202.14, t=+1.48**.
* **Deep price improvement IS adverse selection**: win rate by improvement bucket 0.975 → 0.972 →
  0.854 → 0.787 → **0.513** at ≥0.15. The sweep lane's top-5 is **181%** of it; ex-top-5 **−$3.01/day**.
* ⇒ The archive's *"the stale-ask sweep is the engine / 40% of btc profit"* is **btc-only and ERA1-only.
  Retracted fleet-wide.**

## What each agent settled

| agent | verdict |
|---|---|
| **polymarket-expert** | **No fee cut exists.** Tiers are algebraically a fee-spend ladder (`wV ≡ 32.857 × fee`), Gold costs $6,087 of fee to save $0.80/day, **and even Obsidian flips no cell**. Taker rebate is **$0** in practice. Both subsidy leads dead with numbers. ⚠️ The crypto rate went **0.0312 → 0.07** since Feb — travel is against us. ⭐ **But the reframing matters more than the search**: we pay **0.234 c/share**, not 1.75 — the fee is a *tax on uncertainty*, so "cost exceeds mispricing in every band" was a **mid-band** statement and the live lane is nowhere near that wall. |
| **quant-analyst** | **Nothing re-opens.** 81 rows triaged, ~34 tests, largest \|t\| 3.36 against an expected max-under-null of 2.8-3.0. The best-looking lever (0.90-0.98 band) **already shipped 08-31** and the lane has since collapsed 25.4% → 2.6% of attempts. **With the fee set to exactly zero every negative cell stays negative.** |
| **portfolio-strategist** | **Hold size, hold 7 coins** — both below the noise floor. ⭐⭐ **The governing number is ruin**: over the **144 days** needed to learn whether $8.37/day ≠ 0, **P(equity<$50) = 31.8% if the true edge is zero.** Coin selection is **worse than chance** (split-half Spearman **−0.500**). |
| **ml-engineer** | **First models ever trained here.** Loss-avoidance veto **DEAD** (5 kills), fill-quality **DEAD** (OOS corr **−0.000**), direction control **tripwire clean** (every model below market mid). One **CONDITIONAL** survivor, below. |

## The one live thread, and exactly how it dies

**Sizing by model confidence**, budget-neutral (`w ∝ clip(1+20·(p̂−ask−fee), 0.5, 2.0)`, renormalised
per day — total stake unchanged, only its distribution): **+$2.723/day, paired day t=+2.75, 15/20
days, all 7 coins positive**, weight-shuffle placebo **z=+3.80 (0 of 300)**, side-flip null, both ask
bands positive, LOO all positive, cap sensitivity monotone.

**It dies to one assumption:**

| does a 2× clip fill like a 1× clip? | Δ $/day | t |
|---|---|---|
| same band rate | +2.723 | +2.75 |
| degraded `(1/m)^0.5` | +1.380 | +2.19 |
| **extra size never fills** | **+0.326** | **+0.66** |

**The whole result is a wager that displayed depth is real** — exactly what §72 retracted a finding
over (271 decisive bars showing cheap asks, **one** ever printed) and what bug #33 exists for. The
feasibility check uses `ask_sz`, the same displayed number under suspicion, so it cannot rescue the
assumption it rests on. Deflated over the round's ~75 configs, **t = −0.19**.

**Filed CONDITIONAL. Not deployable, and no offline re-analysis can settle it** — no tape we have
contains fills at more than one clip size.

## The two things actually worth acting on — both the user's call

1. ⛔ **The `live_inflight` ratchet.** eth and xrp have placed **zero orders since 09-09**, hype fires
   only below ask 0.598 — `settle_loop`'s abandoned path never decrements the counter, and
   `_whale_fire` returns **bare** on the cap where its siblings log. Six days of total inactivity
   produced no signal. **btc/sol are clear only because they restarted; bnb is one bad bar away.**
   → `incident-inflight-ratchet-20260915.md`
2. 🟡 **Record the panel's feature block into `PF_TE_EVAL`.** The 30-day decision set has one `tl`,
   no ladder, no flow, no Binance; the 3-day panel has all of it. One recorder change turns **53,311
   bars** from a 16-field record into a modellable panel at **zero research cost**. The single
   highest-leverage data change available, and it is additive and log-only.

## Standing results to reuse (not re-derive)

* **Power**: perfect loss oracle **+$17.57/day**; MDE at G=30 **+$5.35/day** ⇒ a veto is detectable
  only if it catches **≥30% of losses at ~zero false positives**. Ours caught 47% at 13% FP.
* **The relay race is worth +1.7 c/share** — five seconds of perfect foresight, measured on the
  monotone `ahd5 → live → lag5` ladder. That is the *entire* latency prize.
* **The `+0.01` limit buffer is the least concentrated positive in the round** and is already live:
  783 above-ask fills, **+$3.09/day, t=+1.68, 21/29 days, top-5 only 29%**.
* **The τ=0 veto drops 40-48% of fires and loses nothing** — a *capacity* result, not a PnL one.
* ⚠️ **AUC 0.8493 must be quoted with its tl band and a decidedness filter** or it is meaningless
  (pooled row-level AUC over ~28 near-duplicate rows/bar inflates to 0.88-1.00).
* ⚠️ **0.00% of 4,434 fills printed above their own `req_px`** — the FAK limit binds absolutely, so
  over-requesting is **price-safe**; the "17.8% above displayed ask" is the bot's own buffer.
* ⚠️ **The era trap is everywhere (bug #24)**: every lane except the near-zero 0.99 lane flips sign
  between halves, including clips 2+ (−$17.32 over 29d, **+$61.61 in ERA2**).

## Honest closing position

The fleet earns **$8.37/day at t=1.25** and **cannot distinguish itself from zero on its own 29-day
record**. Four specialists attacking it from four directions found no new edge, and the most
valuable outputs of the round were a **production bug**, a **ruin number**, and **three retractions
of things this archive believed**. That is the result.
