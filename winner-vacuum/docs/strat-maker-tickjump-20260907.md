# The 0.001-TICK JUMP: the first 5m MAKER lane with a positive sign — 2026-09-07

**User brief:** *"keep searching for the maker strategy which will generate profits on 5m markets."*
**Data:** mrec v2 parquet, 7 coins, 2026-09-01 → 09-06, **9,833 bars / 2.73 M prints**.
**Scripts:** `winner-vacuum/tools/mrec/tickjump/` (`lw2.py` = the strategy sim, `lw3.py` = +recon
gate, `field.py` = high-power population estimate, `diag2.py` = the fill-model diagnostic,
`rest.py` / `full.py` / `verify.py` = the refutations below).

---

## 0. ONE-LINE VERDICT

> **Post a bid ONE 0.001-TICK ABOVE the favourite's best bid in the last 30 seconds of the bar.**
> Replay: **+0.52 ± 0.17 c/share, t = 3.07, 6/6 days positive, +$74/day at a 50-share cap.**
> With the fleet's own TWAP-recon gate (`|est_bps| ≥ 2`, `cov ≥ 0.5`): **+0.74 ± 0.12 c/share**.
> ⚠️ **Not a deployment.** 6 days, **7-13 loss events carry the entire downside**, and
> **removing btc leaves +$0.6-3/day** — and this repo has measured replay coin-ranking at
> **r = −0.63 against live**. This is a **log-only pilot candidate**, and the pilot's job is to
> measure ONE thing: *do we actually get filled when we improve by 0.001?*

**Why it is not just another maker cell.** Every previous maker test in this program joined the
touch or rested behind it, in a book whose tick is **0.01**. Above **0.96 the tick is 0.001**
(verified: 14.3% of late-window `ub ≥ 0.96` values are off the 0.01 grid, vs **0.017%** below
0.90). So in that band **price priority costs 0.1 c** instead of 1 c — and the adverse selection
it buys off is worth ~0.6 c. That 10× tick change is the entire strategy.

---

## 1. THE MECHANISM, stated as a reversal of the program's central finding

The repo's standing result is [maker-resting-order-wall](maker-resting-order-wall.md):
*"depth does not pay — it buys a worse selection."* The tick jump is the same law read from the
other end: **queue position determines fill quality, so buying the FRONT of the queue buys the
BENIGN flow.**

Measured on identical bars, tl 2-30, favourite bid ≥ 0.98, 50 sh/bar (`go2.py`):

| placement | bars filled | mean fill px | win rate | **net c/share** |
|---|---|---|---|---|
| **join the touch** (queue-ahead modelled) | 449 | 0.9871 | 0.98598 | **−0.093 ± 0.567** |
| **improve +1 tick (0.001)** | 2,467 | 0.9898 | **0.99480** | **+0.518 ± 0.169** |

Joining fills only **449** bars — and only when the whole displayed queue is swept, i.e. on the
dump that is about to be right. Improving fills **2,467** bars at a **0.9 pp better win rate**
*despite paying 0.27 c more*. The 0.1 c of price priority is the cheapest thing in this book.

## 2. ⭐ THE FILL MODEL, and the diagnostic that decides the whole result

The claim being made is: *a post-only bid at `best_bid + 0.001` intercepts the taker-sell flow
that would otherwise have executed at `best_bid`.* `diag2.py` tests it directly against the tape —
every late-window sell print (tl 2-30, favourite bid ≥ 0.96, `evage < 1 s`), 17,577 prints /
2.26 M shares:

| where the print actually executed | prints | shares |
|---|---|---|
| **exactly AT the displayed best bid** (we would have intercepted it) | **94.69 %** | **87.51 %** |
| above the best bid (somebody had already improved) | 2.60 % | 7.70 % |
| below (walked down through the level) | 2.71 % | 4.79 % |

**The improvement niche is essentially unoccupied.** That is the strongest single piece of
evidence here — and also names the decay risk: the 0.5 c edge supports at most **~5 more ticks**
of competitive improvement before it is gone.

## 3. The strategy, exactly

```
while tl ∈ [2, 30]:                      # last 30 s of the 5-minute bar
    for tok in (UP, DOWN):
        if best_bid(tok) ≥ 0.98 and best_bid(tok) < 0.9985 and book fresh (evage < 1 s):
            keep a POST-ONLY bid at round(best_bid + 0.001, 4)      # never cross the ask
        else: cancel
    stop when SIZE shares are filled for the bar; hold to settlement
```
The `≥ 0.98` gate *is* the favourite selector — the underdog's bid is ~0.01 and never qualifies.
No estimate, no model, no spot feed: it is a pure book rule. Fills are fee-free and earn the
0.2 × 0.07 × q(1−q) rebate (≈ 0.014 c at q = 0.99 — **negligible; this is not a rebate strategy**).

### Parameter response (`go2.py`, all vs the BASE cell above)

| axis | values | net c/share |
|---|---|---|
| improvement | +0 / **+1** / +2 / +3 ticks | −0.09 / **+0.52** / +0.28 / +0.18 |
| window | tl 2-20 / **2-30** / 2-45 / 2-60 / 2-90 | +0.62 / **+0.52** / +0.12 / +0.03 / −0.21 |
| price floor | 0.90 / 0.95 / 0.96 / 0.97 / **0.98** | +0.42 / +0.41 / +0.38 / +0.39 / **+0.52** |
| size cap /bar | 8 / 12 / 24 / **50** / 100 / 250 sh | +0.57 / +0.55 / +0.52 / **+0.52** / +0.54 / +0.48 |
| scan period | 0.2 / **0.4** / 1.0 / 2.0 s | +0.58 / **+0.52** / +0.66 / +0.59 |
| place latency | 0.05 → 0.8 s | +0.41 → +0.51 (**flat**) |
| freshness `evage` | 0.3 / 1.0 / 5.0 s | +0.518 / +0.518 / +0.518 |

⚠️ **Latency- and freshness-flat.** The repo's own tell for a clairvoyant sim
([dual-ask-oscillation-harvest](every-tick-single/dual-ask-oscillation-harvest.md)) is
delay-insensitive PnL. Here it is *structural*, not clairvoyant: a **resting** order's fill
quality does not depend on our reaction time once it is resting — latency only changes how often
we are late to re-quote, and we re-quote rarely (the favourite's bid is nearly static at 0.99).
Recorded as a caveat, not a pass: **the live pilot must re-measure it.**

## 4. ⭐⭐ THE CONTROLS — and they are what make this credible

The tick jump is **not** a universal trick. It works only where the tick is 0.001 (`go2.py`):

| control | bars | net c/share | days + |
|---|---|---|---|
| **mid-bar tick jump, tl 120-290** (tick 0.01, so the jump costs 1 c) | 8,437 | **−1.799 ± 0.227** (t = −7.9) | **0/6** |
| **mid-band 0.30-0.96, tl 2-30** (tick 0.01) | 2,893 | **−0.279 ± 0.291** | 3/6 |
| join the touch, same band and window | 449 | −0.093 ± 0.567 | 4/6 |

Paying 1 c for priority destroys it; paying 0.1 c buys it. The band gate and the tick gate are
the same gate.

## 5. High-power version, and the honest statistics (`field.py`)

Scoring **every** qualifying print instead of a 50 sh/bar clip — 14,482 prints / **1.46 M shares**
/ 2,517 bars, i.e. the capacity-unbounded upper bound:

| | value |
|---|---|
| mean price / win rate | 0.9906 / **0.99570** |
| break-even loss rate at that price | **0.943 %** ; observed **0.430 %** |
| net | **+0.526 c/share**, bar-clustered **SE 0.296**, **t = 1.78** |
| losing bars | **13 of 2,517** |

**t = 1.78 uncapped vs t = 3.07 at a 50-share cap.** Both are real: the cap truncates the loss
bars (a 0.99 entry pays ~1 c and costs ~99 c, so PnL is a count of catastrophes), which is exactly
what a position limit is for. **Quote the capped number as the strategy and the uncapped number as
the evidence that the effect is not significant on 6 days.**

### The two facts that stop this being a deployment
1. **btc is the strategy.** Leave-one-coin-out $/day: drop btc → **+$3.2** (ungated) / **+$0.6**
   (recon-gated); dropping any other coin leaves +$45-83. bnb, doge and hype are negative in every
   configuration (−1.7 to −2.3 c/share, win 0.967-0.973 against a 0.991 break-even).
   ⛔ **This may NOT be turned into "run it on btc only."** The live ledger's own per-coin ≥0.98
   ranking is *bnb +$107 / btc +$77 / … / doge −$49*, and `docs/README §4` records replay-vs-live
   per-coin correlation at **r = −0.63**. Pool or do not run.
2. **The downside is 7-13 events.** Losing bars: 8 (capped) / 13 (uncapped) in six days, none of
   them btc. Day 09-06 alone is **−$530** in the uncapped population. Jeffreys 95 % upper bound on
   the bar loss rate is 0.61 % against a 1.02 % break-even — a **1.7× margin**, on 6 days.

### With the fleet's own TWAP recon gate (`lw3.py`) — quote only the side the arithmetic favours
| gate | bars | win rate | net c/share | $/day |
|---|---|---|---|---|
| none | 2,467 | 0.99480 | +0.518 ± 0.169 | +74.2 |
| `\|est_bps\| ≥ 0.5, cov ≥ 0.5` | 2,201 | 0.99472 | +0.462 ± 0.182 | +57.9 |
| `\|est_bps\| ≥ 2` | 1,604 | 0.99811 | **+0.738 ± 0.119** | +63.2 |
| `\|est_bps\| ≥ 4` | 1,040 | 0.99948 | +0.863 ± 0.052 | +44.3 |

The gate trades volume for margin, monotonically and in the right direction — but the t-statistics
at ≥2 and ≥4 are **artefacts of observing almost no losses** (0.99811 → 0.99948) and must not be
quoted as significance. LOO-coin is unchanged: drop btc → +$0.6/day.

## 6. ⚠️⚠️ THE STRUCTURAL OBJECTION — a maker at 0.99 has no sweep option

[strat-btc-live-ledger §7](strat-btc-live-ledger-20260907.md) established, on 2,347 live fills,
that the ≥0.98 lane **is a break-even grind financing a fat-tailed option**: strip the sweeps and
1,577 fills earn +0.34 % ROI, while 59 sweeps earn +17.4 % and are **61.7 % of all fleet profit**.

**A resting bid can never sweep.** A maker fills at *its own* price — price improvement is
identically zero, by construction. So this lane deliberately buys the half of the ≥0.98 trade that
the live ledger says is *not* the business:

| | ROI on capital at risk |
|---|---|
| live taker ≥0.98, grind only (fee paid) | **+0.34 %** |
| **this maker lane, grind only (fee-free + rebate)** | **+0.53 %** |
| live taker ≥0.98, including sweeps | +0.87 % |

The maker grind genuinely beats the taker grind — no 0.07·p(1−p) fee, plus the rebate — but it is
**a grind, and it is short the tail.** Anyone sizing this must accept: *we are selling 100:1
insurance at 0.99 for a 1.7× margin measured over six days.*

## 7. Capital and feasibility
- Fills average 34.8 sh/bar at ~0.99 ⇒ **≈ $34 per filled bar**; 411 filled bars/day pooled.
- All seven 5m bars close on the same wall-clock boundary ⇒ peak concurrent exposure is
  **7 × clip**. At the fleet's live $24 clip that is **$168 concurrent** against the account's
  $219-253 — feasible; at 50 sh ($49.5) it is **$346** and is not.
- Hold time is **≤ 30 s** to settlement, so capital turns over fast, but redemption latency (not
  modelled here) sets the real concurrency limit.
- Expected at a $24 clip, pooled, ungated: **≈ $39/day** (scaling the 50 sh cell by shares);
  recon-gated ≈ $33/day. For scale, the whole live fleet currently makes **~$14/day**.

## 8. What the pilot must measure (and it is not PnL)
6 days cannot resolve PnL here — 13 events do. The pilot answers the two things the replay cannot:
1. **Do we get filled at `best_bid + 0.001`, and at what rate?** Replay says ~25 % of qualifying
   bars produce a fill at a 50 sh cap. §54's rest lane got **0 fills in 165 orders** — but that
   was the *post-close* snipe at a fixed 0.99, a different window; it is not a contradiction, and
   it is exactly why this must be measured before it is sized.
2. **Does the 0.001 tick actually exist at order time?** The repo has already been bitten
   (notes §24: *"the finer tick only exists after a book's `tick_size_change`"*) — round the price
   DOWN to the token's live tick and log every post-only rejection.

**Proposed arm:** 5-share, log-only, **all seven coins** (never btc alone), `|est_bps| ≥ 2` gate,
tl 2-30, one clip per bar, no ladder, existing halts. Cost ≈ $0. Judge on **fill rate and
rejection count first**, PnL not at all for the first two weeks.

## 9. What this session refuted on the way here

### 9a. ⛔ STATIC DEEP RESTING BIDS on the late favourite — dead, t = −8 to −16 (`rest.py`)
The idea that the sweeps (62 % of fleet profit) could be captured with *time priority* instead of
a latency race: at tl = T₀ place a bid at `fav_bid − Δ` and leave it to the close.

| T₀ | Δ = −1 c | −5 c | −10 c | −20 c | −30 c |
|---|---|---|---|---|---|
| 30 s | −14.2 | −17.4 | −18.3 | −17.1 | −14.5 |
| 45 s | −13.2 | −17.5 | −18.7 | −16.9 | −14.7 |
| 60 s | −13.6 | −17.0 | −18.7 | −18.7 | −15.1 |
| 90 s | −14.0 | −16.4 | −17.8 | −18.2 | −15.9 |

(c/share, t = −8 to −16 everywhere; both a strict "walked-through" fill model and a zero-queue
model give the same answer.) **Filled at a mean 0.58-0.77 and winning 12-58 %.** A static deep bid
only fills when the favourite is collapsing, and then it loses. *A sweep is not a price you can
wait at; it is a price that only exists while the outcome is changing.* This also corrects the
naive reading of the print census — prints at 0.80-0.90 in tl 0-30 win 90.8 %, but that is the
*market* at 0.85, not a bid pre-committed at 0.85.

### 9b. ⛔ No maker rebate tier exists (the reopener named by strat-maker-4060-pooled §5)
Live gamma check, 2026-09-07: every 5m/15m crypto up/down carries
`{rate: 0.07, exponent: 1, takerOnly: true, rebateRate: 0.2}` and `clobRewards: None`.
`rebateRate` varies **by market** (sports 0.15, Fed 0.25) — **not by volume tier**. Nothing to win
by trading more.

### 9c. The full (tl × price) map of the touch-joining maker — every cell negative
`full.py`/`an.py` lifted both caps the program had always run under (q 0.04-0.60, tl 40-270):
8 price bands × 8 tl buckets, terminal PnL, queue modelled. **Every cell is negative**, −1.9 to
−7.3 c/share at t = −3 to −17. Best band 0.00-0.15 (−1.9), worst 0.75-0.90 (−7.3); monotone
improvement toward the start of the bar (tl 240-291 −4.1 vs tl 20-40 −7.5). The single positive
cell (tl < 20, q 0.96-0.999) is **16 fills / 721 shares** — it is the tick-jump lane showing
through a harness that cannot sample it, because `mm.py` skips every epoch where the favourite has
no ask (83 % of late-window seconds). That is what `lw2.py` was written to fix.

---

## 10. ⚠️⚠️ ACCOUNTING CORRECTION to [strat-rebate-farm-20260907](strat-rebate-farm-20260907.md)

Reproducing that document's headline cell exactly (`verify.py`; q 0.04-0.60, tl 40-270, DELTA 0,
50 sh, LAT 0.20, queue modelled — 47,038 fills / 1.53 M shares) gives its components **bit for
bit**: half-spread **+0.868** (published +0.851), adverse selection **−1.562** (published −1.540),
rebate +0.254, **sum −0.441** (published **−0.430**). ✔ The harness agrees.

**But that sum is not the strategy's PnL.** The complete decomposition of what a maker actually
banks is

```
win − q  =  (mid@quote − q)  +  (mid@fill − mid@quote)  +  (win − mid@fill)
             +0.868 half-spread   −4.156  DRIFT  (omitted)    −1.562 adverse
```

| metric, same 47,038 fills | c/share |
|---|---|
| published-style `net` (half-spread + adverse + rebate) | **−0.441** |
| **TERMINAL net (`win − q` + rebate) — the money** | **−4.624 ± 0.382** |
| the omitted term: mid drift between placement and fill | **−4.156** |
| ⇒ fill price minus the mid **at the moment of fill** | **+3.298 c ABOVE mid** |

The drift is not double counting — it is the price moving against us *before* we fill, which is
the whole reason we fill. Dropping it credits the half-spread as if the market had stood still.
The last line is the [resting-order wall](maker-resting-order-wall.md) restated on fresh data
("a bid quoted 1.5 c below mid fills 0.47 c above it" → here, quoted 0.87 c below, fills 3.30 c
above).

**Consequences.**
- The verdict is **unchanged and strengthened**: the mid-bar maker is −4.6 c/share, not −0.4.
- It **resolves the contradiction** with [strat-maker-4060-pooled](strat-maker-4060-pooled-20260907.md),
  which reported **−7.03 c/share** for the same object in the 40-60c band on the same day. That
  document is right; this harness gives −6.68 for the 0.45-0.60 band. The two docs were measuring
  different things, not disagreeing.
- ⚠️ **Anything derived from the magnitude needs re-scoring on terminal PnL** — above all
  *"at LAT = 0 the whole strategy is +0.534 c/share = +$269/day"*. That ceiling is computed on the
  drift-free metric. (It cannot be re-derived here: `mm.py` has no cancel logic, so its latency
  axis is placement-only and is flat on both metrics — the LAT curve belongs to `pess2/qdecay.py`
  and must be re-run there.) The §9 signal-cancel work uses a 1-second markout, which is a
  legitimately different short-horizon estimator and is not affected.

---

## 11. Files
`winner-vacuum/tools/mrec/tickjump/` — `lw2.py` (strategy), `lw3.py` (+recon gate),
`go2.py`/`go3.py`/`risk.py` (batteries), `field.py` (high-power), `diag2.py` (fill-model
diagnostic), `rest.py` (§9a), `full.py`+`an.py` (§9c), `verify.py`+`latsw.py` (§10),
`census2.py` (print census). All read the `pq/` build described in
`winner-vacuum/tools/mrec/README.md`; `mm.py` there needs `evage` added to `load_coin` (done).

---

## 12. HARDENING (agent A, 2026-09-07) — ⛔ the lane is 98.6 % INFEASIBLE: the venue's 0.001 tick arrives ~2 minutes late

Full detail: [strat-maker-hunt-r3-20260907](strat-maker-hunt-r3-20260907.md); scripts
`tools/mrec/tickjump/agentA/`.

**Every book-side attack passed.** Hidden queue: 98.1 % of late-window sell prints execute exactly at
the displayed best bid, 97.7 % fit inside the displayed size, median queue 7,647 sh vs a 12-sh print.
Competition: 12 exact-+0.001 improvements in 3,905 bar-tokens. Capacity: median 100 sh of qualifying
pressure per filled bar; 5/8/12/24 sh clips → +$11/16/22/39 per day. Pre-registered gate **G2 (best
bid ≥ 0.98 for ≥ 5 s before quoting)**: loss bars 8 → 2, **+0.839 ± 0.073 c/sh, +$101/day, all seven
coins positive, LOO-btc +$36/day**. Window: tl 30-60 dead (+0.06); UP/DOWN both positive.

**What failed is the price itself.** 16,212 raw `tick_size_change` events (venue-timestamped,
asset-id-mapped): the 0.01 → 0.001 switch happens **p50 121 s after the favourite's bid first
crosses 0.96**, so **74 % of flips are after the close; only 13 % of decisive bars have the fine tick
by tl 30**, 6.6 % by tl 60. Before the flip 0.991 is rejected (§24 live: `"invalid price, max: 0.99"`).
Restricting §3's fills to instants after the venue flip:

| config | as simulated | **tradeable** |
|---|---|---|
| G0 | 2,467 bars · +$74.2/day | **34 bars · +$1.7/day** |
| G2 | 2,041 · +$101.1 | **26 · +$1.3** |

This reconciles §54/§56's live 0/165 and explains why the niche is empty (§2): nobody improves
because nobody *can*. The post-close flip window is not exploitable either (3 winner-sell prints
at ≤ 0.991 in six days before somebody posts 0.999; median 18 s). **Verdict: ⛔ not a pilot
candidate.** Re-open only if `a12_tick.py`'s *"flips before tl 30"* rises well above 13 %, and then
only as an arm that places nothing until the market's `tick_size_change` has arrived (≈ $1-2/day).
Proposed bug #39 is in the r3 doc.
