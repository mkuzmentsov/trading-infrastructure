# FRONTIER.md — the conviction/volume frontier, and the "we are right, the market is wrong" cell

**2026-09-16. Read-only. Nothing deployed, nothing proposed for deployment.**
Pre-registration: `PREREG-FRONTIER.md` (written before any cell below existed).
Scripts `f1.py`…`f11.py`; scan output `out/frontier/scan.csv`.
Lanes: RETEST.md (quant), MODELS.md (ml), ALLOC.md (sizing), VENUE.md (mechanics).

---

## 0. Answer first

**The crack is not a crack. The "sign flip at 2.0 bps" is a weighting artefact, and it reverses
the moment you count bars instead of seconds. Underneath it is a real and much more important
bound: conviction and fillability are inversely related by 23×, holding price and clock fixed.**

| the claim | what it actually is |
|---|---|
| "`est ≥ 2.0 bps` flips net per-share to +0.030" | a **per-second** average over ~28 near-duplicate rows per bar. One trade per bar, the same gate reads **−1.44 c/share** (first), −1.76 (last), −1.76 (random), −1.62 (bar-mean). **The flip does not survive the unit of analysis.** §2 |
| "the fleet gate nets −0.279 c/share" | that is a share-denominated displayed-ask taker. **The fleet actually realises +0.4385 c/share** (+0.2746 ex-sweep) on 55,364 real shares. The panel replay understates the live book by ~0.84 c/share. §2.3 |
| "the high-\|est\| tercile fills only 10.5%" | an understatement. On 8,496 live attempts, **fill rate falls 0.829 → 0.020 as \|est\| goes 0.5 → 15+**, and **0.928 → 0.040 holding the ask band AND the clock fixed**. §3 |
| "raising the gate buys per-share and pays in volume" | correct, and the exchange rate is terrible: **+9.1× per-share for −25.5× shares/day.** Every paired daily difference against the live gate is **negative at every threshold tested**. §1 |

**Task 1 verdict.** Along the **conviction** axis, positive-per-share and material-$/day are
**disjoint**, and the bound is: of 190 scanned cells, the best that clears the full pre-registered
bar is worth **$1.04/day of an $8.37/day book**. Along the **clock** axis they are *not* disjoint
(tl ≤ 12 is 4.68 c/share and still $5.27/day) — but that is the known sweep harvest, already live,
and concentration-bound. **The direction lane closes as a conviction gate. It does not close as a
timing statement.** §5

**Task 2 verdict.** The cell is **real information and worth approximately nothing.**
The decisive-and-market-disagrees interaction is **+13.75 pp at z = +5.34** against a blocked-shuffle
null (side-flip placebo −18.95). But (a) **10.26 of the headline 14.04 pp appears under the null**,
because a 97.75 % base rate makes any cheap ask look like a 15-point edge; (b) conditional on the
market disagreeing, **our accuracy falls from 97.75 % to 94.23 %** — the disagreement is informative
*against* us, just not enough to overturn us; and (c) **the fleet already fires there**: on the exact
82 bars, **639 attempts at ask < 0.90 produced 6 fills (0.9 %) and −$14.48.** §4

**The finding of this round is the mechanism, not a strategy.** Our estimator becomes decisive at
the moment the TWAP reconstruction resolves — and that is the same moment the makers pull the
offer. Conviction does not buy a better price here; **it buys an empty book**, and it does so at a
measured 23:1 rate. That is a structural bound on every direction-based idea on this venue, and it
is now measured on a 2-D control grid with n in the thousands rather than inferred.

---

## 1. Task 1 — the frontier, on the live ledger, with no fill model anywhere

`f1.py`, `f5.py`. Unit = **attempt** (net = 0 if unmatched); gate on `|est_bps|`, an ex-ante
pre-send field. 8,496 attempts, 4,390 settled fills, 29 UTC days, 7 coins, +$242.79.
This needs no fill model at all: the gate changes the attempt set and the measured fill rate
falls out of the data.

| θ = \|est\| ≥ | att/day | fill rate | shares/day | **c/share** | **$/day** | t_day | LOO-day $/d | LOO-coin $/d | top-5 in | ex-sweep $ |
|---|---|---|---|---|---|---|---|---|---|---|
| **0.5 (live)** | 293.0 | **0.522** | **1931** | **0.434** | **8.372** | 1.25 | [4.27, 11.33] | [2.54, 11.50] | 5 | +134.90 |
| 0.75 | 250.8 | 0.471 | — | 0.137 | 2.009 | 0.37 | [−0.10, 4.38] | [−2.17, 4.37] | 3 | +111.48 |
| 1.0 | 211.3 | 0.403 | 970 | 0.194 | 1.878 | 0.52 | [0.27, 3.34] | [0.01, 2.87] | 2 | +101.99 |
| 1.5 | 158.7 | 0.288 | 503 | 0.268 | 1.349 | 0.45 | [0.10, 3.07] | [0.08, 2.53] | 2 | +76.51 |
| **2.0** | 130.4 | 0.194 | 262 | 0.560 | **1.467** | 0.62 | [0.72, 3.21] | [0.11, 1.83] | 2 | +4.03 |
| 3.0 | 99.1 | 0.108 | 104 | −0.817 | −0.853 | −0.45 | [−1.23, 0.82] | [−1.38, 0.40] | 0 | −7.19 |
| 5.0 | 69.0 | 0.047 | 37 | 1.885 | 0.699 | 1.38 | [0.46, 1.00] | [0.43, 0.79] | 0 | +28.75 |
| **8.0** | 47.9 | **0.026** | **16** | **3.963** | **0.649** | 2.22 | [0.41, 0.67] | [0.40, 0.65] | 0 | +17.97 |
| 12.0 | 30.2 | 0.018 | 7 | 3.512 | 0.248 | 1.59 | [0.11, 0.26] | [0.12, 0.25] | 0 | +6.88 |

### 1.1 The volume identity — this is the whole answer in one line

`$/day ≡ (c/share)/100 × shares/day`. From θ = 0.5 to θ = 8.0:

> **c/share rises 9.1× (0.434 → 3.963). Shares/day falls 25.5× (1931 → 16.4).
> The product falls 12.9× ($8.372 → $0.649/day).**

### 1.2 The pre-registered kill fires on every cell

Paired **daily** difference against the live gate (G = 29 day-clusters). Kill condition was
"no θ > 0.5 beats θ = 0.5 at t_day ≥ 3.0".

| θ | Δ $/day | t_day | days improved | LOO-day range |
|---|---|---|---|---|
| 0.75 | −6.363 | −1.57 | 10/29 | [−7.36, −3.22] |
| 1.0 | −6.494 | −1.17 | 12/29 | [−8.52, −2.87] |
| 2.0 | **−6.906** | −1.10 | 13/29 | [−9.62, −2.80] |
| 5.0 | −7.673 | −1.15 | 12/29 | [−10.61, −3.55] |
| 8.0 | −7.723 | −1.15 | 11/29 | [−10.66, −3.60] |

**Every threshold loses money against the gate the fleet already runs, in every leave-one-out
window.** Not one is close. The frontier's maximum in $/day is at θ = 0.5, which is where the
fleet already sits — and I cannot test below it, because the fleet has never fired there
(min \|est\| on all 8,496 attempts is exactly 0.500).

---

## 2. Why the per-share table said otherwise — the specification audit

`f4b.py`. I reproduce the ml-engineer's numbers exactly (their −0.279 → my −0.261 on fleet coins;
their −3.093 market baseline → my −12.286 all-coins / same construction), so this is not a
disagreement about data. It is about the **unit**.

### 2.1 ⭐ The per-second average is not a tradeable average

Same rows, same gate, same fee. Only the weighting changes:

| gate | rows | bars | **per-second** | first (hi tl) | last (lo tl) | random | bar-mean |
|---|---|---|---|---|---|---|---|
| est ≥ 0.5 | 6,208 | 818 | −0.576 | −1.865 | −1.314 | −1.522 | −1.693 |
| est ≥ 1.0 | 3,268 | 559 | +0.364 | −0.668 | −0.169 | −0.312 | −0.586 |
| **est ≥ 2.0** | 930 | 219 | **+1.176** | **−1.444** | **−1.759** | **−1.764** | **−1.620** |
| est ≥ 5.0 | 140 | 16 | +8.656 | +4.652 | +4.652 | +4.652 | +4.652 |

**At est ≥ 2.0 the sign flips back under all four one-trade-per-bar pickers.** It is not
sensitive to *which* second you pick; it is sensitive to counting seconds at all.

### 2.2 The mechanism, and it is the concentration guard wearing a new hat

At est ≥ 2.0, split the qualifying bars by how many seconds the takeable ask persists:

| secs takeable | bars | rows | **bar share** | **row share** | mean ask | acc | c/share |
|---|---|---|---|---|---|---|---|
| 1 | 52 | 57 | **25.6 %** | 6.1 % | 0.9651 | 0.912 | **−5.47** |
| 2 | 36 | 74 | 17.7 % | 8.0 % | 0.9692 | 0.973 | +0.19 |
| 3–4 | 50 | 200 | 24.6 % | 21.5 % | 0.9794 | 0.980 | −0.07 |
| 5–8 | 44 | 296 | 21.7 % | 31.8 % | 0.9725 | 0.936 | −3.83 |
| 9–16 | 16 | 167 | 7.9 % | 18.0 % | 0.9700 | 1.000 | +2.81 |
| **17+** | **5** | 136 | **2.5 %** | **14.6 %** | **0.8396** | **1.000** | **+15.22** |

**Five bars — 2.5 % of the population — supply 14.6 % of the row weight at +15.22 c/share and
carry the average across zero.** The 25.6 % of bars where the ask exists for exactly one second
get 6.1 % of the weight and read −5.47. This is the top-5-fills pathology reappearing through the
sampling weight instead of through the dollar weight, and the pre-registered concentration guard
would have vetoed it on sight had it been expressed in dollars.

### 2.3 The panel understates the live book by ~0.84 c/share

Adding the fleet's gates to the panel one at a time (per-second, fleet coins):

| gate | rows | bars | acc | c/share |
|---|---|---|---|---|
| est ≥ 0.5 (the ml baseline) | 5,737 | 760 | 0.9634 | −0.261 |
| + cov ≥ 0.5 | 5,570 | 741 | 0.9632 | −0.272 |
| + skip 0.90–0.98 (live since 08-31) | 4,695 | 721 | 0.9655 | −0.236 |
| + tl ≤ 20 (the §37 lane) | 1,077 | 267 | 0.9777 | +0.514 |
| **the same, one trade per bar** | — | 267 | 0.9625 | **−0.405** |
| **LIVE LEDGER, realised** | — | — | — | **+0.4385** (ex-sweep +0.2746) |

The residual is bug #46: the live order is **dollar-denominated** and fills below the displayed
ask 294 times for +$107.89. **No displayed-ask share-denominated replay can see the fleet's actual
economics**, in either direction — and this one reads the sign backwards.

---

## 3. ⭐ The mechanism: conviction buys an empty book, at 23:1

`f10.py`. **Fill rate by conviction, holding the ask band AND the clock fixed.** Read across
any row: the price is the same, the second is the same, only our certainty changes. (n in
parentheses.)

| ask band | tl | \|est\| 0.5–1 | 1–2 | 2–5 | 5–10 | 10+ |
|---|---|---|---|---|---|---|
| **.90–.98** | 16–20 | **0.928** (559) | 0.857 (617) | 0.514 (284) | 0.110 (109) | **0.040** (174) |
| .90–.98 | ≤12 | 0.621 (190) | 0.355 (76) | 0.012 (250) | 0.011 (187) | 0.006 (334) |
| **.75–.90** | 16–20 | **0.693** (137) | 0.529 (104) | 0.195 (82) | 0.030 (67) | **0.000** (78) |
| .75–.90 | ≤12 | 0.800 (5) | **0.000** (54) | **0.000** (109) | **0.000** (138) | **0.000** (154) |
| ≥.98 | 16–20 | 0.906 (435) | 0.820 (561) | 0.744 (262) | 0.465 (43) | 0.200 (35) |
| <.75 | 16–20 | 0.516 (64) | 0.535 (43) | 0.160 (25) | 0.062 (16) | 0.043 (23) |

* **A 23× collapse at constant price and constant clock** (0.928 → 0.040; 0.693 → 0.000).
* In the cheap band late (`.75–.90`, tl ≤ 12) the fleet made **455 attempts at \|est\| ≥ 1 and got
  zero fills.** Not a low rate — zero.
* It is **not** a tl confound and **not** a price confound: both are held fixed inside every row.

**Corroboration from the independent instrument.** On the panel (`f3.py`, 3 days, 4,320 bars,
per-second book state), asking how often a takeable ask exists on our side at all:

| \|est\| | tl 3–14 | tl 15–29 |
|---|---|---|
| 0.0–0.5 | 0.4724 | 0.8623 |
| 0.5–1 | 0.0721 | 0.6491 |
| 1–2 | 0.0139 | 0.2813 |
| 2–5 | 0.0004 | 0.0323 |
| 5–8 | 0.0000 | 0.0004 |
| **8+** | **0.0000** | **0.0000** |

**At \|est\| ≥ 8 bps there is not one takeable second in 21,938 observations.** Per bar: at θ = 5
a takeable ask ever appears on **7 of 2,368 bars (0.3 %)**; at θ = 8, **0 of 1,681.**

**Interpretation.** Our estimator becomes decisive when the 60-second TWAP reconstruction resolves.
Any maker watching the same Chainlink ticks resolves at the same instant and pulls the offer. Our
conviction and their withdrawal are **the same event**, which is why no amount of estimator quality
converts into fills. This is the taker-side adverse-selection finding in the archive, now measured
along the conviction axis with the price and the clock controlled.

---

## 4. Task 2 — "we are right and the market is wrong", on 30 days

`f6.py`, `f7.py`, `f9.py`. Instrument I2 (`evx`, 53,311 bars, 30 days, tl ≈ 27.8).
`ask` is oracle-conditioned (recorded on the estimator's own side) — correct for this question.
Base rate: our side is right on **97.75 %** of all 53,311 bars. Metric: `P(win) − ask − fee(ask)`.

### 4.1 The 2×2, with both controls pulled *before* the write-up (pre-registered)

| cell | n | /day | ask | P(win) | **edge pp** | t_day |
|---|---|---|---|---|---|---|
| **DECISIVE (est ≥ 5) & CHEAP (ask .55–.90)** | 104 | 3.5 | 0.791 | **0.9423** | **+14.04** | **6.85** |
| control — WEAK (est < 2) & CHEAP | 2,071 | 69.0 | 0.763 | 0.7335 | −4.20 | −3.73 |
| control — DECISIVE & EXPENSIVE (.98–.99) | 269 | 9.0 | 0.984 | 0.9963 | +1.10 | 3.69 |
| control — WEAK & EXPENSIVE | 2,146 | 71.5 | 0.986 | 0.9772 | −0.96 | −2.02 |

The signs are right, the interaction is in the correct corner, and it is robust: LOO-day
[+17.20, +19.85] with **0 sign flips over 20 days**, LOO-coin [+12.61, +16.63] with **0 flips**,
**all 7 coins positive**, both eras positive (A +7.63/+2.73, B +21.91/+12.08), 6 losses in 104.

### 4.2 Two corrections that take most of it back

**(a) The level is mostly the base rate.** Blocked-shuffle null (`won` permuted within coin-day,
500 draws, bug #35):

| statistic | observed | null mean | null sd | **z** | p |
|---|---|---|---|---|---|
| DiD **interaction** | **+13.75 pp** | −2.29 | 3.00 | **+5.34** | 0.0000 |
| dec&cheap **level** | +14.04 pp | **+10.26** | 2.59 | **+1.46** | **0.096** |

Side-flip placebo: interaction −18.95, level −74.42.
**The interaction is real; the headline level is 73 % null.** Any row priced at 0.79 looks like a
+18 pp edge when the population wins 97.75 % of the time. Quoting +14.04 pp as "our edge" would
have been the error.

**(b) The disagreement is informative against us.** On bars the market prices cheap, our accuracy
is **0.9423 vs our 0.9775 base rate.** We are still usually right — and measurably *less* right
than usual. The market's cheap ask is a correct warning, merely an over-priced one.

### 4.3 And the fleet already fires there, 639 times, for −$14.48

Joining the 104 decisive-and-cheap bars to the live ledger on `(coin, ws)`:

| | |
|---|---|
| evx decisive & cheap bars | 104 |
| of these, bars the fleet also traded | **82** |
| live attempts on those bars | **657** (639 at ask < 0.90) |
| fills | **24** total, **6** at ask < 0.90 (**0.9 %**) |
| **live net on those bars** | **−$14.48 = −$0.499/day** |

Measured directly on the ledger by its own fields (all tl, 29 days):

| cell | att | att/day | fills | **fill rate** | $/day | c/share |
|---|---|---|---|---|---|---|
| est ≥ 5 & ask .55–.90 | 658 | 22.7 | 11 | **0.0167** | +0.151 | 3.29 |
| est ≥ 10 & ask .55–.90 | 326 | 11.2 | **1** | **0.0031** | +0.125 | 40.29 |
| est ≥ 5 & ask .90–.98 | 335 | 11.6 | 25 | 0.0746 | +0.382 | 5.08 |
| **est < 2 & ask .55–.90** | 605 | 20.9 | **291** | **0.4810** | **+3.516** | 1.83 |

**Ceiling arithmetic.** 104 bars × 3.5/day × 14.04 pp × ($8 / 0.791 = 10.1 shares) = **$5.26/day
if the displayed ask always filled.** At the measured 1.7 % it is **$0.079/day**; the ledger's own
answer for the same cell is **$0.151/day**. This is the A1 census's "+37.65 % ROI on 11 bars"
at 30 days: the ROI is real, the volume is three bars a day, and the book honours one in sixty.

### 4.4 ⭐ The inversion — the fleet's cheap-band money is its *least* confident signal

The cheap band (.55–.90) split by our own conviction, live ledger:

| cell | att | fills | **fill rate** | $/day | c/share | t_day | top-5 | **era A → B** |
|---|---|---|---|---|---|---|---|---|
| est 0.5–1 & cheap | 315 | 180 | **0.571** | **+5.147** | 3.63 | 1.54 | **2** | +7.05 → **−0.27** |
| est 1–2 & cheap | 290 | 111 | 0.383 | −1.631 | −3.26 | −0.77 | 0 | — |
| est 2–5 & cheap | 310 | 34 | 0.110 | +1.750 | 10.59 | 1.36 | 1 | — |
| est 5–10 & cheap | 332 | 10 | 0.030 | +0.026 | 0.60 | 0.07 | 0 | — |
| est 10+ & cheap | 326 | **1** | **0.003** | +0.125 | 40.29 | 1.00 | 0 | — |

And where that money actually comes from — 291 fills at est < 2 in the cheap band:

> seen_ask **0.8013**, paid **0.7724** (improvement **2.89 c**), win rate **0.8076**.
> **Had we paid the displayed ask: −0.49 c/share. We realised +1.83 c/share.**

The market's displayed cheap price is **fair** (80.8 % wins vs 80.1 % implied, −0.49 after fee).
**The entire cheap-band edge is buying below the displayed ask** — execution, not prediction — and
it is *inversely* related to conviction, because a cheap offer that is still standing is one the
maker was willing to lose. It is also **era-fragile**: +$7.05/day in the first 15 days,
**−$0.27/day in the last 14**, and −$0.37/day over the freshest 11.

---

## 5. The bound (Task 1's real question, stated as a bound)

`f11.py`. Systematic scan of **190 cells**: 8 `|est|` thresholds × 7 ask bands × 7 tl bands,
keeping cells with ≥ 100 attempts and ≥ 200 shares. Full pre-registered bar = c/share > 0
**and** t_day ≥ 3.0 **and** ex-top-5 > 0 **and** both eras > 0 **and** LOO-day > 0 **and**
LOO-coin > 0.

| constraint on per-share | **max $/day achievable** | that cell |
|---|---|---|
| none | 8.372 (100 %) | the live book |
| c/share ≥ 1.0 | 7.302 (87 %) | all attempts, **tl 0–16** — t 1.74, **3 top-5 fills** |
| c/share ≥ 2.0 | 5.417 (65 %) | ask .55–.90, all tl — t 1.15, 3 top-5 |
| c/share ≥ 3.0 | 5.270 (63 %) | all attempts, **tl 0–12** — t 1.64, 2 top-5 |
| **passing the FULL bar** | **1.041 (12.4 %)** | **ask .90–.98 & tl < 12** |

**So the honest answer is two answers, and they differ by axis:**

* **Conviction axis — disjoint, hard bound.** Every `|est|` threshold above the live gate loses
  money (§1.2), and the mechanism forbids it: the book is 23× thinner where we are sure (§3).
  **No conviction gate can be both per-share positive and material. This closes the direction
  lane as a gate.**
* **Clock axis — not disjoint.** `tl ≤ 12` is 4.68 c/share *and* $5.27/day. But t = 1.64, it holds
  2 of the top-5 fills, and RETEST already showed it collapses +152.82 → +38.94 ex-sweep. It is the
  dislocation harvest, it is already live, and it is a concentration bet. **Not a new lane —
  a restatement of the one we are in.**

### 5.1 The one cell that clears every pre-registered bar

**`seen_ask ∈ [0.90, 0.98) & tl < 12`**, any conviction — 325 attempts, 58 fills (17.8 %):

| | |
|---|---|
| net | **+$30.18 = +$1.041/day**, 4.52 c/share |
| t_day | **4.29** (largest in this program; expected max-under-null for 190 cells = 3.24) |
| days | **17 active, 17 positive, 0 negative** (P = 7.6 × 10⁻⁶ under day-sign flips) |
| day bootstrap | 95 % CI **[+0.61, +1.56] $/day**, P(>0) = 1.000 |
| concentration | **0 top-5 fills**; largest single day = largest single fill = **17.8 %** |
| per coin | **all 7 positive** (hype +0.44, eth +0.23, doge +0.10, xrp +0.09, sol +0.09, bnb +0.07, btc +0.01) |
| era | A +$1.20/day → B +$0.87/day |

Its complement is the mid-band bleed, and the split is by the clock alone:

| 0.90–0.98 at | att | fill rate | $/day | t_day | days + |
|---|---|---|---|---|---|
| **tl < 12** | 325 | 0.178 | **+1.041** | **+4.29** | **17/17** |
| tl 12–16 | 319 | 0.448 | −1.419 | −1.04 | 11/16 |
| tl 16–20 | 688 | 0.644 | −2.907 | −1.09 | 17/23 |
| tl ≥ 20 | 539 | 0.612 | −2.112 | −1.39 | 13/18 |

**Reading.** The deployed `PM_TE_FIRST_SKIP 0.90–0.98` veto treats the band as uniform; the band
is not uniform, and its one profitable window is the late one. (It is mostly ladder clips 2–3,
which the first-clip skip never touched: clip 2 carries +$20.92 of the +$30.18.) This is the only
object in two rounds of this program that survives every pre-registered filter simultaneously.

**And it is still not a strategy.** It is worth **$1.04/day — 12.4 % of an $8.37/day book** — it is
a *description of flow the fleet already has*, and turning it into a gate would mean discarding
the other 87.6 %. I am flagging it as the one cell that deserves a longer ledger, not as a
change. Confidence that it is non-zero: high (17/17, bootstrap P(>0) = 1.000, no concentration).
Confidence that it is worth acting on: low, because acting on it means either doing less of
everything else or up-sizing into a 17.8 % fill rate, which is the unresolvable depth wager
MODELS §3.7 already filed as CONDITIONAL.

---

## 6. Multiple comparisons, and the forward picture

**Budget.** F1 9 + F2 40 + F5 grid 17 + controls 4 + F11 scan 190 ≈ **260 scored cells.**
Expected max |t| under the null ≈ √(2 ln 260) = **3.34**.

| claim | raw t / z | vs 3.34 |
|---|---|---|
| ask .90–.98 & tl < 12 (§5.1) | **4.29** | clears |
| Task 2 DiD interaction (§4.2) | **z = 5.34**, empirical null, 0/500 draws | clears |
| Task 2 level (+14.04 pp) | z = **1.46** | **fails** — 73 % null |
| every conviction threshold (§1.2) | ≤ 1.57, all negative | n/a |
| `|est| ≥ 8` all bands | 2.22 | fails |

**Forward (freshest 11 days, $20.45/day).** The book has moved, and it has moved *away* from
everything in this document:

| lane | att/day | $/day | share |
|---|---|---|---|
| **\|est\| < 2 & ask ≥ 0.98** | 88.1 | **+16.354** | **80 %** |
| \|est\| ≥ 2, all bands | 13.2 | +1.734 | 8 % |
| \|est\| ≥ 5, all bands | 2.7 | +0.187 | 1 % |
| \|est\| < 2 & ask .55–.90 | 10.4 | **−0.369** | — |

**93 % of the fleet's 29-day net comes from `|est| < 2`** — the low-conviction half of its own
signal — and forward it is 80 % from one cell: low conviction, near-certain price, high fill rate.
**The fleet is not paid for being sure. It is paid for showing up where the book will trade.**

---

## 7. What I am handing back

1. **The "0.5 → 2.0 flips the sign" crack is closed.** It is a per-second weighting artefact
   carried by 5 bars out of 219; one trade per bar reverses it. The fleet's realised per-share is
   already **+0.4385 c**, not −0.279 — the panel replay cannot see the dollar-denominated book.
2. **Conviction gating is closed as a direction, permanently, with a mechanism.** 23:1 fill
   collapse at constant price and constant clock; zero takeable seconds at \|est\| ≥ 8 in 21,938
   panel observations; every threshold negative in paired daily differences. This is a **bound**,
   not another refutation, and it should be treated as closing the lane.
3. **Task 2's cell is real information worth ~$0.15/day.** The interaction survives its null
   (z = 5.34); the level does not (z = 1.46); our accuracy *drops* to 94.2 % when the market
   disagrees; and the fleet already fires 639 times into it for 6 fills and −$14.48.
4. **One survivor: `ask .90–.98 & tl < 12`, +$1.04/day, t 4.29, 17/17 days, no concentration,
   all 7 coins, both eras.** It contradicts the uniform mid-band skip. It is 12 % of the book and
   I am not proposing anything be changed for it.
5. **The uncertainty.** Items 1–2 are arithmetic and mechanism — I would defend them at >95 %.
   Item 3's interaction I would defend; its dollar value is ±$0.1/day. Item 4 is the only cell I
   would want more data on, and "more data" means roughly **3× the ledger**, i.e. months.

**No deployment is proposed anywhere in this document, and none should be inferred from §5.1.**
