# btc vacmaker — the LIVE FILL LEDGER (2026-09-07). What actually makes the money.

**This document supersedes every replay-derived conclusion about which btc price band is
profitable.** Source: `btc-vacmaker` pod, `logs/logs-training-events.jsonl` + rotated archives,
read-only `kubectl exec`. Events `PF_TE_WHALE_ORDER` (carries **`seen_ask`** — the displayed ask
the bot actually saw — plus `req_px`, `req_sh`, `matched`, `avg_px`, `filled`, `cost`, `est_bps`,
`tl`) joined to `PF_TE_LIVE_SETTLE` (`won`) by bar.

**482 live order attempts / 316 settled fills, 2026-08-17 → 09-06.** Three weeks, 5× the mrec
replay window, and immune to every fill-model question that has dominated this program.

---

## 1. ⭐ BUG #23, RECALIBRATED — the live FAK match rate by DISPLAYED ask

| displayed (seen) ask | attempts | matched | **live match rate** | previous doc anchor |
|---|---|---|---|---|
| 0.55-0.75 | 44 | 11 | **25.0%** | 11.2% (08-23, n=295) |
| 0.75-0.85 | 17 | 8 | 47.1% | — |
| 0.85-0.90 | 49 | 20 | 40.8% | — |
| 0.90-0.95 | 59 | 34 | 57.6% | — |
| 0.95-0.98 | 142 | 111 | 78.2% | — |
| ≥0.98 | 171 | 124 | **72.5%** | 75% ✓ |

The cheap band fills **2.2× more often than the documented anchor**. Use these numbers.

**Price improvement on 308 matched orders** (`seen_ask − avg_px`): mean **+0.90c**, median 0,
≥1c **16.2%**, ≥5c **5.8%**, ≥10c 2.9%, ≥20c 0.65%, max **80c**; and **33.1% fill ABOVE the
displayed ask**. ⚠️ This partially corrects §68-2, which put ≥5c improvement at 1.3% (0.2s) /
3.0% (0.4s) and called the windfalls a latency artifact — the live rate of 5.8% implies an
effective window nearer **1 second**. The windfalls are more real than §68-2 claimed.

## 2. The current era is clean, and the §37 timing fix is confirmed on live fills
Splitting at 08-22 (when the vol-condition was removed and the tl gate tightened):

| era | tl>25 | tl≤25 |
|---|---|---|
| pre-fix (<08-22) | 55 fills, **5 losses, −3.59% ROI** | 62 fills, 0 losses, +7.48% |
| current (≥08-22) | 6 fills, 0 losses, +4.51% | 182 fills, 4 losses, +3.66% |

**All 5 of the tl>25 losses are pre-fix.** §37 worked. Current era: **188 fills, +$98.24 on
$2,675, ROI +3.67%, win 97.9%, 4 losses** — and the last loss was **2026-08-25**, i.e. 12 clean days.

## 3. ⛔ NO ASK FLOOR HELPS. Every floor costs money (current era, gate on the DISPLAYED ask)

| floor on `seen_ask` | fills | losses | pnl | ROI | forfeited |
|---|---|---|---|---|---|
| **none (live config)** | 188 | 4 | **+$98.24** | +3.67% | — |
| ≥0.75 | 182 | 3 | +$85.43 | +3.25% | **−$12.81** |
| ≥0.90 | 171 | 1 | +$80.60 | +3.22% | **−$17.64** |
| ≥0.95 | 165 | 1 | +$77.20 | +3.14% | **−$21.04** |
| ≥0.98 | 141 | 0 | +$77.42 | +3.44% | **−$20.82** |

All 4 current-era losses come from a displayed ask below 0.95 — **but that band is still net
positive at the highest ROI in the book** (23 fills, +$21.04, **+9.61% ROI**). Keep MIN_ASK 0.55.

**This kills the MIN_ASK 0.90 proposal from three independent offline analyses (§72-3, the btc5m
scan, and the lead's own verification). See bug #33.** The replays gated on the *realised fill
price*; a live gate can only key on the *displayed* ask, and with slippage those are different
variables. In a replay with no slippage they are the same variable, which is why every replay
got it backwards.

## 4. ⭐⭐ WHERE THE MONEY ACTUALLY COMES FROM — the stale-ask sweep is the engine

| class (current era) | fills | losses | cost | pnl | ROI | % of profit |
|---|---|---|---|---|---|---|
| **SWEEP — filled ≥5% below the displayed ask** | 9 | 2 | $110.60 | **+$39.26** | **+35.5%** | **40.0%** |
| filled ABOVE the displayed ask | 25 | 0 | $322.43 | +$19.77 | +6.1% | 20.1% |
| filled at the displayed ask | 154 | 2 | $2,242.43 | +$39.21 | +1.7% | 39.9% |

And the sweeps split by where they were fired from:

| sweep origin (displayed ask) | n | pnl |
|---|---|---|
| ≤0.90 (we deliberately took a cheap ask) | 5 | **−$4.52** |
| 0.95-0.98 | 1 | +$6.32 |
| **≥0.98 (a stale 0.99 that collapsed in our favour)** | **3** | **+$37.46** |

> **Firing at a displayed 0.98-0.99 is not merely "the grind" — it carries a free option on the
> book collapsing in our favour while our marketable order is in flight.** Deliberately taking a
> cheap displayed ask is the opposite trade and is net negative.

Worked example, 2026-08-25: displayed **0.99**, requested 8 shares, **filled 41.68 shares at
$0.19** for $7.92 → **+$33.76**, a 426% return on one clip. That single fill is 34% of all
current-era btc profit.

## 5. 🟡 THE ONE ACTIONABLE PROPOSAL — raise the CLIP SIZE in the displayed ≥0.98 band
Evidence, all live:
- **displayed ≥0.98, full window: 198 fills, ZERO losses, +$87.50 on $2,695, ROI +3.25%.**
  Jeffreys 95% upper bound on the loss rate: **0.96%**, against a break-even loss rate of ~3.2%
  at that ROI — a 3× margin.
- **Depth is not the constraint.** btc displayed top-of-book at ask ≥0.98, tl 3-20 (mrec, n=562):
  median **$1,253**, p25 $357. The top level alone covers a **$48 clip 92.7%** of the time and a
  $96 clip 89.5%. (The oft-quoted "$29 median top-of-book" is a fleet-wide, all-bands figure and
  does not apply to this band on btc.)
- **We are not even using the current cap**: mean clip cost in that band is **$15.09** against a
  $24 cap; fill ratio ≈1.0 (we get what we ask for).
- **The sweep option scales linearly with clip size** and is 57% of that band's profit. The
  08-25 windfall was an $7.92 clip; at $24 it would have been ~$102.

⚠️ **Honest risks.** (a) §65-2 refuted raising the *ladder* cap — that was multi-clip-per-bar
laddering dominated by the mid band, a different object from first-clip size in the safest band,
but it is the nearest contrary evidence. (b) 0 losses in 198 is not zero probability; size the
change against the 0.96% upper bound, not against the observed 0. (c) Account balance has been
$219-253, so a $48 btc clip is affordable but should be checked against the whole fleet's
concurrent exposure. (d) btc only — this has not been checked on other coins.

**Suggested test:** raise the first-clip cap on btc only, at displayed ≥0.98 only, from $24 to
$36-48, leaving every other band and the ladder untouched. Judge on loss count first (expect to
stay at 0) and on the sweep windfalls second.

## 6. Standing recommendations
1. **Never settle a per-band gate from a replay again** (bug #33). `PF_TE_WHALE_ORDER` +
   `PF_TE_LIVE_SETTLE` answer it directly and take one `kubectl exec`.
2. **Log the displayed size** alongside `seen_ask` on every order event — one line, and it makes
   the depth/fill-rate question continuously measurable per band. `req_px` is currently present
   on only 11 of 316 settle rows and should be on all of them.
3. Do not pilot the bid-drop veto on btc (it misses the loss that makes the worst day) and do not
   apply an ask floor.

---

## 7. ⭐⭐ CROSS-COIN VALIDATION — the sweep finding GENERALISES, and it reframes the strategy
Same construction, all seven live ledgers pulled, current era (≥08-22): **2,347 live fills,
+$220.53** (~$14/day, consistent with the day-close record).

| class | fills | losses | cost | pnl | ROI | **% of ALL fleet profit** |
|---|---|---|---|---|---|---|
| **SWEEP — filled ≥5% below the displayed ask** | **59** (2.5%) | 16 | $780.61 | **+$136.15** | **+17.44%** | **61.7%** |
| filled ABOVE the displayed ask | 431 | 13 | $5,904.44 | +$37.80 | +0.64% | 17.1% |
| filled at the displayed ask | 1,857 | 61 | $22,750.26 | +$46.58 | **+0.20%** | 21.1% |

Sweeps by origin — the btc pattern holds and sharpens:

| displayed ask fired from | fills | losses | cost | pnl | ROI |
|---|---|---|---|---|---|
| ≤0.90 | 28 | 11 | $325.40 | +$38.64 | +11.9% |
| 0.90-0.95 | 6 | 1 | $66.25 | +$4.19 | +6.3% |
| 0.95-0.98 | 11 | 4 | $189.97 | **−$43.63** | **−23.0%** |
| **0.99** | **14** | **0** | $198.99 | **+$136.95** | **+68.8%** |

### ⭐⭐ THE REFRAMING: this is not a 97%-win grind. It is a break-even grind financing a fat-tailed option.
The ≥0.98 band is 1,597 fills for **+$191.47 (ROI +0.87%)**. Strip out its 20 sweeps and the
remaining **1,577 fills earn +$74.36, ROI ≈ +0.34%**. At a 0.99 entry a win pays ~1c against a
99c stake, so break-even is a **~0.99% loss rate**; the observed fleet rate in that band is
**19/1,597 = 1.19%**. **The grind pays for itself and little more. The business is the option on
a stale displayed ask collapsing in our favour while the marketable order is in flight.**

### ⚠️ This makes the §5 sizing proposal RISKIER, not safer
btc's 0-losses-in-198 at ≥0.98 is partly luck. Fleet-wide that band carries **19 losses in 1,597
fills**, and per coin the same band ranges **bnb +$107.04 / btc +$77.42 / sol +$38.36 / hype
+$16.03 / eth +$1.36 / xrp +$0.24 / doge −$48.98**. Raising the clip scales a **fat tail in both
directions**, not a steady grind — the 2 hype sweep-losses at a displayed 0.98 cost −$31.68 between
them. Size the proposal against the fleet's 1.19% loss rate, never against btc's observed 0%.

### The one clean cell
**Sweeps originating from a displayed 0.99: 14 fills, ZERO losses, +$136.95, +68.8% ROI — 62% of
all fleet profit.** Sweeps originating from a displayed 0.98 exactly: 6 fills, 2 losses, −$19.84.
That one-cent distinction is worth more than any gate tested this session; it is n=14 and must not
be traded on until it is n=50.

---

## 8. ⭐⭐ THE FIRE WINDOW — a large live ROI gradient, but ⚠️ SEE §9: the paired counterfactual is NOT supportive
> ⚠️ **READ §9 BEFORE ACTING ON THIS SECTION.** The tl gradient below is a real *population*
> difference in live fills. §9 tests the *causal* question — what happens to the SAME bars if we
> delay — and finds delaying is mildly NEGATIVE on the ordinary component. The two are reconciled
> in §9; the honest verdict is "unresolved, and it hinges on the sweep option".

## 8. THE TL GRADIENT IN LIVE FILLS (live fills, all coins)
The live gate is `tl ∈ [3,20]` and the bot fires at the **first qualifying moment** — which is the
top of its own window. The consequence, within the displayed ≥0.98 band, current era:

| tl (seconds left) | fills | losses | sweeps | cost | pnl | **ROI** |
|---|---|---|---|---|---|---|
| 0-12 | 130 | 1 | 5 | $1,759 | **+$89.41** | **+5.08%** |
| 12-16 | 265 | 2 | 6 | $3,637 | +$43.88 | +1.21% |
| **16-20** | **1,194** | 16 | 9 | **$16,563** | +$57.21 | **+0.35%** |

**75% of fills and 87% of capital go into the worst cell.** And the sweep rate — the profit engine
(§7) — is **5× higher** at tl≤12 (3.8%) than at tl 16-20 (0.75%).

### It is not composition, and it is not the windfalls
- **Comparable populations**: tl≤16 vs tl>16 have mean displayed ask 0.984 vs 0.986, mean fill
  0.980 vs 0.984, mean clip cost $13.66 vs $13.83. The late group's mean **|est| is LOWER**
  (1.011 vs 1.673) — it wins *despite* a weaker signal, which strengthens the result.
- **⭐ With ALL sweeps removed**, the effect is still there and cleaner:

| (sweeps excluded) | fills | losses | loss rate | cost | pnl | ROI |
|---|---|---|---|---|---|---|
| tl 16-20+ | 1,193 | 15 | 1.26% | $16,460 | +$24.85 | **+0.151%** |
| **tl≤16** | 384 | 2 | **0.52%** | $5,249 | +$49.50 | **+0.943%** |

**6.2× the ROI at less than half the loss rate.**
- **Per coin, tl≤16 wins in 6 of 7**: bnb +9.77% vs +1.27%, eth +2.30% vs −0.43%, xrp +1.63% vs
  −0.63%, sol +1.79% vs +0.95%, hype +0.60% vs +0.38%, doge −1.55% vs −2.59%. Only btc goes the
  other way (+1.63% vs +3.78%) and its late cell is n=22.

### ⚠️ This REPLICATES §65-5 and REFUTES my own §68-7 replay
§65-5 measured, on 21 days of live fills, tl 16-20 = +0.28% ROI vs tl 12-16 = +1.19%, flagged it
as a LIVE CANDIDATE, and it was never deployed. **§68-7 then "refuted" it from a replay** on the
grounds that narrowing the window loses 45-55% of the stake. The stake loss is real, but the
replay's ROI estimates came from the wrong fill population (bug #33 again) — the live ROI gap is
**6.2×**, far larger than the replay's 1.5×, and it comfortably outweighs the stake loss.

**Rough sizing** using §65-5's measured persistence (tl18→tl13 = **68.8%** of asks survive):
0.688 × $16,634 of tl>16 stake = ~$11,400 re-staked at the tl≤16 rate ⇒ **+$108 (ex-sweeps) to
+$285 (incl. sweeps)** against the **+$58** those fires actually earned — i.e. roughly
**+$3 to +$13/day** on a fleet making ~$14/day.

**Caveats, in order of seriousness:** (a) §65-5's own caveat stands — the 31% of asks that vanish
while we wait may be the *surest* winners, so realised ROI on the survivors may be below the
observed tl≤16 cell; (b) this is a behavioural change to the highest-volume cell, so per the 08-22
lesson it must be **single-coin A/B, never fleet-wide**; (c) btc is the one coin where it does not
hold, and btc is the user's scope — so the pilot coin should be **bnb, eth or xrp**, not btc.

---

## 9. ⚠️ SELF-CORRECTION to §8 — the paired counterfactual says delaying is NOT free
§8 compared **different populations** of live fills (bars that happened to fire late vs early) and
inferred that moving the gate later would capture the late cell's ROI. That inference does not
follow. The causal question is what happens to **the same bars** if we delay, and mrec answers it
directly (7 coins, 09-01→09-06, live gates, displayed asks, fee-exact — `verify/persist.py`):

**1,101 bars carry a fireable ask at tl 16-20. 70.7% still carry one at tl 12-16** — an
independent confirmation of §65-5's 68.8% persistence estimate.

**§65-5's caveat (a) is REFUTED — the vanishing asks are not the surer winners:**

| | bars | win% | mean ask | **EV/share, fee-exact** |
|---|---|---|---|---|
| persists to tl 12-16 | 778 | **94.99%** | 0.9042 | **+4.04c** |
| vanishes | 323 | 92.88% | 0.9549 | **−2.86c** |

The bars that vanish were the **negative-EV** ones (92.88% win against a 0.955 ask). Waiting
filters them out. Good news — but not the whole trade:

**⛔ The price moves AGAINST us while we wait.** On the persisting bars the ask goes
**0.9042 → 0.9195 (+1.53c)**; only 5.7% are cheaper later, 29.6% dearer. So:

| policy | EV per bar-opportunity |
|---|---|
| fire at tl 16-20 on everything | **+2.016c** |
| delay to tl 12-16 (persisting bars only) | **+1.829c** |
| | **−0.187c, i.e. −9.3%** |

Per share *deployed* delaying is better (+2.59c vs +2.02c) — a better ROI on less volume — but
**supply, not capital, is this strategy's constraint**, so total EV is the objective and delaying
loses ~9%.

### How to reconcile §8 and §9
Both are correct about different things. §8's live gradient is real but is a **selection effect**:
bars that naturally fire late are those whose ask appeared late or whose `est` qualified late, and
they are a better population than bars we would delay into. §9 is the causal experiment and it is
mildly negative **on the ordinary component**.

**The unresolved term is the sweep option, and it is large enough to flip the sign.** §9 measures
displayed asks and therefore cannot see sweeps; but the live sweep rate is **5× higher at tl≤12
(3.8%) than at tl 16-20 (0.75%)**, and sweeps are **61.7% of all fleet profit** (§7). A 3pp higher
sweep rate at ~+$7 per sweep is worth ~+21c per fire — an order of magnitude more than the −0.19c
the ordinary component loses.

**Verdict: the fire-window shift is UNRESOLVED, not established.** It hinges entirely on whether
the higher late-window sweep rate is causal (delaying into tl≤12 produces sweeps) or selection
(bars that sweep are the ones whose asks were stale, and staleness is why they were still there
late). **That is exactly the question the sweep-prediction model was commissioned to answer.**
Do not quote §8's "+$3 to +$13/day" — it is not supported by the paired test.

---

## 10. ⭐ WHAT THE SWEEP ACTUALLY IS — the bot's own stale market view (verified 2026-09-07)
§7 called the stale-ask sweep "the engine" (61.7% of fleet profit). The mechanism is now known and
it is not a market phenomenon: **it is our own book age.** Matching every live order to the
recorder's 10Hz book at the fire instant (`verify/`, 432 orders in the mrec window):

| | n | mean `seen_ask` (bot) | mean FRESH ask (recorder) | mean fill | fresh < seen | \|fresh−fill\| | \|seen−fill\| |
|---|---|---|---|---|---|---|---|
| normal fills | 415 | 0.9646 | 0.9690 | 0.9653 | 6.3% | 0.0042 | **0.0026** |
| **sweeps** | 17 | 0.8582 | **0.7071** | 0.6899 | **100.0%** | **0.0304** | 0.1683 |

On sweeps the recorder's fresh ask predicts the realised fill **5.5× better** than the bot's own
`seen_ask`, and it is staler in **100%** of them; on ordinary fills the bot's view is the better
predictor. The recorder's `evage` on those rows is **0.00-0.09s**, so a dedicated WS feed had the
collapse already. **The bot fires at a stale 0.99, its dollar-capped FAK meets the real book at
0.26, and it buys 4× the shares cheaply.**

### Consequences
1. **There is nothing to predict.** The independent sweep-prediction model confirms this from the
   other side: 13/17 sweeps show the collapsed ask in the fresh book *before* the fire
   (17/17 strictly cheaper) vs **0 of 426** non-sweeps. A model cannot forecast our own latency.
2. **Fixing the staleness would forfeit these trades, not improve them.** With a fresh view, all
   17 sweeps show an ask below 0.98 — so the first-clip skip band (0.90-0.98) would block ~6 — and
   3 of 17 fall below `MIN_ASK=0.55` outright. The gates are calibrated against the *stale* view.
3. **But hunting them deliberately does not pay**: taking dislocations at scale is **−3.81% ROI
   blind** (n=274 tape-confirmed) and **+0.82%** with the live recon gate. The windfalls we booked
   were a lucky subset, not a harvestable class.
4. **§7's "61.7% of profit" must be read with its variance**: the live class is 5 fills — top-1 is
   **55.9%** and top-5 **132.6%** of all sweep profit; the fleet ex-those-5 makes +$40.04 of
   $220.53. Bootstrap 95% CI on the 59 sweeps' ROI: **[−7.3%, +46.2%]**.

## 11. ⛔ §8/§9 SETTLED — do NOT shift the fire window
§9 left the question hinging on whether delaying manufactures sweeps (it needed ~+21c/fire).
**It does not.** Collapse hazard is flat in tl (4.2 / 5.0 / 6.8 / 5.6 / 6.2 / 5.0%), and the paired
within-bar test runs the *wrong* way: collapse during tl 16-20 **21.2%** vs during tl 12-16
**18.2%** (−3.0pp, t=−1.65), and **40.7% vs 28.7%** for tl 3-8 (t=−2.59). Dislocations are if
anything MORE likely early. With the sweep term gone, §9's paired result stands unopposed:
delaying costs **−9.3%** of EV per bar-opportunity. **The fire-window shift is closed.**
