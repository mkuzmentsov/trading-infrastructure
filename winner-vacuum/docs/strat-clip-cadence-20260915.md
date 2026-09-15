# "What if we clipped every 4 seconds, either side?" — measured
**2026-09-15. Real ledger (29 days, 4,434 matched fills) + the 3-day panel. Nothing deployed.**

Three answers, in order of how much they change the question.

## 1. The bot already clips ~3× faster than every 4 s — a 4 s cadence is a SLOWDOWN

Matched fills, real ledger, gap between consecutive fills in the same bar:

| | median | p25 | p75 | p90 | **< 4 s** |
|---|---|---|---|---|---|
| matched fills | **1.20 s** | 1.10 | 1.50 | 4.93 | **88%** |
| all attempts (incl. unmatched) | 1.30 s | 0.70 | 1.30 | 8.00 | 85% |

`WHALE_COOLDOWN_S` is 8 s, but the retry path (`PM_TE_LIVE_RETRY_S=3.0`) and unmatched attempts
not consuming the cooldown mean the realised cadence is ~1.2 s. **A strict 4-second floor would
delete 1,242 of 1,418 consecutive fill pairs (88%)** — it removes clips, it does not add them.

What actually caps a bar is the **ladder budget**, not time: $ spent per bar runs 15.12 (1 fill) →
20.22 (2) → 21.85 (3), and **56% of bars are a single attempt**. Clipping more often mostly splits
the same dollars into smaller pieces.

## 2. Yes the side can flip — it happens on 0.5% of bars, and it is a guaranteed loss

On a 4 s grid (tl 30→6), using the live estimator's own side at each slot: **6.73 decisive slots per
bar**, and the side flips within the bar on **23 of 4,888 bars = 0.5%**.

⚠️ **When it flips, you are not hedged — you are buying a $1.00 payout for more than $1.00.** By the
one-book identity a matched UP+DOWN pair pays **exactly $1.00**, so the pair's cost is the whole
story. Measured on the 13 bars where both sides had a displayed ask:

* mean pair cost **1.757**, median **1.820**, **min 1.360**
* **0 of 13 below 1.00**

A flip means the market's favourite moved while we were in it, so we buy the *new* favourite at a
high price having already bought the *old* one at a high price. Mean ≈ **−43% on the overlap**.
This is the same wall as [[reversion-priced-out]] arriving through a different door.

## 3. ⭐ The real finding: all of the money is in CLIP 1

Per clip index, real matched fills, taker fee charged:

| clip | n | $/fill | SE | t | day-clustered t | sweep rate | net |
|---|---|---|---|---|---|---|---|
| **1** | 2,985 | **+0.0871** | 0.0531 | 1.64 | 1.56 (G=29) | **2.91%** | **+$260.11** |
| 2 | 1,139 | −0.0136 | 0.0886 | −0.15 | 0.87 | 0.97% | −$15.50 |
| 3 | 265 | −0.0086 | 0.1102 | −0.08 | 0.04 | 0.75% | −$2.28 |

**Fleet +$242.79 = clip 1 +$260.11 + clips 2+ −$17.32.** Clips 2+ pooled are
**−$0.012/fill at t = −0.16** — indistinguishable from zero, not destructive, just *nothing*.

⭐ **Mechanism: the sweep rate collapses 2.91% → 0.97% after the first clip.** The stale ask is what
pays ([[btc-live-fill-ledger]]), and clip 1 already took it. A later clip is buying the *repriced*
book — the same object A1 measured field-wide at −5.67% for non-recon-eligible dislocations.

⚠️ **A trap I fell into first: the per-bar view says the opposite.** Bars with 2 fills earn
+$0.104/bar vs +$0.077 for 1 fill — which looks like "more clips are better". It is **selection**:
bars that went on to a 2nd clip had a *better clip 1* (+$0.102 vs +$0.078/fill). The clip-index
decomposition is the causal cut; the per-bar one is not.

## 4. Verdict

**More clips is the wrong lever.** Faster is already the status quo (1.2 s), a 4 s floor would be a
cut, both-sides is a 0.5% event that loses 43% when it fires, and the marginal clip has earned
nothing across 29 days. If anything here is worth testing it is the *opposite* — whether clips 2+
should exist at all — and even that is `t = −0.16`, i.e. below this fleet's resolution.

⚠️ **Nothing in §3 is statistically significant.** Clip 1's own t is 1.64 (day-clustered 1.56),
consistent with the fleet being unable to distinguish itself from zero on 29 days (t = 1.25, $8.37/day
against a day sd of $35.93). These are decompositions of a sample too small to certify, and the
honest reading is "no evidence the ladder adds anything", not "the ladder is proven harmful".

⚠️ §2's flip statistics come from the **3-day** panel (MDE +0.73 c/share); §1 and §3 are the
**29-day** ledger with no fill model.

Script: `scratchpad/research/cadence.py` plus the inline ledger cuts.
