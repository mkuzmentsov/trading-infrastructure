# Longer durations (15m / 1h / 4h / 1d) — is the 5m settlement edge un-farmed there?

**Date:** 2026-09-10 (data drained same day) · **Analyst lane:** Agent D
**Verdict up front: REFUTED at every duration. The 5m fleet is where the money is.**

| duration | recon transfers? | fireable bars/day (7 coins) | measured $/day | honest ceiling | verdict |
|---|---|---|---|---|---|
| **15m** | ✅ 100% at \|margin\|>0.5bps | 20.7 | +$1.95/day on 2 coins → ~$6.8 extrapolated, **SE ±$41 on the 9d total (t=0.47)** | ~$0 ± $5 | **REFUTED** (already live-refuted: −$30/2d) |
| **1h** | ❌ 96.8% — *different market family* | ~1 | −$1.58/day | n/a | **REFUTED** |
| **4h** | ✅ 100% (235 bars) | 1.4 | +$1.15/day on 5 coins, $8.42 of $10.33 is **one bar** | **~$0.3/day** | **REFUTED on ceiling** |
| **1d** | ❌ 83% (n=5), different family | 0.1 | 1 clip in 9 days, **lost** | n/a | **REFUTED** |

---

## 0. Pre-registration

Stated before looking at any long-duration result:

1. **H1 (mechanism).** TWAP-60 reconstruction predicts the winner at long durations with ≥ the 5m
   accuracy by margin band. *Decision:* if band-matched accuracy ≈ 5m, the mechanism transfers.
2. **H2 (supply).** ≥25% of bars must carry a **tape-confirmed** in-band (0.55–0.99) favourite BUY
   print in tl∈[3,30] for the lane to be fireable at all.
3. **H3 (economics).** House fill cell only. Report $/clip, clips/day and **loss-bars/day**.
4. **H4 (ceiling).** State bars/day × per-bar EV *before* reacting to any per-clip number.
   Ship bar: ≥$5/day incremental at 7 coins **and** both LOO folds (by day, by coin) positive.

## 1. Data + method

Source: `every-tick-single/data/mrec/{btc,eth}-mrec15m`, `btc-mrec1h`,
`{btc,eth,sol,xrp,hype}-mrec4h`, `btc-mrec1d` — 4,001 files, 09-01 20:00 → 09-10 20:00 UTC.
Extracted to a private parquet set (5m panel untouched):
`snapL` 4.35M cur-role SNAP rows (tl ≤ 200s, top-3 ladders both tokens), `tradesL` 1.24M prints,
`resL`/`barL` 2,196/2,259 bars. Chainlink 1Hz comes from the shared `pq/cl.parquet` (coin-level,
duration-independent).

Three house rules honoured:
- **Relay lag (bug #25).** The live estimate is gated at each SNAP row's **own `cl_ts`** — only
  ticks the recorder had received. (`b_panel.py`, ported from `panel.py`.)
- **Tape-confirmed fills (bug #23).** A fire counts only if a real BUY print at **px ≤ the
  displayed ask** existed within the fill window.
- **House fill cell (bug #27).** Window **0.4s**, price improvement **0¢** (fill AT the displayed
  ask), size capped by the **displayed top-3 ask depth at prices ≤ the ask**, **CLIP $24 / LADDER
  $48**, GAP 8s, §58 mid-band first-clip skip (0.90–0.98), ladder_min 0.94, threshold
  `0.10 + 0.035·max(0, tl−14)`, cov ≥ 0.5, tl ∈ [3,20] (§37 late-fire).

### 1a. Cell calibrated against live ground truth first (rule #3)

The identical code, run on the **5m** panel for 09-02…09-04:

| | PnL | bars | loss bars |
|---|---|---|---|
| live 5m fleet (ground truth) | +$18.40 | 351 | 17 |
| published house cell (README) | +$34.94 | 312 | 22 |
| **this implementation** | **+$33.79** | **307** | **22** |

Reproduced to within $1.15 / 5 bars / 0 loss bars. Full 9 days it reads **+$107.54 = $10.75/day,
1,031 bars, 4.8 loss bars/day** vs the live era's $19.9/day (the replay has no halts/brake, and the
gap is the known conservative bias). **The same code and the same cell produce every long-duration
number below.**

---

## 2. Q1 — Does the recon work at 15m / 4h? **Yes at 15m and 4h. No at 1h/1d — those are a
## different market family.**

Full-window TWAP-60 reconstruction (`[ws−62, ws−3]` strike vs `[end−62, end−3]` final), with a
tick-completeness guard (≥50 of 59 ticks observed at both ends — bug #24 family):

| \|margin\| band | 15m acc (n) | 4h acc (n) | 1h acc (n) | 5m acc (n) |
|---|---|---|---|---|
| 0–0.5 bps | 0.913 (46) | — | 0.750 (4) | 0.923 (777) |
| 0.5–1 | 1.000 (52) | 1.000 (1) | 0.000 (1) | 0.987 (758) |
| 1–2 | 1.000 (97) | 1.000 (4) | 0.571 (7) | 0.992 (1,436) |
| 2–5 | 1.000 (283) | 1.000 (12) | 0.900 (10) | 0.998 (3,709) |
| ≥5 | 1.000 (1,043) | 1.000 (218) | 1.000 (165) | 0.9999 (11,586) |
| **overall** | **0.9974** | **1.0000** | **0.9679** | **0.994** |

Window search confirms TWAP-60 is the right rule at 15m and 4h (TWAP-30 → 98.1%/98.0%,
TWAP-300 → 85.0%/94.2%, `[−60,0)` ≈ same as `[−62,−3)`).

**The 1h/1d failure is not a broken recon — it is a different product.** The BAR metadata shows it:

| duration | slug |
|---|---|
| 15m | `btc-updown-15m-1788651900` ✅ TWAP series |
| 4h | `btc-updown-4h-1788336000` ✅ TWAP series |
| **1h** | `bitcoin-up-or-down-september-5-2026-10pm-et` ❌ legacy hourly family |
| **1d** | `bitcoin-up-or-down-on-september-3-2026` ❌ legacy daily family |

The 1h errors are sign-flips at 1–2 bps on 80k-dollar btc — exactly what a *different reference
price* looks like, not what relay noise looks like. **1h and 1d do not settle on the TWAP-60 we can
reconstruct; the mechanism does not exist there.** (Consistent with the CLOSED-table line "1h/1d
series measured dead".)

**Live (relay-lagged) estimate accuracy** at the decision second, |est| ≥ 0.5 bps:

| tl | 15m | 4h | 1h | 5m |
|---|---|---|---|---|
| 3 | 0.9994 | 1.000 | 0.9695 | 0.9986 |
| 12 | 0.9968 | 1.000 | 0.9694 | — |
| 20 | 0.9898 | 1.000 | 0.9643 | ~0.988 |
| 30 | 0.9844 | 1.000 | 0.9592 | 0.9777 |

**H1 answer: the mechanism transfers cleanly to 15m and 4h — in fact 4h reads 100% because a 4h
bar's median margin is 27–71 bps, decided hours before the close. That is the problem, not the
prize.**

---

## 3. Q2 — Is there takeable supply in the last 30s? **No. Less than at 5m, and it is worse
## adversely selected.**

Measured on the **print tape**, never on displayed quotes.

**Displayed-ask presence** (decisive bars, tl 3–30, share of *seconds*):

| | no ask at all | in-band 0.55–0.99 | at 0.995–1.00 (worthless) |
|---|---|---|---|
| 5m | 88.79% | 5.54% | 1.12% |
| **15m** | **91.75%** | **3.90%** | 0.64% |
| 4h | 51.32% | 16.64% | **29.98%** |
| 1h | 78.24% | 8.97% | 9.88% |

**Tape-confirmed favourite-side in-band BUY prints** (tl 3–30, 0.55–0.99), 9 days:

| dur | bars with ≥1 such print | hit % of bars | prints | notional |
|---|---|---|---|---|
| 15m (2 coins) | 176 / 1,688 | **10.4%** | 4,661 | $174,749 |
| 4h (5 coins) | 21 / 294 | **7.1%** | 120 | $5,156 |
| 1h (1 coin) | 28 / 206 | 13.6% | 243 | $14,565 |
| 1d (1 coin) | 1 / 8 | 12.5% | 14 | $4,264 |

**H2 fails at every duration** (threshold was 25%). At 4h the displayed book *looks* rich — 16.6%
of late seconds show an in-band ask, 48 of 254 bars — but only 21 bars carry a print. Ghost ratio
≈ 2.3×; running the sim with the tape gate removed inflates 15m from +$19.45 to **+$60.79** (3.1×)
and 4h from +$10.33 to +$41.18 (4.0×). Bug #23 is alive at every duration.

### The mechanism that kills it: the ask only exists on near-ties, and worse so at 15m

| population (tl 3–20, decisive) | median \|est\| | accuracy |
|---|---|---|
| 5m — all decisive seconds | 7.4 bps | 0.9900 |
| 5m — **conditional on a takeable 0.98–0.99 ask** | **1.2 bps** | **0.9921** |
| 15m — all decisive seconds | 9.3 bps | 0.9920 |
| 15m — **conditional on a takeable 0.98–0.99 ask** | **0.7 bps** | **0.9868** |
| 4h — all decisive seconds | 46.9 bps | 1.0000 |
| 4h — conditional on a 0.98–0.99 ask | 7.4 bps | 1.0000 (n=484 sec / 8 bars) |

A 15m bar's doubt resolves *earlier relative to its close*, so by the last 20 seconds the only
quotes still standing are on genuine coin-flips: the residual margin behind a takeable 15m ask is
**0.7 bps vs 1.2 bps at 5m**. The recon is better at 15m and the fills are worse. This is the
taker-side adverse-selection wall (`ua ≡ 1 − db`), amplified by bar length.

**The breakeven arithmetic that decides everything** ($24 clip, crypto fee 0.07·p·(1−p)):

| ask | win | loss | payoff | breakeven win rate |
|---|---|---|---|---|
| 0.90 | +$2.50 | −$24.17 | 10:1 | 90.63% |
| 0.98 | +$0.456 | −$24.03 | 53:1 | 98.14% |
| **0.99** | **+$0.226** | **−$24.02** | **106:1** | **99.07%** |

5m clears 0.99 by **+0.14pp**. 15m misses it by **−1.39pp**. That is the whole story.

---

## 4. Q3 — What does a clip actually earn? (house cell, tape-confirmed)

| | clips | bars | clips/day | **loss bars/day** | stake | PnL | ROI | $/day | worst day | +days |
|---|---|---|---|---|---|---|---|---|---|---|
| **15m** (btc+eth, 10d) | 68 | 59 | 5.2 | **0.23** | $1,489 | **+$19.45** | 1.31% | +$1.95 | −$24.35 | 8/10 |
| **4h** (5 coins, 9d) | 10 | 9 | 0.8 | 0.00 | $227 | +$10.33 | 4.55% | +$1.15 | +$0.23 | 6/6 |
| **1h** (btc, 9d) | 14 | 13 | 1.1 | 0.08 | $293 | **−$20.55** | −7.01% | −$1.58 | −$24.14 | 7/8 |
| **1d** (btc, 9d) | 1 | 1 | 0.1 | 0.08 | $8 | **−$8.08** | −101% | −$0.62 | −$8.08 | 0/1 |
| *5m reference* (7 coins, 10d) | 1,164 | 1,031 | 116 | 4.8 | $23,400 | +$107.54 | 0.46% | +$10.75 | −$80.72 | 6/10 |

**Payoff structure at 15m:** 56 wins averaging **+$1.38**, 3 losses averaging **−$19.36** — 14:1.
Win rate 94.9% against a blended breakeven of 93.3%. The margin is 1.6pp with n = 59, and the
standard error of the win rate is **2.9pp**. Win count is meaningless here exactly as at 5m.

**By ask band — this is the decisive cut:**

| band | 5m bars/day | 5m WR | 5m $/day | | 15m bars/day | 15m WR | 15m $/day |
|---|---|---|---|---|---|---|---|
| 0.55–0.90 | 18.6 | 77.96% (BE 77.07%) | +$3.46 | | 1.7 | 88.24% (BE 79.07%) | +$3.36 |
| **0.98–0.99** | **31.6** | **98.73% (BE 98.35%)** | **+$2.99** | | **4.2** | **97.62% (BE 99.00%)** | **−$1.41** |

**The 15m workhorse band — 71% of its fireable bars — is negative.** All of 15m's headline profit
sits in 17 cheap-ask bars, which is the lane §38 (buy-the-dip) closed at 5m.

---

## 5. LOO robustness — nothing survives

**15m** (+$19.45 total, bar-clustered **SE $41.10, t = 0.47** — indistinguishable from zero):

- LOO by **coin**: drop eth → **−$22.07**. btc alone is a loser. 1 of 2 folds negative.
- LOO by **day**: drop 09-04 → +$3.80; drop 09-07 → **+$2.40**. Two days carry it.
- The cheap band alone (+$33.55, 17 bars): drop eth → **−$4.37**. Same single-coin pattern that
  killed buy-the-dip (13 of 15 wins on one day).

**4h** (+$10.33, SE $8.19, t = 1.26): **$8.42 of $10.33 is one bar** (btc, 09-02, ask ≤ 0.90).
Drop that day → **+$1.91 over 9 days = $0.21/day across 5 coins**. Drop btc → +$1.69.

**Grid scan** (60 cells: tl ∈ {12,20,30} × 5 ask bands × mid-band skip on/off, both durations).
Cells that are positive with *both* LOO folds positive: 6 at 15m, 24 at 4h — every one of them has
**≤16 bars and 0–0 losses in 9 days**. At a 99.07% breakeven you need ~100+ bars to distinguish a
+EV cell from a −EV one; none of these has sampled its first loss yet. This is the multiple-
comparisons signature, not a finding. The best-looking cell (15m, tl ≤ 12, +$41.00) is $38.41
cheap-ask bars, which LOO-drops to +$4.63 without eth.

## 6. Score against live ground truth (rule #3)

The 15m lane **ran live**: btc pilot from 08-30 (§60), fleet-wide 09-02 22:50K, **stopped by the
user 09-03 22:20K** at ≈ **−$30 over 2 days** at $12/$24 sizing (doge15 −$23.16, btc15 −$11.76).

This replay, over the same two days, btc+eth only:

| | PnL | bars | loss bars |
|---|---|---|---|
| replay at $24/$48 | −$44.28 | 8 | 3 |
| replay rescaled to live $12/$24 | **−$22.14** | 8 | 3 |
| live 15m fleet, 7 coins, $12/$24 | **≈ −$30** | — | — |

Same sign, same order of magnitude, from two coins where live ran seven. **The replay agrees with
the only live evidence we have.** The 15m lane was not stopped prematurely — it was stopped
correctly.

## 7. Q4 — The ceiling, stated before any excitement

Bars/coin/day: 5m 288 · 15m 96 · 1h 24 · 4h 6 · 1d 1.

**Absolute theoretical maximum** — capture *every* winner-side print at 0.90–0.99 in tl∈[3,30],
zero competition, zero losses, unlimited capital:

| dur | measured pool | per coin/day | **at 7 coins** | our historical capture rate | implied |
|---|---|---|---|---|---|
| 5m | $4,422/day (7 coins) | $632 | $4,422 | live $19.9/day = **0.45%** | — |
| **15m** | $425/day (2 coins) | $212 | **$1,487** | 0.45% | **≈ $6.7/day** |
| 4h | $12.80/day (5 coins) | $2.56 | **$18** | 0.45% | **≈ $0.08/day** |
| 1h | $28/day (1 coin) | $28 | (wrong family) | — | — |

The bottom-up sim agrees: 15m fires 2.95 bars/coin/day → 20.7 bars/day at 7 coins × ~$0.33/bar ≈
$6.8/day. **Both routes land on ~$7/day gross for a full 7-coin 15m fleet — and that $7 is a point
estimate with a ±$41/9d standard error whose workhorse band is negative.** 4h lands on $0.2–0.3/day
at 7 coins, where a *single* 0.99 loss (−$24) costs 100 winning bars.

Extrapolating btc+eth to 7 coins is a coin-*count* assumption, not a coin *ranking* — but note the
replay/live per-coin anti-correlation (r = −0.63): the honest reading is that the per-coin numbers
here carry no information about which coin would be best, only about the aggregate scale.

---

## 8. Verdicts

**15m — REFUTED.** Mechanism transfers (recon 100% above 0.5 bps), supply does not: 91.75% of
decisive late seconds have no favourite ask; only 10.4% of bars carry a tape-confirmed in-band
print; the takeable 0.98–0.99 ask sits behind a 0.7 bps residual margin (vs 1.2 at 5m), so
fill-conditional accuracy is 97.6% against a 99.07% breakeven. Point estimate +$1.95/day on 2
coins, SE $41 on the 9-day total, negative on btc, negative in the band carrying 71% of volume,
and the two days it ran live lost $30. Ceiling ~$7/day gross at 7 coins in the best case.
**Do not restart the 15m fleet.**

**1h — REFUTED, and for a reason worth recording:** `bitcoin-up-or-down-<date>-<hour>et` is the
legacy hourly family, **not** the `*-updown-*` TWAP series. Our TWAP-60 recon reads 96.8% there,
with sign flips at 1–2 bps — a different reference price. There is no arithmetic edge to farm.

**4h — REFUTED on ceiling.** The mechanism is perfect (100% recon on 235 bars; 100% fill-conditional
accuracy on 8 bars) and the lane is genuinely +EV as far as we can see. It is simply too small:
6 bars/coin/day, 7.1% of them fireable → **1.4 fireable bars/day across 7 coins, ceiling ~$0.3/day**,
carried in this sample by one bar. Not worth a pod, a halt budget, or an operator's attention.

**1d — REFUTED.** Legacy family, 8 bars in 9 days, recon 83% (n=5), 1 clip taken and lost.

**The answer to the brief's question is the plain one: the 5m fleet is where the money is. Longer
durations do not clear.** The reason is not competition thinning out — it is that a longer bar
resolves its uncertainty earlier relative to its close, so the settlement window we exploit is
*more* pre-priced, not less. Supply in the last 30s exists only where our own estimate is weakest,
and it gets weaker as the bar gets longer.

**No config change is proposed. Nothing was deployed, edited or committed.**

## 9. Operational note (not a recommendation to act)

`btc-mrec1h` and `btc-mrec1d` are recording a market family that does not share the settlement
mechanism (§2 above) — 1.24GB on disk and two recorder pods producing data that cannot answer a
TWAP question. If recorder capacity is ever tight, these are the first two to retire. The 15m and
4h recorders should stay: they are the only ongoing check on whether the *venue* ever moves these
series onto a different clock.

## 10. Reproduction

Scripts live in the session scratchpad (`scratchpad/long/`), not committed:
`l2pq.py` (extract) → `a_recon.py` (Q1) → `b_panel.py` (relay-lagged panel) →
`c_supply.py` (Q2, print tape) → `d_sim.py` (Q3, house cell) → `e_calib5m.py` (the §1a
ground-truth calibration; **run this first if the cell is ever changed**).
