# Can a STATISTICAL / ML predictor beat the btc 5m mid by enough to fund a maker fill? — 2026-09-07

**User's ask:** *"Find a maker edge — AI prediction, math/statistics prediction + maker buy.
More than 50% wins gives us at least rebates. maker bet in range 40-60. ladder entry???"*
**Scope:** btc 5m only, **mid-bar** (tl 70–290 s, i.e. before the settlement window opens).
**Data:** the fresh btc build, 09-01 20:00 → 09-06 20:50 UTC, **1,447 resolved bars**,
1,883,569 prints. Working dir `scratchpad/pred/` (`build.py`, `feats.py`, `a1`–`a17`).

## ⛔ VERDICT — NO. Four independent walls, in the order they were hit.

1. **The user's premise is wrong and the correct bar is +3.1 pp.** ">50 % wins gives us rebates"
   is false: break-even is the *entry price*, and conditional on being **filled** a maker is
   already ~1.5 c/share behind. **Independently re-derived here** (below): a maker needs
   **E[y − mid] ≈ +3.03 pp over all quotes**, i.e. **~54.8 % side accuracy**, merely to break even
   after the rebate.
2. **The structural "average vs endpoint" mispricing is real but ~1 pp, not 3.** Measured, not
   assumed.
3. **The 100 %-looking predictive signal was a fossil-book artefact** (new ledger **bug #34**).
   On live books every structural feature is dead.
4. **The one config that survived OOS died at the fill.** +6.73 pp over all quotes → **+0.69 ±
   2.95 pp over FILLED quotes** with the queue modelled; and its honest SE is 6.6 pp, not 2.6
   (new ledger **bug #35**).

---

## 0. Method / pre-registration

- One snapshot per bar at each of **13 fixed `tl`** (290,270,…,95,80,70) — never window-averaged
  (averaging lets the price drift toward the outcome and fabricates ~+6 pp).
- Every feature causal at the decision instant; Chainlink read from the SNAP row's own `cl/cl_ts`
  (bug #25), Binance `spot` at ≤ the decision second, flow from receive-time `t`.
- **Time-ordered** split only (train = first 65 % of bars, test = last 35 %) plus an expanding-
  window walk-forward refit daily. Primary metric **E[outcome − price] on the model's selected
  subset, OOS, in pp, bar-clustered**. AUC reported as a diagnostic only.
- **The benchmark is the market mid, not 50 %.** The mid's own AUC on this panel is **0.8493** —
  no model built here beat it (best OOS AUC 0.845).

### Power, stated up front
| bars | SE of E[y − mid] | a true +3.1 pp edge reads | 80 %-power MDE |
|---|---|---|---|
| 1,447 | 1.31 pp | t = 2.36 | 3.68 pp |
| 507 (test) | 2.22 pp | t = 1.40 | 6.22 pp |
| 300 | 2.89 pp | t = 1.07 | 8.08 pp |
| 150 | 4.08 pp | t = 0.76 | 11.43 pp |

**This dataset cannot certify a +3.1 pp edge on any narrow subset.** It can only reject large ones.

---

## 1. ⭐ THE STRUCTURAL TEST (done first, before any fitting) — effect is REAL but ~1 pp

Settlement is `TWAP(cl,[end−62,end−3]) >= strike`, an **average**, not an endpoint. Under Brownian
motion `Var[avg] = σ²(τ − 62 + 59/3) = σ²(τ − 42.33)` — the digital behaves like one expiring
**42.3 s early** (the brief's "~32 s" is the window midpoint; 42.33 s is the right number once the
averaging variance reduction is included).

**Model-free measurement of the variance reduction** (dispersion of the settled TWAP vs the
endpoint Chainlink, both from the same `clhat`, all 1,447 bars):

| τ | 70 | 110 | 150 | 190 | 230 | 270 | 290 |
|---|---|---|---|---|---|---|---|
| Var(TWAP)/Var(endpoint) **measured** | 0.916 | 0.939 | 0.927 | 0.933 | 0.889 | 0.891 | 0.879 |
| BM theory `(τ−42.33)/τ` | 0.395 | 0.615 | 0.718 | 0.777 | 0.816 | 0.843 | 0.854 |
| implied early-expiry, s | 5.9 | 6.7 | 11.0 | 12.7 | 25.6 | 29.4 | 35.2 |

⭐ **The averaging effect is real but far weaker than BM theory** — a roughly *constant* ~10 % of
variance at every τ, not a fixed 42 s offset. Chainlink is a stepped, deviation-triggered series
with strong short-horizon autocorrelation, so averaging it removes much less variance than
averaging a Brownian path would. **Anyone pricing this off `(τ−42.33)` overstates the edge ~4×.**

**The decisive test needs no vol estimate at all.** If the market priced an *endpoint* digital,
the true probability would be `Φ(Φ⁻¹(mid)·k)` with `k` the variance-ratio correction, and the
favourite-side edge would be a known, signed number. Predicted vs measured:

| | predicted | measured (bar-clustered) | meas − pred |
|---|---|---|---|
| under BM theory (h = 42.33 s) | **+2.434 pp** | **+1.241 ± 0.727 pp** (t = +1.71) | −1.194 (t = −1.64) |
| under the empirical variance ratio | **+0.617 pp** | same | +0.623 (t = +0.86) |

And where the hypothesis predicts the most (deep favourites late in the bar) it is **refuted**,
not merely unsupported: at tl 60–110 and fav ≥ 0.90 it predicts +3.21 pp and measures
**+0.10 ± 0.67 pp** (t vs prediction = **−4.64**); at fav 0.75–0.90 predicted +7.32 vs measured
+2.56 (t = −3.08).

**Conclusion: the market does NOT price this as an endpoint digital.** The residual favourite-side
edge on live books is **+1.05 ± 0.69 pp (t = 1.52)** pooled — the same +0.8…+1.8 pp the calibration
table already showed, one third of the bar, and not significant. **Closed.**

---

## 2. ⛔ THE FEATURE SCREEN — every structural feature is fully priced (once the book is live)

See **bug #34** for the trap. On the LIVE panel (`evage ≤ 1 s` **and** non-zero trailing tape;
14,811 rows / 1,346 bars), the univariate screen of (y − mid) on 35 causal features, train only:

| survives | β pp / SD | t | | dead | t |
|---|---|---|---|---|---|
| `imb0` top-of-book imbalance | +1.62 | **3.81** | | `d_hat` (spot vs strike) | −0.18 |
| `spr` | +1.30 | 3.56 | | `z_hat` (vol-scaled) | +1.02 |
| `imb` top-3 imbalance | +1.32 | 3.02 | | `lead_bps` (Binance lead) | −0.33 |
| `ret20/30/60` spot momentum | +0.65…0.71 | 2.4–2.8 | | `d_tw`, `ret5/10/120/300`, all vols, hour, τ, depth | \|t\| < 1.1 |
| `flow120` signed taker flow | **−1.70** | −1.93 | | | |

Bonferroni over 35 tests needs \|t\| > 3.19; the max observed is 3.81.
- **`d_hat`/`z_hat`/`lead_bps` are dead at every single `tl`** — the market fully prices the
  Chainlink-vs-strike displacement mid-bar. The one proven signal in this program (the TWAP-60
  recon) has coverage 0 before tl 62, and nothing replaces it.
- **`spr` is an artefact**: btc's spread is 1 c on 14,633 of 14,811 rows; the whole coefficient
  comes from the **108 rows** at 2 c.
- **`flow120` is ANTI-predictive** — signed taker flow points *away* from the outcome relative to
  the mid. This independently replicates the rebate-farm §9 finding ("cancelling on visible flow
  discards the GOOD fills").
- **`imb0` is the openmm signal** and it is the only real thing here: +1.6 pp per SD, monotone-ish
  but only the extreme deciles move (most-negative −3.66 ± 1.39, most-positive +1.93 ± 1.35).
  1.6 pp/SD needs a ~2 SD selection to reach the bar.

---

## 3. ⛔ THE LEARNED MODELS — textbook overfitting, **39 configurations scored**

Logistic (market logit as an **offset**, and free), gradient boosting (classifier with `logit_mid`
as a feature, and regressor on the residual `y − mid`), ridge on the residual, random forest;
selection thresholds 0.02 / 0.05 / 0.10. Train vs test, E[outcome − price] pp:

| model | train edge | **OOS edge** | train AUC | OOS AUC |
|---|---|---|---|---|
| GBM-clf (lr .05, d3) | +17.9 … +36.4 | **−1.7 … −3.4** | 0.898 | 0.800 |
| GBM-res (lr .05, d3) | +17.7 … +33.8 | **−0.9 … −3.4** | 0.899 | 0.806 |
| RF on residual | +24.7 … +45.4 | **−1.0 … −2.7** | 0.905 | 0.822 |
| LR free, full | +1.3 … +3.6 | **−0.3 … −1.8** | 0.846 | 0.821 |
| Ridge on residual | +4.1 … +19.9 | −0.2 … **+2.1** | 0.856 | 0.843 |
| LR-offset, full | +4.7 … +17.0 | −0.5 … **+1.6** | 0.856 | 0.841 |
| **LR-offset, 4 features** | +3.5 … +14.3 | +1.2 / **+8.58 (t=2.11)** / +8.87 | 0.854 | **0.845** |

**Market mid AUC = 0.8493. Not one model beat it.** Train edges of +18…+45 pp collapsing to
≈ 0 OOS is the signature of 1,447 bars and too many parameters — exactly the pre-registered
default hypothesis.

### The single survivor, pushed as far as it goes
`LR-offset-small` = logistic with **offset `logit(mid)`** and four features
`[imb0, ret20, flow120, z_hat]` (4 parameters). Fitted coefficients (full sample, for the record):
`imb0 +0.060 (z 2.91)`, `ret20 +0.038 (1.72)`, `flow120 −0.109 (z −5.00)`, `z_hat +0.050 (1.69)`.
Expanding-window walk-forward, refit each day, 11,895 OOS rows / 1,068 bars:

| threshold | 0.00 | 0.01 | 0.02 | 0.03 | **0.05** | 0.08 | 0.10 |
|---|---|---|---|---|---|---|---|
| n rows | 11,895 | 7,604 | 4,956 | 3,095 | **982** | 204 | 89 |
| bars | 1,068 | 1,063 | 1,023 | 903 | **438** | 100 | 44 |
| E[y − price] pp | +0.79 | +1.29 | +2.26 | +3.28 | **+6.73** | +5.49 | +3.65 |
| t (clustered) | 1.18 | 1.38 | 1.87 | 2.22 | **2.58** | 0.95 | 0.39 |

4/4 days positive. **But it is not significant and it is not monotone** — a real signal keeps
rising with the threshold; this one peaks at 0.05 and falls away.

**Correcting for the search.** ~46 model configurations were scored (39 in the grid + 7
walk-forward thresholds); the wider screen adds 35 univariate tests. Bonferroni over 46 needs
\|t\| > 3.48. And per **bug #35** the clustered SE is the wrong SE: the feature-shuffle null (the
outcome-shuffle null is vacuous here, bug #30 — it returns +27.8 pp) gives mean −3.32, **sd 6.58 pp**,
so the real +6.73 sits at **z = +1.53, p = 0.040 uncorrected ⇒ p ≈ 1.0 corrected**.

---

## 4. ⛔ ITEM 5 — IT DOES NOT SURVIVE THE FILL (this is the wall, and it is the expected one)

Quote = the best bid on the model-favoured side, post-only, 50-share clip, tape-confirmed fills
(union of same-token SELL prints at ≤ our limit and opposite-token BUY prints at ≥ 1 − limit),
**tape-SIZE-capped** (bug #28), with and without the FIFO queue ahead of us modelled (bug #11 —
btc touch depth is 135–185 sh).

| config | quotes | fill rate | E[y−mid] **ALL quotes** | E[y−mid] **FILLED** | net c/share incl. rebate |
|---|---|---|---|---|---|
| thr 0.03, 60 s, tape-only | 3,095 | 93.8 % | +3.28 | +2.17 ± 1.52 | +1.79 |
| **thr 0.03, 60 s, queue modelled** | 3,095 | 74.8 % | +3.28 | **−2.62 ± 1.65** | **−2.10** |
| thr 0.05, 60 s, tape-only | 982 | 93.5 % | +6.73 | +5.69 ± 2.71 | +5.10 |
| **thr 0.05, 60 s, queue modelled** | 982 | 74.5 % | +6.73 | **+0.69 ± 2.95 (t=0.24)** | **+1.23** |
| plain maker, both sides, touch, queue | 23,234 | 81.5 % | −0.01 | **−3.74 ± 0.14** | −3.26 |

⭐ **Adverse selection is WORSE for a directional quoter, not better.** The plain two-sided maker
loses **−3.73 pp** between quoting and filling; the model-selected quoter loses **−6.04 pp**
(6.73 → 0.69). Choosing a side does not dodge the wall — it walks further into it, because the
fills arrive exactly when the market disagrees with you.
(The tape-only column reproduces the program's published −0.43 c/share touch number; the queue
column is the honest one and it is 3 c/share worse.)

### The bound that closes it: what a PERFECT predictor is worth, and what accuracy is needed
Positive control (bug #31 discipline) — the harness has power: a clairvoyant maker earns
**+36.0 c/share** net (and a clairvoyant *taker* +30.4 c/share, so making beats taking *if* you
are right). Then, side = true winner with probability π, else the loser:

| π | 0.50 | 0.52 | **0.55** | 0.58 | 0.62 | 0.70 | 1.00 |
|---|---|---|---|---|---|---|---|
| E[y − mid] over ALL quotes, pp | −0.08 | +1.24 | **+3.14** | +5.23 | +7.66 | +12.96 | +32.08 |
| fill rate | 82.1 % | 81.6 % | 80.9 % | 80.3 % | 79.4 % | 77.4 % | 70.1 % |
| **net c/share incl. rebate** | **−3.20** | **−1.85** | **+0.11** | +2.31 | +4.92 | +10.77 | +35.11 |

⭐ **Break-even = E[y − mid] of +3.03 pp over all quotes = ~54.8 % side accuracy.** This is an
independent re-derivation of the +3.1 pp bar from a completely different construction, and it is
the number to quote to the user. **The best honest predictor built here delivers +0.79 pp
unconditionally and +6.73 ± 6.6 pp on 40 % of bars after a 46-config search.**

---

## 5. ITEM 6 — LADDER ENTRY: ⛔ no. Each extra tick buys 1 c of price and costs ~2 c of selection.

Same harness, 60 s, 50 sh, queue ahead modelled at the actual ladder depth of the level quoted.

**No model (both sides, the clean measurement):**

| ticks behind touch | fill rate | mean fill px | win rate | E[y−mid] FILLED | net c/share incl. rebate |
|---|---|---|---|---|---|
| 0 (join the touch) | 81.5 % | 0.466 | 43.3 % | −3.74 ± 0.14 | **−3.26** |
| 1 behind | 73.2 % | 0.447 | 40.4 % | −5.82 ± 0.19 | **−4.29** |
| 2 behind | 67.7 % | 0.438 | 38.9 % | −7.38 ± 0.23 | **−4.84** |

**Monotone.** The 1 c of price improvement is real (0.466 → 0.447 → 0.438) and is *more than*
consumed by the selection (win rate 43.3 → 40.4 → 38.9 %). With the model on top (thr 0.05) the
same ordering holds: +1.23 / +1.00 / +0.91 net c/share, all inside noise.

**So a ladder does not change the economics — it just buys more of the worst fills.** The only
configuration in which depth helps is the clairvoyant one (+36.0 → +38.2 → +39.6 c/share), i.e.
*laddering is a way to get more size when you are right and is strictly harmful when you are not*.
That is the same conclusion the resting-order wall reached: **only the acquisition price matters,
and you do not control it.**

---

## 6. ⭐ The one thing that LOOKED enormous, and why it is not (see bug #34)

`evage > 3 s` books with |z_hat| > 2 — **16.3 % of bars** — show a **+32.91 ± 1.86 c/share** taker
edge on the displayed ask (median 160 sh showing, t = +17.7). It is not takeable: tape-gated at
5/15/30/60/120 s only **2.7 / 7.2 / 10.3 / 11.5 / 12.4 %** of those quotes ever see a print at the
limit, and the fills that exist are **−5.6 / −2.6 / −5.3 / −7.6 / −9.0 c/share** (**−$83 … −$398**
total over the whole 6 days). The 11.5 % at 60 s is the fleet's own live 11 % takeability.
**It cannot be MADE at all** — those bars have zero flow by construction.

---

## 8. The user's exact ask: **mid 0.40–0.60**, live books — nothing works there at all

3,047 rows / **965 bars**. Favourite-side E[y − mid] = **+1.385 ± 1.142 pp (t = 1.21)**;
UP-side bias +0.103 ± 1.919 pp (t = 0.05). Split into quartiles by the three best features, no
cell is significant and none is monotone:

| quartile | 1 | 2 | 3 | 4 | max \|t\| |
|---|---|---|---|---|---|
| by `z_hat` (spot vs strike / vol) | +1.00 | −1.75 | +4.07 | −2.91 | 1.50 |
| by `imb0` (book imbalance) | −2.11 | +1.75 | −0.66 | +1.43 | 0.84 |
| by `ret20` (spot momentum) | −0.94 | +0.03 | +4.19 | −1.10 | 1.33 |

The 40–60 c band is the **hardest** place to find this, not the easiest: it is where the book is
deepest, the spread is 1 c, the market is best calibrated, and the fill selection is most
symmetric. Every pp of edge found anywhere in this study lives *outside* it.

---

## 7. What to tell the user

- ">50 % wins = rebates" is false. You need **~54.8 % side accuracy** (≈ +3.0 pp over the mid on
  every quote) before a single cent of rebate is worth anything; below that the rebate
  (0.254 c/share) is ~8 % of the hole.
- The 40–60 c band is the **worst** place to try: it is where the market is most liquid, most
  calibrated, and where the fill selection is most symmetric. Mid-bar favourite-side edge there is
  +0.9…+1.6 pp with t < 1.3.
- Ladder entry: **no**. Deeper = worse, monotonically.
- The mathematics *does* say the digital is on an average and therefore tighter than an endpoint
  digital — but the effect is ~10 % of variance (not the 15–60 % BM theory suggests) and the market
  already prices it. Worth **≤ 1 pp**, needs 3.
- **The only unclosed direction is not prediction, it is FILL SELECTION** — `imb0` (top-of-book
  imbalance) is the one feature that survives a Bonferroni screen and it is already the openmm
  §11 result. It gates *which fills you accept*, not *which way the market goes*.

---

## LEAD CROSS-CHECK (2026-09-07): the calibration result survives bug #34
The predictor hunt's headline trap was fossil books (`evage` p90 6.6s, p99 37s, max 229s), which
manufactured a **±27pp** apparent edge inside the 0.40-0.60 band. The lead's independent
calibration test — one snapshot per bar at a FIXED tl, which was the basis for the "+3.1pp bar" —
was re-run with a freshness filter:

| tl | filter | bars | mean mid | realized | bias | t |
|---|---|---|---|---|---|---|
| 240 | all | 1,428 | 0.502 | 0.495 | −0.71pp | −0.60 |
| 240 | **evage<1s** | 1,330 | 0.503 | 0.491 | **−1.17pp** | −0.95 |
| 240 | evage>5s | 68 | 0.494 | 0.588 | **+9.45pp** | 1.58 |
| 160 | evage<1s | 1,279 | 0.497 | 0.495 | −0.20pp | −0.18 |
| 120 | evage<1s | 1,241 | 0.495 | 0.494 | −0.09pp | −0.09 |
| 60 | evage<1s | 841 | 0.478 | 0.484 | +0.56pp | +0.52 |

Favourite-side edge on fresh books: **+0.80 / −0.27 / +0.67 / +0.70 pp at tl 240/160/120/60, all
|t| < 0.7.** Stale books are **8.7%** of rows and do carry the fossil signature, so bug #34 is
real — but it did not drive the calibration finding. **The btc 5m mid is an unbiased probability
on fresh books, which is the thing a predictor would have to beat.**

Two independent derivations of the bar now agree: the lead's **+3.08pp** (from
`E[win−mid | filled] = −1.540 c/share` at a 50c entry) and the agent's π-sweep **+3.03pp**
(≈54.8% side accuracy). Nothing found this session comes within half of it.

---

## LEAD, ROUND 2 (2026-09-07): the 40-60c MAKER question at maximum power — pooled 7 coins

User reaffirmed maker-only, entering at 40-60c. Round 1 was btc-only (~965 band bars); pooling all
seven coins gives ~7,600 and is the only change that materially alters what is knowable.
Fresh books only (`evage<1s`, bug #34). Scripts: `verify/{maker4060,imbtest}.py`.

### 1. The 40-60c mid is calibrated. Pooled bias is +0.98pp against a +3.03pp break-even.
7,632 bars, one row per (coin,bar): mean mid **0.5035**, realized **0.5132**, bias **+0.98pp,
t=+1.88**. Per coin: bnb +2.63 (t=1.89), xrp +1.43, doge +1.31, hype +1.24, eth +0.99, sol +0.26,
btc −0.76. **No coin clears the bar; the pooled estimate is a third of it.**
By fixed tl the bias is −1.67 … +1.37pp with |t| ≤ 1.6 everywhere except tl=60 (−7.25pp, t=−3.21,
n=470 — the wrong sign for a buyer, see §3).

### 2. ⚠️ A 39pp "signal" that was pure snapshot selection — and how it was caught
Taking the **latest** 40-60c snapshot per bar, `imb0` (top-of-book $ imbalance) reads monotone
across quintiles: **−18.60pp (t=−17.5) / −7.44 / +3.07 / +7.38 / +20.51pp (t=+20.2)** — a 39pp
spread and by far the strongest "predictor" ever seen in this project.

**It disappears entirely at FIXED tl:**

| tl | q1 | q2 | q3 | q4 | q5 |
|---|---|---|---|---|---|
| 240 | −2.51 | −4.46 | +2.43 | −1.49 | +0.91 |
| 160 | −3.65 | −1.69 | +4.50 | +1.72 | −6.06 |
| 120 | −1.42 | −0.11 | −0.75 | −2.03 | −4.02 |

Non-monotone, |t| ≤ 2.1. **Cause:** conditioning on "the last snapshot still inside 40-60c"
selects bars that were *about to leave the band*, and the imbalance is mechanically aligned with
the direction they left in. This is the "a field-average cell is NOT the subset you will get" trap
in a new costume — logged as a standing warning: **any per-bar aggregate that selects a snapshot
by a price condition inherits the exit direction.** Always re-test at fixed tl.

### 3. ⭐ THE STRUCTURAL WALL, MEASURED: you fill exactly where you lose
A resting UP bid sits **behind** the displayed bid size and fills when sellers hit it — i.e. when
the bid side is thin and the ask side heavy (`imb0 < 0`). Depth by quintile, tl=120:

| imb0 quintile | mean imb0 | **bid depth ahead of you** | ask depth | does an UP bid fill? |
|---|---|---|---|---|
| q1 | −0.848 | **11.3 sh** | 167.1 | **yes** |
| q3 | −0.050 | 25.2 | 26.3 | yes |
| q5 | +0.731 | **128.6 sh** | 15.4 | **no** |

And in the cells where you *do* fill, at tl=60, UP underperforms the mid by **−13.78pp and
−13.89pp (t=−2.8, −2.9)** — **4.5× the +3.03pp break-even, in the wrong direction.**

**This is why the openmm §11 imbalance gate cannot be lifted into this lane.** Gating on
*favourable* imbalance (imb0 ≥ +0.2) means quoting exactly where **128.6 shares** sit ahead of you;
the gate buys benign selection by giving up the fill. It is a fill-rate trade, not a free lunch,
and the fill rate is the thing that cannot be measured from book snapshots.

### 4. Verdict on the user's design (maker entry at 40-60c)
The mid in that band is unbiased to within **+0.98 ± 0.52pp**; the break-even is **+3.03pp**; the
one candidate discriminator dissolves at fixed tl; and where a resting order actually fills, the
realized edge is **−13.8pp**. Round 1's fill-wall result (a directional quoter suffers −6.04pp of
adverse selection vs −3.73pp for a dumb one) now has a mechanism: **the fill is the market's
option, and it is exercised against you.**
