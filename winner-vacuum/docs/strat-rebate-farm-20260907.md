# Rebate farming / mid-bar maker — re-measured on mrec v2 (2026-09-06→07)

**User brief:** *"buy in the range 4-60c (50c ideally) a share… UP trades 50, DOWN 51, we place
post-only 49/50. When one side fills, we cancel the other. Also a stop loss (taker). Expect some
profit, but at least daily maker rebates. Probably volume and volatility matter. Date/time window
as well."* Then: **"only btc for now."**

**VERDICT: ⛔ DEAD on btc and fleet-wide — but the Aug 2026 program's stated reason was wrong, and
so were two of this session's own claims.** The strategy loses because a resting bid at the touch
captures **+0.85c half-spread + 0.26c rebate against −1.54c of adverse selection**. Confirmed at
>20σ by the 1-second markout. It responds to nothing tested. Its ceiling at physically impossible
zero latency is **+$269/day**.

Method: optimistic investigator fork → adversarial evaluator fork (instructed to attack the
refutation as well as the leftovers, because a false negative closes a working strategy forever).
Scripts: `tools/mrec/{mm,mm2,pol,an2,rep,runpol,fieldctx,fa,field}.py`, plus the evaluator's
`scratchpad/pess2/{qdecay,tapevar}.py`. Data: mrec v2 parquet, 09-01→09-06, 9,809 bars.

---

## 0. ⭐ THE REBATE MECHANISM — corrected, and better than we had been saying
`feeSchedule` on 5m crypto = `{rate:0.07, exponent:1, takerOnly:true, rebateRate:0.2}`.
Makers pay **no fee**. The rebate is **20% of the taker fee paid against OUR OWN fills** —
**NOT a pool split pro-rata across all makers.**

Empirical anchor (`every-tick-single/EXPERIMENTS.md` §E7): 2026-07-04 credit **+$3.327** for
2026-07-03's **164 maker trades / ~1,312 shares / fee_eq $16.93** ⇒ capture = **exactly 20.0% of
our own fee-equivalent, no pool dilution observed**. Realised **0.254 c/share**.
Live receipts confirm it still pays: 3 MAKER_REBATE payments on the openmm account —
**$1.83 (07-29), $1.91 (08-21), $1.42 (08-22)** — on exactly the days a maker strategy ran, and
$0 liquidity rewards on all 14 recent days (`clobRewards` unfunded since ≥09-02).

**Consequences:** (a) "what share of the $X/day pool can we win" is the wrong question and any
such table (including this session's first pass) should be ignored — your rebate is simply
`0.254c × your filled shares`; (b) the share-weighted alternative (flat 0.198 c/share) is
**refuted**; (c) E7's caveat stands untested — *retest capture if fill volume grows 10×*.

## 1. HEADLINE — net c/share of a resting maker fill, rebate counted
Join the touch, 50sh, tl 40-270, q 0.04-0.60, LAT 0.2s, queue-aware, tape-size-capped (bug #28;
0 of 40,919 fills exceed the window tape). 1,439,442 resting orders → 40,919 fills / 953,833 sh.

| component | c/share |
|---|---|
| half-spread captured | **+0.851** |
| adverse selection | **−1.540** |
| = gross | −0.690 |
| maker rebate | +0.260 |
| **NET (static queue)** | **−0.430 ± 0.500** |
| **NET (queue drain 1.8s, Aug-calibrated — the correct base case)** | **−0.605 ± 0.468** |

**The high-power estimator, and the one to quote:** gross **1-second markout −0.95 to −1.09
c/share in every tl bucket, SE 0.03-0.07**. Even haircutting the ~0.5c that is mechanical (our own
fill removes the touch level and drags the mid), it is ≈ −0.5c against +0.26c of rebate.
Terminal PnL has SE ≈ 0.5 c/share — larger than the rebate — so **5.5 days cannot resolve $/day;
markouts can.**

Per band: .04-.15 +0.150 · .15-.30 −0.273 · .30-.45 −1.389 · .45-.55 −0.126 · .55-.60 −0.030.
Per placement: improve 1 tick −0.554 · **touch −0.430** · 1 behind −0.801 · 2 behind −0.461.
**Depth does not pay** — it buys a worse selection (Aug's finding, re-confirmed on real prints).

## 2. ⭐ btc SPECIFICALLY (the user's scope) — btc is the HARD case, not the easy one
| btc, mid-bar, 4-60c | |
|---|---|
| spread = 1c | **93.4%** of snaps (fleet-wide 36.7%) ⇒ **no room to improve, you must join** |
| touch depth, bid | p25 48 · **median 135** · p75 256 · p90 423 shares |
| touch depth, ask | p25 86 · **median 185** · p75 294 · p90 470 |
| a 50sh quote | 0.4× the median touch; exceeds the whole touch only 25% of the time |
| btc tape in band | 3.34M maker shares/day, $8,848/day of taker fees ×0.2 |

⚠️ **Correction to this session's own first pass:** the "median touch 20-27 shares, so bug #11 does
not apply" claim was a fleet aggregate dominated by the thin alts. On btc the touch is **135-185
shares** and you queue behind it with no room to improve — this is exactly Aug's *"queue position
filters out the GOOD fills"*.

btc net c/share: LAT 0.20 **−0.326 ± 0.663** · LAT 0.15 −0.079 ± 0.683 · with drain **−0.594 ±
0.624**. Negative-to-noise in every variant; positive on 0-2 of 6 days.

## 3. The three attacks that could have overturned the negative — all failed, two BACKFIRED
1. **"`BUY D` prints consume UP bids" — SURVIVED decisively.** The book is one merged book,
   bit-exact: `bsum_u ≡ asum_d` and `asum_u ≡ bsum_d` at **100%** on (ws,t,mts)-exact event pairs.
   Event-level decrement test, 415,216 single-print intervals: `BUY D` moves UP bid₀ size by
   **−9.59 mean / −4.47 median**, the same signature as the unambiguous `SELL U` control
   (−6.02 / −1.04). No double counting (1,726,908 tx for 1,726,908 rows). **And it would not have
   mattered:** the same-token-only counterfactual is **+0.086 ± 1.103 c/share = +$14/day**.
2. **Queue-model pessimism — WOUNDED, and it backfires.** The static model holds queue-ahead
   constant for the order's life; Aug measured cancellations at 2-4× trades (half-life 1.3-2.3s).
   Adding exponential ahead-decay: −0.430 → **−0.605** (1.8s), −0.578 (1.0s). The fills the static
   model discards score **−0.015 ± 0.486** — worthless, not a hidden pool of good fills.
3. **Latency — WOUNDED (the number, not the sign).** A real harness defect was found: the order
   *population* was a function of LAT. Fixed-population curve (2,217,284 quotes at every point):

   | LAT | 0.00 | 0.05 | 0.10 | 0.15 | 0.20 | 0.30 | 0.40 |
   |---|---|---|---|---|---|---|---|
   | net c/sh | **+0.534** | +0.228 | −0.066 | −0.174 | −0.430 | −1.520 | −1.850 |

   "Realistic 0.24-0.30s" was **wrong** — it double-counted a +50ms detection term already inside
   the x-axis and imported the vacmaker's **190ms *place*** round trip into a **cancel** budget.
   The repo's own cancel numbers are openmm **71ms** and CLOB warm p50 **44.9ms** in-pod ⇒
   realistic band **0.13-0.22s ⇒ −$50…−$745/day**, not −$600…−$860.
   **⭐ But the ceiling settles it: at LAT=0 — clairvoyant cancellation, physically impossible —
   the whole strategy is +0.534 c/share = +$269/day.** Winning the latency argument outright buys
   a few hundred dollars a day. That is the number that closes the program.
   (The `41.4% of fills above mid` family IS grid-quantised — `above-mid` is 0.000 for LAT ≤0.10
   by construction. The PnL is not: exposure closes at continuous time against a real print tape.)

## 4. The user's specific mechanics
| variant (q .45-.60, spread ≤2c, 50sh/side/bar, LAT 0.2) | $/day |
|---|---|
| cancel-the-other-on-fill (**the user's design**) | −25.3 ± 107 |
| leave both resting | −19.2 ± 106 |
| cancel + stand down for the bar | −50.7 |
| **+ taker stop-loss @30s** | **−142.5** |
| btc only, cancel-other | +39.1 ± 72 |

- **⭐ "Cancel the other side when one fills" DESTROYS THE PAIR BY CONSTRUCTION** — pair rate
  **0.000** with stand-down vs **0.112** without. The pair is the only structurally positive term
  in the whole design. **Leave-both dominates cancel-other at every size cap.**
- **Taker stop-loss: never beats doing nothing** at any threshold (5s −350, 15s −261, 30s −258,
  60s −271, 180s −216 vs baseline −209). ⚠️ Its first implementation read **+$474/day and was
  LOOK-AHEAD** — it exited only legs unpaired *at bar end*. Causal version = pure transaction
  cost, reproducing Aug's RAND == real verdict. See ledger #29.
- **Pair completion is not free money:** both sides fill in only **11.1%** of bars; the pair sum
  averages **1.0373** (median 1.03) and only **24.6%** of completed pairs sum below 1.00.

## 5. Conditioning — the user's three predicted levers all land flat
- **Time-of-day: noise.** 24 hourly cells swing +3.8 to −6.6 c/share at SE ≈1.2; 6h buckets
  +1.51 to −2.78. **Day-of-week: noise.** (Textbook of "permutation nulls read t≈2-3 on noise".)
- **Volume: no separation.** Trailing-10s hostile-volume quintiles −0.78/−3.62/−0.51/−0.52/−0.33;
  fill rate rises 0.7%→8.6% but c/share does not move. Previous-bar volume: same.
- **Volatility: no predictive power at 5m** (−1.63/−0.12/+0.34/+0.07) — extends Aug's 1h verdict.
- **Book imbalance: could NOT reproduce Aug's monotone gate** (−0.94/+0.80/−1.48/+1.31).
- Aggressor-signed flow imbalance (new in v2): noise. Min-touch-age gate: noise.
- **Time-within-bar is the ONLY structural gradient**: tl 240-270 (bar seconds 30-60) **+0.418
  c/sh**; 180-270 −0.281; 120-240 −0.487; 40-120 **−1.413**. Replicates Aug's "+0.411 first minute".
- Spread: 1c −0.257 · 2c −0.914 · 3c −0.684 · 4c −0.752 · 5c −2.568.
- **Multiple comparisons kill the leftovers.** ≈70+ cells were searched at SE ≈1.5c ⇒ expected
  max under a true null ≈ **+3.5c**. The best cell is **+1.3c = 0.85σ**. Deep band (q≤0.15) and
  doge both die under the queue-drain correction.

## 6. ⚠️ TWO METHODOLOGY CATCHES worth more than the strategy
1. **The RAND control used throughout this lane is VACUOUS.** Fills have share-weighted
   q = **0.3080** and true win rate **0.3012**; shuffling outcomes assigns ≈50%, so RAND **must**
   return `(0.5 − 0.308)·100 + rebate = +19.46` by arithmetic (measured +19.81 ± 0.71). It
   measures the mean quote price, nothing else. Aug's RAND was meaningful because it ran on a
   *pair* engine with a symmetric price mix; this one is not. **The valid version:**
   `E[win − mid]` over all quotes **+0.233c** vs over filled **−1.540c** ⇒ dynamic adverse
   selection **−1.77 c/share** against +1.11c of carry. See ledger #30.
2. **"Field makers earn +0.502 c/share ≈ $11,087/day, the gap is our reaction time" — WITHDRAWN.**
   Decomposed: 82% of those dollars come from prints **>100 shares** (maker selection +0.653 —
   the maker wins against big takers); the **20-100 share bucket where a 50sh quote lives is
   −0.056**. By price vs mid: below-mid 67.7% of volume at +1.183; **above-mid — our population,
   41.4% of our fills — −1.468**. A single 6.4% slice (makers quoting ~7c below mid in a wide
   book) is worth +$13,660/day on its own. And `attouch` scores a print against the touch *at the
   moment of the print*, so essentially no field "at-touch" fill is above the mid while 41.4% of
   ours are. **This is the "a field-average cell is NOT the subset you will get" trap, hit for the
   fifth time in this program.**

## 7. What is NOT refuted (and it is not rebate farming)
> Two-sided post-only at the touch, q .45-.60, spread ≤2c, **first 60 seconds of the bar only**,
> **leave BOTH sides resting — do not cancel the other, do not stand down**, no taker stop-loss.

**+$45.1 ± 90/day at LAT 0.15; −$6.3 ± 96 at LAT 0.20.** Indistinguishable from zero, but the only
cell positive in all four fill models. That is a **log-only arm, not a capital allocation.**

**The one genuinely untested mechanism: a SIGNAL-DRIVEN cancel.** Every sim here cancels for
exactly one reason — the touch moved. It never cancels on a spot move, a large print, or an
imbalance shift, all observable *before* the touch moves, and the −0.95 c/share 1-second markout
is direct evidence the information is there a second early. ⚠️ But note what that is: a
**directional model with maker execution**, not rebate farming — and this repo has already refuted
the directional models ([[market-efficiency-proof]], [[structure-hunt-exhausted]]).

## 8. What would settle the rest
**Offline, cheap:** re-score every cell with a price-stratified (not RAND) control — no cell in
this lane currently has a valid selection control; make queue-drain the base case, not the static
model; test the signal-driven cancel; and wait ~6 weeks for terminal SE to drop below the rebate.
**Live, and only two quantities:** our true *detect → cancel-effective* time (the entire x-axis),
and whether our own 50 shares displace the flow we are modelling ourselves into. A **5-share,
log-only, first-60s btc arm** answers both for ≈$0 — with the Aug pilot's warning attached: all
six live bugs there were state-reconciliation, not strategy, and this design has the same shape.

---

## 9. ⛔ THE SIGNAL-DRIVEN CANCEL — TESTED AND DEAD (2026-09-07, the last open mechanism)

Harness `scratchpad/sig/{sig,diag,score,audit}.py`, started from `pess2/qdecay.py`; base arm
reproduces the published headline **bit-for-bit** (static `mo1 −0.919 ± 0.037`, `net −0.326 ±
0.663`; drain HL=1.8 `net −0.594 ± 0.624`). btc 5m only, 6 days, 285,279 resting orders,
30,844 fills / 1,097,929 shares. Base case = queue-drain HL 1.8s, LAT 0.20, tape-size capped.

**Information set at the cancel instant (written down first, audited after):** snapshots at
index ≤ j, prints at t ≤ st[j], our own q/t0/ahead. Cancel effective at st[j]+LAT, so every
avoided print is strictly ≥ LAT in the trigger's future. `audit.py` re-derives 9,566 avoided
prints from the raw tape: **0 violations, min observed lead 0.2001s.**

### Pre-registered criteria — (a) FAILED by every trigger
| criterion | result |
|---|---|
| (a) **d(1s markout) > +0.30 c/share**, matched population | ⛔ best = **+0.163** (fitted 21-signal combo); best single = **+0.107** |
| (b) ≥4 of 6 days positive | ✅ for the spot triggers (6/6) |
| (c) placebo (donor-bar signal, rate-matched) must not reproduce | ✅ for spot (placebo −0.001); ⛔ qdep/dimb partly are placebo |

### Per trigger (LAT 0.20, drain HL 1.8; base mo1 −0.717, 1,097,929 sh)
| trigger | share ret. | fills | mo1 | **d_mo1 ± SE** | placebo | days+ |
|---|---|---|---|---|---|---|
| spot move ≥0.5bps / 0.3s | 0.916 | 28,303 | −0.610 | **+0.107 ± 0.011** | −0.001 | 6/6 |
| … same, **cancel-only** (may not fire at placement) | 0.979 | 30,265 | −0.659 | **+0.058 ± 0.007** | — | 6/6 |
| our-level queue depletion ≥70% / 2s | 0.462 | 14,041 | −0.637 | +0.080 ± 0.030 | **−0.075** | 4/6 |
| … same, **cancel-only** | 0.697 | 22,327 | −0.732 | **−0.014 ± 0.015** | — | 2/6 |
| depth-imbalance shift, cancel-only | 0.814 | 25,628 | −0.720 | −0.002 ± 0.010 | — | 4/6 |
| LOO-fitted 21-signal combo (best threshold) | 0.649 | 20,033 | −0.557 | **+0.160 ± 0.019** | −0.056 | 6/6 |
| **aggressor-signed flow imbalance ≥0.5 / 0.3s** | 0.198 | 6,890 | −1.081 | **−0.364 ± 0.067** | −0.105 | 0/6 |
| **hostile volume ≥25sh / 0.3s** | 0.308 | 10,647 | −1.043 | −0.326 ± 0.039 | −0.095 | 0/6 |
| **large print ≥50sh / 0.3s** | 0.557 | 18,249 | −0.859 | −0.141 ± 0.024 | −0.052 | 0/6 |

⭐ **Two structural results, both new:**

1. **Aggressor flow, print size and flow imbalance are ANTI-predictive of toxicity**, monotone in
   aggressiveness, 0/6 days positive, ~10σ. Cancelling on visible order flow throws away the
   *good* fills: benign flow is what a maker gets paid for, and the toxic fill arrives with no
   flow warning at all. This is Aug's *"43 of 48 loser-singles filled at FLAT lead velocity"*
   generalised from spot velocity to the whole observable flow — and the sign is not merely null,
   it is **negative**. ⇒ **Never gate or cancel a maker quote on trade flow in this market.**
2. **qdep / dimb are ENTRY GATES wearing a cancel's clothes.** Their whole effect vanishes when
   the trigger is forbidden from firing at the placement snapshot (+0.080 → −0.014). Depth
   conditioning was already refuted as an entry gate (§5); it is not resurrected as a cancel.

### ⭐⭐ THE MECHANISM: the information's half-life is ~0.15s
LOO-fitted 21-signal ranker read at `tf − Δ`, **fill population held fixed**, keep 80%:

| lead time Δ before the fill | 0.1s | 0.2s | 0.3s | 0.5s | 1.0s | 2.0s | 4.0s |
|---|---|---|---|---|---|---|---|
| best achievable **d_mo1** | **+0.340** | +0.181 | +0.069 | **−0.031** | −0.025 | −0.020 | −0.004 |

The pre-registered +0.30 bar is crossed **only at Δ = 0.1s** — a total detect→cancel-effective
budget of 100 ms, against the repo's own measured **71 ms cancel round trip alone**, before feed
delay and decision time. By 300 ms the signal is gone; by 500 ms it is **negative**. The −0.92
c/share 1-second markout is *not* evidence that the information exists a second early: it exists
for roughly **150 milliseconds**, and the marking-out happens afterwards.

### Positive control (proves the harness has the power)
A deliberately **non-causal** trigger — cancel when spot moves ≥0.5 bps over the **next** 0.5s —
scores **d_mo1 +0.404 ± 0.019** while retaining 90.5% of shares. So the harness detects a real
signal at 21σ when one is present; the causal nulls are not a power failure. **And even that
clairvoyant cancel leaves mo1 at −0.313 and net at −0.208 c/share** — cheating about the spot
half a second ahead does not make the lane profitable.

### Why a signal cancel cannot help even in principle here
Base net by LAT (drain HL 1.8): 0.05 **+0.000** · 0.10 −0.157 · 0.15 −0.330 · 0.20 −0.594.
The signal cancel adds +0.069 at LAT 0.10 and +0.037 at LAT 0.05 — it is **redundant with
speed**, because it is made of the same 150 ms. A cancel trigger cannot buy latency; it spends it.

### VERDICT
⛔ **There is no signal-driven cancel that beats touch-move-only on btc.** One trigger is real,
causally clean and placebo-surviving — spot move ≥0.5 bps over 0.3s, **+0.058 ± 0.007 c/share**
as a pure cancel, 6/6 days — and it is **10× too small** to close a −0.594 c/share hole. This
closes the mid-bar rebate-farm lane on a **structural bound, not on absence of effort**: the
adverse-selection information in this book lives inside the cancel round trip. The only remaining
lever is the one §3 already identified — **latency** — and §3 already priced winning that argument
outright at +$269/day at physically impossible zero.

## 10. ⛔ "MAKER one leg + TAKER the other leg" — closed BY AN IDENTITY, not by a measurement (2026-09-07)
User proposal: *"taker other leg for the same dollar amount"* — rest a post-only bid on one side,
and when it fills, take the other side to complete the pair.

**It cannot work, and the reason needs no simulation.** `ua ≡ 1 − db`, so at any instant the
UP bid and the DOWN ask are complements. Measured on the fresh btc build:

> **UP bid + DOWN ask = exactly 1.000 in 100.00% of 1,066,015 btc mid-bar snapshots** (mid 0.30-0.70,
> tl 40-270). Not approximately — the max deviation is 0.00 to two decimals and the p1/p99 are both 1.000.

So completing the pair as a taker at the touch costs **exactly** what the maker leg saved. Gross is
identically zero, and the costs are one-sided:

| at q ≈ 0.50 | c/share |
|---|---|
| taker fee on the completing leg, `0.07·q(1−q)` | **−1.75** |
| maker rebate on our own maker leg, `0.2·0.07·p(1−p)` | +0.35 |
| **net, by construction** | **−1.40** |

Break-even requires a share-matched pair sum below **0.986**. Waiting for one does not help — the
distribution is **symmetric about exactly 1.000 at every delay**, so waiting is a directional bet
carrying a 1.4c handicap:

| completion delay | share of moments < 1.00 | **< 0.986 (break-even)** | mean sum |
|---|---|---|---|
| 0.0s | 0.0% | 0.0% | 1.000 |
| 0.2s | 7.9% | 3.2% | 1.000 |
| 0.5s | 13.6% | **6.8%** | 1.000 |
| 1.0s | 19.6% | 11.0% | 1.000 |
| 2.0s | 25.7% | 16.6% | 1.000 |

And it is worse than that in practice: our own maker fill consumes the level we were resting at, so
the completing leg is typically taken *after* the touch has moved against us.

### ⚠️ "The same dollar amount" is also the wrong leg sizing — it converts an arb into a coin flip
- **Equal SHARES** `n` at prices `p`, `q`: cost `n(p+q)`, payoff `n` ⇒ profit `n(1 − p − q)`,
  **independent of the outcome**. An arbitrage iff `p + q < 1`.
- **Equal DOLLARS** `X` per leg: you hold `X/p` and `X/q` shares for a cost of `2X` ⇒ profit is
  `X(1/p − 2)` if the first side wins and `X(1/q − 2)` if the other does. Profitable in **both**
  outcomes only if `p < 0.5` **AND** `q < 0.5` — strictly stronger than `p + q < 1`.

Worked example at `p = 0.30`, `q = 0.65` (sum 0.95, a genuine 5c edge on shares):
share-matched 100/100 = **+$5 guaranteed**; dollar-matched $50/$50 = **+$66.67 or −$23.08**,
a coin flip. **If anything ever pairs on this venue, it must be SHARE-matched.**
The one construction not yet measured is replacing the taker completion with a **mint** (pair for
$1 via the collateral adapter) and a maker-side exit of the unwanted leg — that swaps the 1.75c
taker fee for queue risk. Being scanned; `mintsalvage`'s prior death was at 0.99, a different cell.

---

## 11. ⚠️⚠️ ACCOUNTING CORRECTION (2026-09-07, later session) — `net c/share` above omits the
   placement→fill mid drift, and is ~10× too small

The headline cell of §1 reproduces **bit for bit** on a fresh run of the same harness
(`winner-vacuum/tools/mrec/tickjump/verify.py`; 47,038 fills / 1.53 M shares): half-spread
**+0.868** (vs +0.851), adverse selection **−1.562** (vs −1.540), rebate +0.254, sum **−0.441**
(vs the published **−0.430**). The harness is fine. The *arithmetic of the table* is not complete:

```
win − q  =  (mid@quote − q)  +  (mid@fill − mid@quote)  +  (win − mid@fill)
             +0.868 half-spread   −4.156  DRIFT — MISSING   −1.562 adverse selection
```

| same 47,038 fills | c/share |
|---|---|
| this document's `net` (half-spread + adverse + rebate) | −0.441 |
| **TERMINAL net (`win − q` + rebate) — what is actually banked** | **−4.624 ± 0.382** |
| ⇒ the fill price vs the mid **at the moment of fill** | **+3.298 c ABOVE mid** |

Crediting the half-spread measured at placement while measuring adverse selection only from the
fill instant drops the price move *between* the two — which is precisely the move that caused the
fill. **The verdict of this document is unchanged and strengthened** (−4.6 c/share, not −0.4), and
it now **agrees with [strat-maker-4060-pooled](strat-maker-4060-pooled-20260907.md)'s −7.03 c/share**
instead of appearing to contradict it by 16×.

⚠️ **Re-score before reusing any magnitude from this doc**, above all §3's *"at LAT = 0 the whole
strategy is +0.534 c/share = +$269/day"* — that ceiling is computed on the drift-free metric and
must be re-run on terminal PnL in `pess2/qdecay.py` (which owns the cancel-latency axis; `mm.py`
has no cancel logic). §9's 1-second markout is a legitimately different short-horizon estimator
and is **not** affected.

Full write-up, plus the one maker lane that survived this pass:
[strat-maker-tickjump-20260907](strat-maker-tickjump-20260907.md).
