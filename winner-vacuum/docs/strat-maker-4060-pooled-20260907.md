# Round 2: the 40-60c MAKER lane, pooled over 7 coins — ⛔ CLOSED on its strongest variant (2026-09-07)

**User's ask (reaffirmed twice):** *maker options only, entering as a maker in the 40-60c band.*
**What round 2 changes vs [round 1](strat-predictor-btc5m-20260907.md):** the data, not the model.
Round 1 was btc alone (3,047 rows / **965 bars** in the band). This is **all 7 coins, 8,743 rows /
5,265 bars** on fresh books — 5.5× the clusters, which is the only thing that changes what is
knowable. Working dir `scratchpad/pred2/` (`build7.py`, `feat7.py`, `mkr.py`, `s1`–`s5`).

## ⛔ VERDICT — NO, and now it is a *powered* no, not an underpowered one.

1. **The band is calibrated.** Pooled `E[y − mid] = +0.359 ± 0.774 pp (t = 0.46)`. The favourite
   side carries **+1.172 ± 0.549 pp (t = 2.13)** — real, but the bar is **+3.03 pp**, and the bar
   is now **3.4 σ above the measurement**. Round 1 could not reject +3.1 pp on btc; pooled, we can.
2. **The directional signal does not survive pooling.** Round 1's one survivor spec, refit
   walk-forward on 7 coins, is **anti-predictive at conviction**: −1.2 pp at thr 0.03, **−2.4 pp**
   at 0.05 (4-feature spec) and **−6.68 ± 2.54 pp (t = −2.63)** at 0.05 for the 3-feature spec —
   monotonically worse as the threshold rises, the opposite of a real signal. Model OOS AUC
   **0.5626 vs the mid's own 0.5747** in this band.
3. **⭐ THE NEW RESULT — the `imb0` gate does NOT rescue the maker; with the queue modelled it
   makes it WORSE, and the mechanism is mechanical.** The imbalance that predicts direction *is
   the queue standing in front of you*.
4. **The 40-60c band is the worst cell in the book, pooled**: filled adverse selection −7.4 pp at
   tl 230 rising to **−25.1 pp at tl 40**, against −3.8 pp for btc across all mids.

---

## 0. Pre-registration and the config budget

- **Declared budget: 12 model configurations for the whole run. 7 were used** (5 in the taker
  phase before the scope change — see [strat-sweep-mechanism-20260907](strat-sweep-mechanism-20260907.md) —
  and 2 here: `D1` = walk-forward logistic with `logit(mid)` as an offset on `[ret20, flow120,
  z_hat]`, `D2` = the same on `[imb0, ret20, flow120, z_hat]`, i.e. round 1's surviving spec).
  Bonferroni over 12 needs |t| > **2.23**; over the 7 used, 2.09. **No cell in this document is
  positive, so the correction never binds against a claim — it binds against the negatives, which
  it only strengthens.** Threshold/gate slices (6 selection thresholds × 4 gate levels) are
  evaluation cuts of those two fits and are all reported, not filtered.
- Time-ordered walk-forward only (expanding window, refit daily, first 2 days train-only).
- **Freshness gate `evage < 1 s` AND non-zero trailing tape on every row** (bug #34).
- Fills: post-only at the touch, 60 s, **queue-ahead modelled** (bug #11) and **tape-size-capped**
  (bug #28); rebate `0.2 · 0.07 · q(1−q)` per share on own fills (0.35 c at q = 0.50).
- Clusters = bars (`coin_ws`); every SE below is bar-clustered.

### ⭐ Harness positive control (bug #31 discipline) — it reproduces round 1 exactly
btc only, all mids, tl ≥ 80, queue modelled, both sides at the touch:

| | fill rate | mean fill px | win rate | E[y−mid] FILLED | net c/share |
|---|---|---|---|---|---|
| **this harness** | 82.3 % | 0.4671 | 43.5 % | **−3.762 ± 0.178 pp** | −3.005 |
| round 1 published | 81.5 % | 0.466 | 43.3 % | **−3.74 ± 0.14 pp** | −3.26 |

(the small net difference is the rebate formula: 0.35 c/share here vs round 1's flat 0.254 c.)

---

## 1. The band, pooled — power finally adequate, and the answer is "calibrated"

8,743 rows / **5,265 bars**, `evage<1s` + non-zero tape, mid ∈ [0.40, 0.60], 7 coins.

| tl | rows/bars | E[y−mid] pp | se | t | favourite-side edge pp | se | t |
|---|---|---|---|---|---|---|---|
| 40 | 232 | −0.68 | 3.23 | −0.21 | +4.21 | 3.22 | 1.31 |
| 60 | 438 | −3.43 | 2.34 | −1.46 | +5.51 | 2.33 | 2.36 |
| 80 | 572 | +0.68 | 2.07 | 0.33 | +0.70 | 2.07 | 0.34 |
| 110 | 834 | −2.08 | 1.71 | −1.21 | +2.43 | 1.71 | 1.42 |
| 170 | 1,365 | +0.59 | 1.34 | 0.44 | +1.82 | 1.34 | 1.36 |
| 230 | 2,108 | +1.29 | 1.08 | 1.20 | +0.17 | 1.08 | 0.16 |
| 290 | 3,194 | +0.82 | 0.88 | 0.93 | +0.50 | 0.88 | 0.57 |
| **pooled** | **8,743 / 5,265** | **+0.359** | **0.774** | **0.46** | **+1.172** | **0.549** | **2.13** |

Per coin (pooled tl), favourite-side edge: bnb +2.02, btc +0.72, doge +1.90, eth −1.04,
hype +2.00, sol +0.29, xrp +2.33 pp — **every |t| < 1.7**, no coin carries the effect.

⭐ **The pooled favourite-side edge is +1.17 pp with an SE of 0.55 pp. The maker break-even bar is
+3.03 pp. The gap is 1.86 pp = 3.4 SE.** Round 1 said "cannot certify +3.1 pp"; round 2 says
**+3.1 pp is not there**. The +1.17 pp that *is* there is the same ~1 pp structural averaging
effect round 1 measured (§1 there) and is one third of what a fill costs.

---

## 2. ⛔ The direction signal does not survive pooling — it inverts

Walk-forward (expanding window, refit daily, coin dummies), OOS 6,777 rows / 4,055 bars.
`E[y − mid]` on the model's **chosen side**, bar-clustered:

| selection thr | 0.00 | 0.01 | 0.02 | 0.03 | 0.05 | 0.08 |
|---|---|---|---|---|---|---|
| **D1** (`ret20, flow120, z_hat`) | +0.40 | −0.34 | −1.06 | −2.79 | **−6.68 ± 2.54 (t −2.63)** | −9.85 ± 3.66 |
| **D2** (+ `imb0`, round 1's spec) | +0.69 | +0.40 | −0.43 | −1.22 | −2.36 | −3.96 |

**Monotonically worse with conviction, on both specs.** Round 1's `+6.73 pp at thr 0.05` on btc
was noise — its own feature-shuffle null (sd 6.58 pp, bug #35) said so, and pooling now confirms it
with the opposite sign. In this band the market's own AUC is **0.5747** and the models score
**0.5626 / 0.5625**: nothing beats the mid, exactly as round 1 found at a different horizon.

---

## 3. ⭐⭐ THE MAIN EVENT — the 2×2, and why the `imb0` gate makes it worse

40-60c band, tl 110-290, OOS quote instants 5,798 / 3,855 bars, both tokens quoted at the touch.
Gate = openmm's own definition (`imb0 = (bid0−ask0)/(bid0+ask0)` on the quoted token, sign-flipped
for the DOWN side by the mirror identity, verified against `openmm/src/openmm.py:427`).

| # | config | quotes | fill rate | E[y−mid] FILLED | se | **net c/share** | se |
|---|---|---|---|---|---|---|---|
| 1 | dumb two-sided | 11,596 | 51.7 % | **−8.60** | 0.42 | **−7.03** | 0.42 |
| 2 | + `imb0 ≥ 0.2` gate | 3,430 | 47.8 % | **−11.13** | 1.22 | **−9.92** | 1.22 |
| 3 | direction signal (thr 0.03) | 1,813 | 44.7 % | −10.04 | 1.88 | −8.38 | 1.87 |
| 4 | **direction + `imb0` gate** | 1,170 | 47.1 % | **−9.87** | 2.20 | **−8.68** | 2.20 |

With the queue **not** modelled (the optimistic bound): −4.17 / −3.65 / −4.54 / −3.21 pp filled,
net −2.05 / −2.10 / −2.08 / −1.66 c/share — all negative, all mutually inside noise.

**⭐ The mechanism, and it is the point of this document.** Filled adverse selection as a function
of the **signed** `imb0` (positive = the book leans the way we are quoting):

| signed `imb0` | quotes | fill rate | fills | mean q | win | E[y−mid] FILLED | net c/sh |
|---|---|---|---|---|---|---|---|
| −1.0…−0.6 (leans against us) | 1,912 | **0.720** | 1,377 | 0.4879 | 43.5 % | **−6.25 ± 1.34** | −4.94 |
| −0.6…−0.2 | 1,518 | 0.667 | 1,012 | 0.4875 | 44.9 % | −4.81 ± 1.57 | −3.54 |
| −0.2…+0.2 | 4,736 | 0.416 | 1,971 | 0.4810 | 39.9 % | −10.09 ± 0.78 | −7.88 |
| +0.2…+0.6 | 1,518 | 0.546 | 829 | 0.4901 | 38.1 % | −11.78 ± 1.69 | −10.54 |
| **+0.6…+1.0 (leans our way)** | 1,912 | **0.424** | 810 | 0.4937 | 39.8 % | **−10.45 ± 1.73** | −9.27 |

Quoting into a book that leans our way (`imb0 ≥ +0.2`) fills at **−11.13 ± 1.22 pp**; quoting
into one that leans against us (`imb0 ≤ −0.2`) fills at **−5.64 ± 1.03 pp** — a **−5.49 pp
difference, t = −3.43**, which clears the 12-config Bonferroni bar of 2.23 in the *wrong*
direction for the gate.

**A bid-heavy book is not a friendly book — it is a long queue.** The same top-of-book imbalance
that predicts the outcome (+1.6 pp/SD, round 1 §2) *is* the size standing in front of our order,
so gating on it (a) halves the fill rate (0.72 → 0.42) and (b) selects the fills that arrive only
when the whole queue is swept, i.e. exactly the adverse ones. This is the resting-order wall
([maker-resting-order-wall](maker-resting-order-wall.md)) expressed in a new variable.

### ⚠️ This CONTRADICTS openmm §11's sign, and the reason is the queue model
openmm §11 measured `imb ≥ 0.2` as removing the adverse selection (−$65/day → +$151/day, t=+3.25,
monotone over 6 buckets on 105k **field** fills). Those were other participants' fills — a field
average with **no queue position** — and openmm's own live pilot stopped at **−$8.40 on day 1**.
Here, with the queue ahead modelled at the actual displayed depth, the gate is worth **−2.5 pp**,
not +. Both can be true: the imbalance describes where the *field's* fills are good, and the field
is the queue we are behind. **Do not deploy an `imb0` gate on the strength of the field statistic.**

### Fill-model-independent metrics (50-share clip, 7 coins, 4 OOS days, tl 110-290)

| config | fills | $/day | days positive | worst day |
|---|---|---|---|---|
| dumb two-sided | 5,999 | −$4,845 | **0 of 4** | −$6,927 |
| + `imb0` gate | 1,639 | −$1,938 | **0 of 4** | −$2,275 |
| direction | 811 | −$588 | 1 of 4 | −$1,210 |
| direction + `imb0` | 551 | −$528 | 1 of 4 | −$913 |

Everything scales with volume; the invariant is **days-positive 0-1 of 4 in every configuration**.

---

## 4. What to tell the user
- The 40-60c maker lane is **closed**, and now on adequate power rather than on a shrug. Pooled
  over 7 coins the band's favourite-side edge is **+1.17 ± 0.55 pp** against a **+3.03 pp**
  break-even — the bar sits 3.4 SE away, so this is a rejection, not an "unknown".
- The strongest remaining variant — a directional quoter **plus** the `imb0` fill-quality gate,
  the one combination nobody had tried — is **worse than the dumb two-sided quoter**, not better,
  and the reason is structural: the imbalance that predicts direction is the queue you are behind.
- Round 1's btc-only survivor (+6.73 pp at thr 0.05) **inverts to −2.4…−6.7 pp** when pooled.
- The 40-60c band remains the *hardest* place to try this, and pooling made that sharper, not
  softer: filled adverse selection there is −7.4 pp (tl 230) to −25.1 pp (tl 40) vs −3.8 pp for
  btc across all mids.

## 5. What would have to change for this to reopen
Nothing found here is a tuning problem, so no threshold sweep reopens it. The two things that
would: **(a)** a fill mechanism that does not queue behind the displayed size (a rebate tier, a
maker-taker split, or size that jumps the queue), or **(b)** a directional signal worth ≥3 pp,
which pooling has now shown does not exist in this band at any conviction level.
