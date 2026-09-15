# DEPTH.md — the depth question, settled from the tape

**2026-09-16. Round 2 deliverable. Nothing deployed. No live-fleet change proposed.**

Base: `/private/tmp/claude-501/-Users-maxkuzmentsov-development-projects-my-hummingbot-hummingbot-infra/34249563-b474-4d9e-bdf4-d3c52eb5d2de/scratchpad/research`
Scripts: `models/dp1_ledger_depth.py`, `dp2_price_impact.py`, `dp3_book_tape.py`,
`dp4_reprice.py`, `dp5_depletion.py`, `dp6_edge_conditional.py`, `dp7_gate.py`,
`dp8_buffer.py`, `dp9_final.py`. Raw output: `out/depth/dp*.txt`.

---

## 0. Answer first

| task | answer |
|---|---|
| **1. does the extra clip size fill?** | **YES.** Measured **φ(2) = 1.92**, not the 2.00 / 1.41 / 1.00 hypotheticals. The sizing rule re-prices at **+$2.448/day, day t = +2.76** — 90 % of its optimistic value, not the 12 % feared. |
| **2. is p̂ a better gate than \|est\|?** | **NO**, in both framings. As a gate: **+0.04 $/day, t = +0.03** (equal volume). As a *fillability* predictor (the re-scoped version): AUC(fill ~ p̂) = **0.071**, and residualised on \|est\| within cells it stays below 0.5 — p̂ is \|est\| wearing a different hat. §2, §3b.4. |
| **3. would a +0.02 limit buffer pay?** | **NO, and it is bounded, not estimated.** The second cent needs a **0.9755** win rate. The fills the first cent already buys win **0.9719**. Repriced one cent worse those same fills go **+0.574 → −0.361 c/share**. Negative by arithmetic before reach enters. |

**I was wrong in MODELS.md §3.6a about the data, and the correction is the main result.**
I wrote *"no tape we have contains fills at more than one clip size, so no re-analysis
resolves it."* Both halves are false:

* `req_sh` in the pod ledger takes **8 / 9 / 5 / 12 / 13 / 24 / 25 / 26** shares across eras.
* More decisively, **a partially-filled FAK is an exact observation of available depth.**
  A FAK that returns less than it asked for has *exhausted the book at or below its limit*.
  So the 24-share lane alone identifies the entire distribution of executable size `L` on
  `[0, 24)` with **no cross-size assumption and no fill model** — every `L < 24` is observed
  to the share.

That is the counterfactual I said did not exist. It was in the ledger the whole time.

**The honest caveat that replaces it:** resolving the depth assumption does not make the
sizing rule a finding. It removes the *specific* objection that killed it and leaves it
exactly where its own statistics put it — a 20-day, t = +2.76, deflated-negative result with
an unclean latency tell. §1.6.

---

## 1. Task 1 — the depth question

### 1.1 The estimator, and why it has no look-ahead

For every attempt in `PF_TE_WHALE_ORDER` (8,496 attempts, 29 days):

```
matched & filled <  req_sh   ->  L = filled      EXACT observation of executable depth
matched & filled >= req_sh   ->  L >= req_sh     right-censored
not matched                  ->  L = 0
```

`L` = shares executable at ≤ `req_px` at the send instant. Kaplan-Meier on `L` with
right-censoring at `req_sh`, then

> **φ(m) = E[min(L, m·S₀)] / E[min(L, S₀)]**, S₀ = 8/0.975 = 8.2 sh (the $8 clip)

φ(m) is exactly the quantity MODELS.md §3.6a guessed at three ways: φ(2) = 2.00 is
"same band rate", 1.41 is "degraded (1/m)^0.5", 1.00 is "extra size never fills".

**This estimator reads zero seconds of the future.** It is our own realised fill at the
instant we sent. The standing look-ahead rule has nothing to bite on — which is the whole
reason to prefer it to the tape statistic in §1.4, which does grow with the window and
says so.

### 1.2 The measured curve

`models/dp1_ledger_depth.py` → `out/depth/dp1.txt`

| lane | n | base rate at S₀ | **φ(2)** | L identified to |
|---|---|---|---|---|
| late era (≥08-28), ask ≥ 0.90 | 3,169 | 0.5638 | **1.9176** | 26 sh |
| late era, ask 0.98–0.99 | 2,726 | 0.5859 | 1.9160 | 24 sh |
| late era, ask 0.90–0.98 | 443 | 0.4279 | 1.9299 | 26 sh |
| sz ≥ 24 lane (self-identifying) | 3,394 | 0.3999 | 1.9106 | 26 sh |
| early era (<08-28), ask ≥ 0.90 | 3,754 | 0.5698 | 1.9332 | **13 sh — extrapolated, upper bound** |

A 2× clip needs 16.4 sh, **inside** the identified range in every late-era lane. The early
era is reported only to show it agrees; its φ(2) is not identified and is not used.

**Why it is so close to 2.0 — the shape of L** (`dp2.txt`):

| L | share |
|---|---|
| **0 (no fill at all)** | **0.5825** |
| (0, 8] | 0.0384 |
| **(8, 16)** | **0.0274** |
| [16, 24) | 0.0288 |
| **≥ 24 (full)** | **0.3232** |

**L is bimodal: either nothing is there, or a lot is.** The interior band — the only region
where a 2× clip is cut short and a 1× clip is not — holds **2.7 %** of attempts.
Conditional on any fill at all, **P(L ≥ 16) = 0.845** and **P(L ≥ 8) = 0.910**.

φ is a *ratio*, so it is **invariant to the L = 0 mass** — whether the 58 % of unmatched
attempts are "no depth" or "order arrived late" changes the base rate and leaves φ
untouched. Verified numerically: all attempts φ(2) = 1.9176, conditional on L > 0
φ(2) = 1.9176 (`dp5.txt`).

### 1.3 The price of the marginal share is zero

`dp2.txt`. Slippage `avg_px − seen_ask`, demeaned within coin × day × ask-tick:

| realised fill | n | slip (demeaned) |
|---|---|---|
| < 12 sh | 557 | **+0.00073** |
| ≥ 12 sh | 1,294 | **−0.00031** |

Bigger fills do not pay more. And size is not adverse selection: win rate by fill bucket is
0.973 / 0.991 / 0.984 / **1.000** / 0.972 across 4–26 shares. §4.4's adverse selection is
real but it is a **price-improvement** effect (deep improvement → 0.513 win), not a **size**
effect at the same price. The two were being conflated, including by me.

### 1.4 The tape confirmation, with its own look-ahead warning

`models/dp3_book_tape.py` → `dp3.txt`. 760 counterfactual fire instants (panel, 3 days,
one per bar, fleet gate, favourite ask ladder).

Displayed level-0 size: median **30 sh**; P(level-0 ≥ 16 sh) = **0.690**; P(top-3 cum ≥ 16)
= 0.946. **A 2× clip sits inside displayed level 1 on most instants** — so the question was
never "is level 3 real", it is the §72 ghost question, "is level 1 real".

The §72 ghost test:

* P(nothing ever prints at ≤ the displayed best ask within 60 s) = **0.053**
* P(≥ 8 sh prints) = **0.884**, P(≥ 16 sh prints) = **0.800**
* median printed volume 95.1 sh vs median displayed level-0 30.0 sh

⚠️ **The window sweep, reported in full because it is the required diagnostic.** Fraction of
displayed depth traded, level 1:

| look-ahead | no lag | 0.5 s lag |
|---|---|---|
| 0.2 s | 0.070 | 0.068 |
| 0.5 s | 0.149 | 0.135 |
| 1.5 s | 0.348 | 0.284 |
| 5.0 s | 0.598 | 0.522 |

**This quantity grows with the window, monotonically, by a factor of 8.** Under the standing
rule that is a red flag — and here the mechanism is known and benign: the statistic is
**demand-limited, not availability-limited**. Displayed size that nobody chose to hit is not
phantom. It is therefore a **lower bound** on realisable depth and it is **not the number
used anywhere in the re-price.** §1.2 is. I am reporting it because the task asked for the
sweep and because the honest reading of a growing quantity is "do not use this one", not
"here is my answer".

### 1.5 The two ways it could still have been wrong, both tested

**(a) Our own clip eats the book for the next one.** `dp5.txt`. The bot sends up to 4
sequential clips per bar, median gap **0.61 s** — an aggregate order the venue actually
filled. After a **full 24-share clip 1**, clip 2 fully fills **78.4 %** of the time
(clip 1 on a virgin book: 65.2 %). Bars that sent 2 clips took **29.4 shares** in aggregate.
Deep books stay deep; the confound runs the same direction, so this is an upper bound —
but it is nowhere near a depletion signature.

**(b) ⭐ Depth is thinner exactly where the model wants more size.** This was the decisive
objection ([[taker-side-adverse-selection]]: a cheap ask *is* an informed maker's bid and
fills 11 %). Joined the ledger to the OOS eval panel on (coin, ws), 1,590 rows / 18 days,
and measured φ **inside each multiplier band the rule actually uses** (`dp6.txt`):

| multiplier band | n | ask | base rate | **φ(2)** |
|---|---|---|---|---|
| 0.5–0.8 (down-weighted) | 317 | 0.980 | 0.860 | 1.931 |
| 0.8–1.0 | 216 | 0.985 | 0.596 | 1.874 |
| 1.0–1.3 | 283 | 0.983 | 0.514 | 1.894 |
| 1.3–1.7 | 594 | 0.979 | 0.061 | 1.933 |
| **1.7–2.0 (doubled)** | **180** | 0.940 | 0.319 | **1.966** |

**φ is flat — 1.87 to 1.97 — across every band, including the band where the rule doubles.**
The objection fails.

⚠️ But the table shows something else, and I am flagging it rather than using it: the
**base** fill rate is wildly heterogeneous (0.86 down to 0.06) and correlated with the
multiplier. Re-pricing with band-conditional base rates moves the headline to **+$3.62/day,
t = +2.19** (*up*, with a doubled SE). **I am not taking that number.** The 0.061 cell is
**47 % one day (08-31) and 38 % one coin (hype)** — exactly the concentration this venue's
history is made of. It is a sensitivity, not a correction.

### 1.6 The re-price

`models/dp4_reprice.py` → `dp4.txt`. Same rule, same rows, same budget-neutral framing as
MODELS.md §3.6a: `w ∝ clip(1 + 20·(p̂ − ask − fee), 0.5, 2.0)`, p_full, OOS fires n = 2,430
over 20 days. Only the fill assumption changes.

| fill assumption | Δ $/day | day t | days+ | ex-best-day | ex-top-5-rows | LOO range |
|---|---|---|---|---|---|---|
| hypothetical: same band rate (φ=m) | +2.618 | +2.78 | 15/20 | +2.086 | +2.104 | [+2.09, +2.91] |
| hypothetical: degraded (φ=m^0.5) | +1.198 | +2.66 | 14/20 | +0.958 | +0.897 | — |
| hypothetical: hard (φ=1) | **0.000** | — | 0/20 | — | — | — |
| **MEASURED φ [late, ask ≥ 0.90]** | **+2.448** | **+2.76** | **15/20** | **+1.951** | **+1.945** | **[+1.95, +2.72]** |
| MEASURED φ [0.98–0.99 lane] | +2.444 | +2.76 | 15/20 | +1.948 | +1.941 | — |
| MEASURED φ [0.90–0.98 lane] | +2.478 | +2.77 | 15/20 | +1.974 | +1.976 | — |
| MEASURED φ [sz ≥ 24 lane] | +2.431 | +2.76 | 15/20 | +1.937 | +1.930 | — |
| MEASURED φ, **edge-conditional** | +2.558 | +2.78 | 15/20 | +2.032 | +2.050 | — |
| MEASURED φ, **worst band's curve on every up-weight** | +2.364 | +2.74 | 14/20 | +1.884 | +1.861 | — |

**Strict realised-share budget neutrality.** φ is concave, so equal *intended* dollars is not
equal *realised* shares — the rule must not win by quietly spending less. Realised-share
ratio vs flat = **0.9970**; renormalising to exact realised-share neutrality gives
**+2.429 $/day, t = +2.79**. It does not win by spending less.

**Required robustness, all on the measured-φ number:**

| check | result |
|---|---|
| **weight-shuffle placebo** (300 draws, within day) | mean +0.021, sd 0.644, **z = +3.77, p(≥obs) = 0/300** |
| **side-flip placebo** | **−2.448 $/day, t = −2.76** (clean sign reversal) |
| **era split** (bug #24) | late (≥08-28, G=18) **+2.498, t = +2.57**, 13/18 days. Early era has G = 2 — not testable, stated as such |
| **ex-best-day** | +1.951 | 
| **ex-top-5-rows** | +1.945 (top-5 rows are **21 %** of the effect — this is *not* a five-fill result) |
| **LOO-day** | all positive, [+1.951, +2.717] |
| **per-coin** | all 7 positive: bnb +0.28, btc +0.37, doge +0.90, eth +0.23, hype +0.27, sol +0.26, xrp +0.15 |
| **cap sensitivity** | 1.25× +0.83 (t 2.07), 1.5× +1.65 (2.62), 2× +2.45 (2.76), 3× +2.85 (2.63) — monotone, smooth |
| **base-rate rescale** (evh band rate 0.549 vs ledger-realised 0.564) | +2.512 $/day |
| ⚠️ **bug #32 latency tell** | low-lag tercile **+0.043 (t +0.11)**, mid +1.467, high +0.937. **Still not clean.** Inherited from round 1, not created here |
| **φ's own latency tell** | φ(2) by order round-trip: fast 1.930 / mid 1.910 / slow 1.923. Flat. The *base* rate rises with ms (0.069 / 0.733 / 0.890), which is mechanical — an order with nothing to fill returns fastest |
| **φ stability** | by day (G=18): mean 1.9232, **sd 0.0353**, range [1.867, 1.995]. By coin: [1.801 hype, 1.989 btc] |

### 1.7 Verdict on task 1

**Displayed depth beyond our 1× clip is real, and the sizing rule's stated blocker is
removed.** φ(2) = 1.92 ± 0.04, stable across 18 days, 7 coins, 2 ask bands, 5 multiplier
bands, 3 latency terciles and 2 independent lanes.

**That does not make it deployable, and I am not proposing it.** What remains, unchanged
from round 1:

1. **The latency tell is still not clean.** Value is ≈ 0 at the freshest tercile. That was
   the fifth flag that killed the veto and it has not been answered here.
2. **Deflation.** Cumulative configs across both rounds ≈ **115**. √(2 ln 115) = **3.08**.
   Raw t +2.76 → **deflated −0.32**. Over the
   8-cell sizing family alone (2.04) it reads +0.72.
3. **20 day-clusters.** The paired MDE at G = 20 is roughly +$2.5/day; the effect is at the
   detection floor, not comfortably above it.

The correct status is **CONDITIONAL → OPEN**: the specific reason it was filed conditional
is gone, the general reasons it is not a finding are not. The next thing that would move it
is **more day-clusters**, not more analysis.

---

## 2. Task 2 — confidence ranking vs magnitude ranking

`models/dp7_gate.py` → `dp7.txt`. Eligible pool n = 4,342 (fires + eligible-but-blocked),
20 OOS days. Each day selects the **same number of rows the bot actually fired**, ranked
four ways. Equal volume, so neither side can win by trading less.

| ranking | n | acc | ask | net c/share | $/day | ex-best-day | ex-top-5-rows |
|---|---|---|---|---|---|---|---|
| **\|est\| (magnitude — what the fleet does)** | 2,430 | 0.9765 | 0.961 | +1.350 (t 3.19) | **+5.624** (t 2.69) | +4.379 | +5.371 |
| p_full (confidence, no price) | 2,430 | 0.9860 | 0.974 | +1.063 | +3.883 | +2.746 | +3.652 |
| p_full − ask − fee | 2,430 | 0.9654 | 0.948 | +1.479 | +5.661 | +4.253 | +5.398 |
| p_est (confidence, no price) | 2,430 | 0.9807 | 0.964 | +1.411 | +5.154 | +4.080 | +4.893 |
| p_est − ask − fee | 2,430 | 0.9490 | 0.931 | +1.394 | +5.765 | +4.698 | +5.499 |
| the bot's actual fires | 2,430 | 0.9461 | 0.929 | +1.322 | +5.346 | +3.657 | +5.081 |
| **random, volume-matched (200 draws)** | 2,430 | — | — | — | **+2.731** (sd 1.23) | — | — |

Paired day-level differences vs `|est|`:

| ranking | Δ $/day | t | days+ | LOO range |
|---|---|---|---|---|
| p_full (no price) | **−1.742** | −1.53 | 7/20 | [−2.28, −1.27] |
| p_est (no price) | −0.470 | −0.50 | 9/20 | [−1.03, −0.06] |
| p_full − ask − fee | **+0.037** | **+0.03** | 11/20 | [−0.38, +0.53] |
| p_est − ask − fee | +0.140 | +0.11 | 13/20 | [−0.30, +0.70] |

**Placebos.** Label-shuffle (block-permuted): mean −0.031, sd 1.833, **z of observed = +0.04,
p = 0.495**. Side-flip: −0.037, t = −0.03. Both say the same thing as the point estimate:
nothing. (Per bug #30 the label shuffle is near-vacuous for *levels* on a 0.97 ask mix; for
a *paired difference between two equal-volume selections* it is not vacuous and is the right
null here.)

**Robustness.** Late era (G=18) +0.967, t = +0.75. Per-coin: 4 of 7 positive, none with
|t| > 1.4 (eth +0.67, sol −0.65). Latency tell: low −0.51, mid +0.49, high +0.16 — noise.
Volume sensitivity: at half the daily budget +1.201 (t +1.16), at double **−0.374 (t −0.49)**
— the sign flips with volume, which is what a null does.

**Verdict: clean negative.** Confidence ranking does **not** beat magnitude ranking at equal
volume. Two things worth keeping:

* **Price is doing all the work the model could do.** p̂ *without* price is decisively worse
  (−1.74). p̂ *with* price is indistinguishable from |est| with price. The model's
  calibration is real (MODELS.md §3.2) and it is already priced in.
* **The gate itself is worth something against random** (+5.62 vs +2.73/day) — but it is the
  *estimator* that is worth it, not the model on top of it.

**Power.** Paired SE ≈ 1.19 $/day at G = 20 ⇒ **MDE(80 %) = +$3.33/day**. An improvement
smaller than that is invisible here. The point estimate is +0.04 and the family's best raw
|t| is 0.11, so no deflation is needed — but "no effect above +$3.3/day" is the defensible
claim, not "no effect".

---

## 3. Task 3 — the +0.02 buffer, bounded

`models/dp8_buffer.py`, `dp9_final.py` → `dp8.txt`, `dp9.txt`.

**The bound does not need a reach estimate, because the arithmetic closes first.**

The live +0.01 buffer's above-ask fills: **783 settled fills, mean seen_ask 0.9570, mean
avg_px 0.9639, win 0.9719, +0.574 c/share, +$89.65 = +$3.091/day** (MODELS.md §4.6,
reproduced exactly).

| price | break-even win rate | realised win rate | net c/share | $/day |
|---|---|---|---|---|
| avg_px (what +0.01 buys) | 0.9662 | 0.9719 | **+0.574** | **+3.091** |
| avg_px + 0.01 (what +0.02 would buy) | **0.9755** | 0.9719 | **−0.361** | −0.311 |
| avg_px + 0.02 | 0.9848 | 0.9719 | −1.293 | −3.708 |

**The second cent needs a 0.9755 win rate. The fills the first cent already buys win 0.9719.**
The first cent clears its break-even by 5.7 pp of win rate; the second is 3.6 pp short of its
own. The incremental fills a +0.02 buffer would add are, by construction, the rows where the
ask ran *further* — a strictly worse subset than the ones measured above, not a better one.

Three independent bounds, all pointing the same way:

**(1) Structural.** `fee = 0.07·p·(1−p)`, so net at ask 0.98 + 0.02 = 1.00 is ≤ 0 by
arithmetic. Only **40.3 %** of attempts (and **40.1 %** of the above-ask fills) have
`seen_ask ≤ 0.97`, i.e. any headroom for a second cent at all. **A +0.02 buffer is
inoperative on the band where the fleet does most of its volume.**

**(2) Book.** 760 fire instants, ask one second later (1 s is 2–5× the real 0.2–0.5 s send
latency, so this **overstates** drift):

| where the ask went | share |
|---|---|
| ≤ a (buffer not needed) | 0.696 |
| **(a, a+0.01] — what +0.01 catches** | **0.096** |
| **(a+0.01, a+0.02] — what +0.02 adds** | **0.018** |
| > a+0.02 (still missed) | 0.097 |
| ask gone | 0.092 |

Extra reach ratio **0.192**. Split by headroom: at ask ≤ 0.97 the extra reach is 0.057
(ratio 0.67); at ask > 0.97 it is **exactly 0.000** — there is nowhere to go.

**(3) Tape.** Cheapest price that *actually printed* in (t, t+0.5 s] (a print is proof the
level was executable): ≤ a on 0.884, in (a, a+0.01] on 0.070, **in (a+0.01, a+0.02] on
0.027**, > a+0.02 on 0.018. The book and tape bounds agree to within a factor of 1.5.

**Combined upper bound:** +$3.091/day × 0.192 (extra reach) × −0.63 (price-penalty scale) ×
0.40 (headroom share) = **−$0.15/day**. Every factor is generous and the product is still
negative, because the sign is set by the per-share arithmetic, not the reach.

**Verdict: bounded and closed. The +0.01 buffer is at the right size; +0.02 is
net-negative at every reach assumption this data can support.** The symmetric question —
whether +0.005 would be better — is *not* answerable this way, because the tick grid below
0.96 is 0.001 and above it is 0.01, so a half-cent buffer is not expressible on most of the
volume. That one stays live-A/B-only, as round 1 said.

---

## 3b. Three results handed to me mid-round, folded in

`models/dp10_coord.py` → `out/depth/dp10.txt`

### 3b.1 The strategist's "19 % of up-weighted clips are PROVEN unfillable" — same measurement, different statistic

We ran the same idea. Their statistic is **P(a clip that completed at all completed at
< 100 %)**, which on this ledger is **0.137 (all) / 0.168 (late, ask ≥ 0.90) / 0.227
(sz ≥ 24 lane)** — their 0.189–0.193 sits inside that bracket. It is correct.

It does **not** carry the economic implication, for two reasons, both measurable:

* **Those clips are not unfilled, they are half-filled.** Mean completion of a partial clip
  is **0.484**. "Proven unfillable" reads as 0; the ledger says ~½.
* **Most of the capped mass is at L = 0, where the 1× clip gets nothing either, so it
  cancels in the ratio.** On up-weighted rows (w ≥ 1.7, n = 180, 18 days):

| | share |
|---|---|
| L = 0 — 1× gets nothing either | 0.678 |
| 0 < L < S₀ — 1× also cut short | 0.006 |
| **S₀ ≤ L < 2·S₀ — only the 2× is cut** | **0.011** |
| L ≥ 2·S₀ — the 2× fills in full | 0.306 |

**The band that actually penalises doubling is 1.1 % of up-weighted rows**, and φ(2) in that
band is **1.9655**. (n = 180 — small; this is the weakest cell in the round and I am not
resting the conclusion on it alone. The pooled and per-band curves in §1.2/§1.5b carry it.)

⇒ *"fraction of clips capped"* and *"fraction of the extra shares lost"* are different
numbers. Only the second prices the rule. **I do not treat "displayed depth is real" as
disproved for the up-weight half; the ledger measurement says the opposite, and it is the
same ledger.**

### 3b.2 ⭐ The venue floor is real and I had it wrong — but it binds on the *parameterisation*, not the rule

`twapedge.py:441-442`: `LIVE_SIZE` is in **shares** (26 live), with hard floors
`sh ≥ 5` **and** `sh·ask ≥ $1`. A multiplicative scheme must clamp as
`max(5, int(k·req_sh))` or it silently deletes clips. Re-priced (each row against its own
no-floor baseline, same convention throughout):

| base clip | no floor | **floor as `max(5, k·req_sh)`** | floor silently deletes | rows below floor |
|---|---|---|---|---|
| **$8-denominated (8.2 sh)** | +2.594 (t 2.39) | **+2.388 (t 2.81)** | +2.728 (t 2.37) | **17.6 %** |
| **LIVE_SIZE = 26 sh** | +2.594 | **+2.594 (identical)** | +2.594 | **0.0 %** |

**At the live 26-share clip a 0.5× multiplier is 13 shares and the floor never fires.** The
strategist's "the down-weight does not happen" is a property of the $8-clip parameterisation
that `evh.usd()` assumes, not of the sizing rule. Correctly clamped at the $8 clip it costs
−0.21 $/day and *raises* t. Either way the floor does not kill it.

(⚠️ note: dp10's no-floor baseline reads +2.594 vs dp4's +2.448 — dp10 extrapolates φ below
m = 0.5 to 0 where dp4 holds it at φ(0.5). The floor comparison is internally consistent;
**the headline stays dp4's +2.448.**)

### 3b.3 ⭐ The replay-vs-realised gap, decomposed — and it is *not* reachable on purpose

The coordinator is right that the panel replay understates the live book and that the gap is
the prize. On the **filled set**, with real prices and the fee charged:

| | c/share |
|---|---|
| realised (242.81 $ / 55,364 sh) | **+0.4386** |
| the *same fills* priced at the displayed ask | **−3.0287** |
| **execution edge** | **+3.4673** |

(The gap is larger than the +0.84 c implied by −0.279 vs +0.4385 because those two numbers
are over *different row populations* — the panel replay averages over all gate-firing rows,
including the 47.8 % of attempts that never fill. The replay/realised gap is two effects
superimposed: price improvement on the fills we got, **plus** the replay pricing fills we
never got. Only the first is reachable on purpose.)

And the first decomposes to almost nothing reachable:

| lane | n | % of shares | contribution to the +3.467 |
|---|---|---|---|
| **sweeps (imp ≥ 0.005)** | 294 | **11.3 %** | **+3.5866** |
| buffer fills (paid above ask) | 783 | 19.1 % | −0.1203 |
| at the ask | 2,972 | 63.6 % | 0.0000 |

**The entire execution edge is the sweep lane** — 11.3 % of shares producing 103 % of the
improvement. That is the lane the coordinator already reports as **one fill fleet-wide
(n = 100, t = +0.31, −$34.16 ex-best)** and that MODELS.md §4.4 showed is adverse selection
with a lottery attached (win rate 0.975 → 0.513 with depth).

⇒ **Answer to "is the execution edge reachable on purpose or an accident of being present":
on this decomposition it is an accident of being present.** It is not a depth effect, it is
a stale-quote-arrival effect concentrated in a handful of fills, and nothing in the depth
curve makes it targetable.

### 3b.4 Task 2, re-scoped: does p̂ predict *fillability*?

It does — **with the wrong sign, and it adds nothing to `|est|`.** Joined ledger,
n = 1,590, 18 days, fill rate 0.416:

| predictor | AUC(fill) |
|---|---|
| p_full | **0.0714** |
| p_est | 0.0875 |
| p_full − ask − fee | 0.1842 |
| −\|est\| | **0.9168** |
| seen_ask | 0.6879 |

p̂ residualised on `|est|` **within ask-band × tl-band** still reads AUC 0.085 / 0.298 /
0.438 — **below 0.5 in every cell**. p̂ carries no fillability information that `|est|` does
not already carry, and what it carries points the same way.

This is an independent confirmation of the quant-analyst's mechanism from a different model
and a different feature set: **conviction and withdrawal are the same event.** The p(win)
model is built on the estimator block, so it inherits the estimator's inverse relationship
to availability exactly.

The joint frontier has one cell that is not obviously dead — **top-quartile model edge ×
ask ≥ 0.98: fill rate 0.702, n = 47.** That is 47 attempts. It is a lead, not a result, and
it is underpowered by an order of magnitude.

**Task 2 verdict, both framings:** as a *gate*, p̂ does not beat `|est|` (+0.04 $/day,
t = +0.03, §2). As a *fillability* predictor, p̂ is `|est|` wearing a different hat. Closed.

---

## 4. What this round changed, and what it did not

**Changed**
1. The depth assumption is **measured**, not assumed: φ(2) = 1.92. The sizing rule's headline
   moves +2.723 → **+2.448** (measured), not → +0.326 (feared).
2. A methodological correction worth more than the number: **a partial FAK fill is an exact
   observation of book depth.** Any future question of the form "would a bigger/smaller clip
   have filled" is answerable from the existing ledger by censored estimation. It does not
   need a new recorder, a new fill model, or a live A/B.
3. **Size ≠ price improvement.** §4.4's adverse selection is a price-improvement effect;
   there is no adverse selection in fill *size* at the same price (win 0.97–1.00 across
   4–26 shares). I had been reading the two as one.

**Not changed**
1. The sizing rule's latency tell is still unclean and its deflated t is still negative.
2. 20 day-clusters is still 20 day-clusters. Both live threads (sizing, buffer size) are at
   or below the detection floor of this sample.
3. **The execution edge is not a depth effect.** Decomposing the fleet's realised
   +0.4386 c/share against the same fills at the displayed ask gives +3.467 c/share of
   execution edge, of which **+3.587 is the sweep lane at 11.3 % of shares** — the lane that
   is one fill fleet-wide. §3b.3.
4. **No candidate here is deployable and none is proposed.** The one lane that improved is
   the one whose *remaining* objections are the generic ones this program has never been able
   to answer offline.

**Config count, both rounds:** ~75 (round 1) + ~40 new decision cells (incl. dp10's 6
floor cells and 5 fillability AUCs) = **~115**; √(2 ln 115) = 3.08. Applied: sizing
t +2.76 → **−0.32**; gate family best |t| 0.11 → no
deflation needed; the buffer bound is arithmetic, not a fitted cell.

**Bug-ledger candidates**
* *"`req_sh` is not constant across eras (5/8/9/12/13/24/25/26). Any statement of the form
  'we only ever traded one clip size' must be checked against `req_sh.value_counts()`."*
* *"A partially-filled FAK identifies executable depth exactly (`L = filled`); a fully-filled
  one right-censors it at `req_sh`. Do not model fill rates when the ledger identifies the
  depth distribution directly."*
* *"Fraction-of-displayed-depth-traded is demand-limited and grows ~8× from a 0.2 s to a 5 s
  window. It is a lower bound on realisable depth and must never be used as a fill model."*
