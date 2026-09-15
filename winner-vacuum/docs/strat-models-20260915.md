# MODELS.md — the first models ever trained on this venue

**2026-09-15. Round 2 deliverable: three modelling targets, trained, validated and
scored in net cents per share. Nothing deployed. No live-fleet change proposed.**

Base: `/private/tmp/claude-501/-Users-maxkuzmentsov-development-projects-my-hummingbot-hummingbot-infra/34249563-b474-4d9e-bdf4-d3c52eb5d2de/scratchpad/research`
Scripts: `models/`. Raw outputs: `out/models/`. Harness: `harness/hx.py`, `models/evh.py`.

---

## 0. Answer first

**All three targets read negative, and one of them reads negative for a reason worth more
than a model: the sample cannot resolve what we are asking of it.**

| target | best OOS result | verdict |
|---|---|---|
| **1a. loss avoidance — VETO** (evals_live, 53,311 bars, 30 d) | +$0.93/day, day t=+1.11, deflated t **−0.68** | **DEAD** — 5 independent kills |
| **1b. same model used to SIZE, not to veto** | **+$2.72/day, paired day t=+2.75**, all 7 coins +, placebo z=+3.80 | **CONDITIONAL** — collapses to +$0.33 (t=0.66) if displayed depth does not fill |
| **2. fill quality** (live ledger, 8,496 attempts, 29 days) | corr(pred, realised $) = **−0.000** | **DEAD** — the object is unpredictable |
| **3. direction control** (panel, 4,321 bars, 3 days) | no model beats the market mid anywhere | **TRIPWIRE CLEAN** |

**The one live thread: the model cannot veto, but it may be able to size.** Same p(win)
model, same fires, same total stake per day — only the *distribution* of stake changes.
That reads +$2.72/day at paired day t=+2.75, survives a weight-shuffle placebo (z=+3.80),
a side-flip placebo (+0.01), LOO-day (all positive), every one of 7 coins, and a
feasibility check on displayed size. It then **fails the only test that matters**: it
assumes the extra size fills. Force the extra shares not to fill and it is +$0.33/day,
t=+0.66. §3.7. **That question is not answerable offline and I am not proposing a way to
answer it live.**

Three things that are worth more than the null results:

1. **The power bound on target 1.** A *perfect* loss oracle on the fired set is worth
   **+$17.57/day**. The day-level sd of daily $ is 10.46, so the MDE at G=30 days is
   **+$5.35/day** at 80% power. A rule must catch **≥30 % of all losses with zero false
   positives** to be visible in 30 days. Our best candidate catches 47 % of losses but
   throws away 326 winners to do it, and nets +$0.93/day. **This question is underpowered,
   not answered** — and it stays underpowered until the ledger is ~4× longer.
2. **A leak in my own first pass, found by the tripwire discipline.** `clip` in
   `PF_TE_WHALE_ORDER` equals `prior_fills + 1{matched}` — the column contains the label.
   It gave `P(match)` an OOS AUC of **1.0000**. Fixed; the clean model reads 0.9416. See §4.1.
3. **The economics say the estimator is already better than the market and it still
   is not enough.** At tl 3–30 the market's own favourite, taken at the displayed ask,
   nets **−3.09 c/share**. The fleet's estimator gate nets **−0.28 c/share**, a lift of
   **+0.744 c/share over the market**. A perfect oracle nets +5.33. The estimator captures
   21 % of available foresight, beats the market decisively, **and is still below zero at
   the ask.** Accuracy was never the binding constraint here. Price is.

---

## 1. Fee model (venue correction, 2026-09-15, applied throughout)

Reconciled on our own tape: **4,390 settled fills, 55,364 shares, $127.20 fee = 0.230
c/share**, mean realised `p(1−p)` = **0.0319**. (The venue agent's 4,721 fills / $134.00 /
0.0334 is the same number on the unsettled-inclusive set; agreement 5 %.)

* `harness/build_fills.py` already charges `0.07 · avg_px · (1−avg_px) · shares` — on the
  **fill** price, as required. Charging on the displayed ask instead would overstate the
  fleet fee by **0.5 %** (deep fills are rare); per-fill in the sweep band it matters a lot.
* `models/ev_build.py` charges on the displayed ask. That is correct there: `evals_live`
  has no fill outcome, so the ask *is* the ex-ante expected fill price.
* Fee per share: 1.750 c @0.50, 0.630 @0.90, 0.333 @0.95, 0.204 @0.97, 0.069 @0.99.
  **No rebate is credited anywhere in this code**, per the venue finding that ongoing
  taker rebate is $0.
* Tick-size break at 0.96 (0.01 → 0.001) is entered in the fill models as an indicator
  plus distance-from-break, not as more ask. 78.6 % of fills sit above it.

---

## 2. Target 3 — the DIRECTION control (run first, as the tripwire)

`models/dir1_control.py`, `models/dir2_econ.py`, `models/dir3_lat.py` →
`out/models/dir{1,2,3}.txt`

### 2.1 The tripwire: no model beats the market where it must not

Split contiguous forward-in-time by day (train 09-12+09-13 → test 09-14).
Two regimes, because they ask different questions.

| regime | market mid | market-only | book+flow+price | +binance | +estimator | verdict |
|---|---|---|---|---|---|---|
| **A** window OPEN, tl 3–30 | 0.9997 | 0.9997 | 0.9997 | 0.9997 | 0.9997 | — |
| **B** window CLOSED, tl 63–180 | **0.9320** | 0.9312 | 0.9269 | 0.9248 | n/a (NaN by construction) | **clean** |

Regime B is the real tripwire: at tl ≥ 63 the settlement window has not opened, `est_*` is
NaN (bug #43), and there is **no legitimate source** of settlement information. Every model
lands *below* the market mid. Label-shuffle placebos (block-shuffled by bar, bug #35) read
0.4877–0.5064 in both regimes. **No leakage alarm.**

### 2.2 Where the famous AUC 0.8493 actually lives

The prior figure is reproducible, but only on the right slice. Pooled row-level AUC over
~28 near-duplicate rows per bar is inflated:

| tl | n | AUC pooled | AUC undecided (mkt 0.05–0.95) | undecided share | AUC 1 row/bar |
|---|---|---|---|---|---|
| 3–10 | 30,622 | 1.0000 | 0.9688 | 1.5 % | 1.0000 |
| 21–30 | 39,277 | 0.9986 | 0.9000 | 9.7 % | 0.9990 |
| 63–90 | 116,997 | 0.9604 | 0.8748 | 47.0 % | 0.9737 |
| **121–180** | 255,301 | 0.8803 | **0.8402** | 83.5 % | 0.9096 |

**0.8493 is the long-horizon, undecided slice.** Quote AUC with its tl band and its
decidedness filter or it means nothing.

### 2.3 The economics — the headline, and why AUC is the wrong one

tl 3–30, ask 0.55–0.99, net cents per share at the **real displayed ask**, fee on that ask,
SE = max(bar, coin-day) clustered. 3 days / 4,321 bars, so the day-clustered SE is not
estimable (G=3) and is printed only as a sensitivity.

| strategy | rows | bars | acc | **net c/share** | se (bar) | lift vs market |
|---|---|---|---|---|---|---|
| market-implied baseline | 12,491 | 1,033 | 0.9032 | **−3.093** | 0.799 | — |
| est_live ≥ 0.5 bps (the fleet gate) | 6,395 | 843 | 0.9623 | **−0.279** | 0.638 | **+0.744** |
| est_live ≥ 2.0 bps | 842 | 224 | 0.9786 | +0.030 | 1.142 | +0.398 |
| est_live ≥ 5.0 bps | 15 | 10 | 1.0000 | +3.704 | 2.570 | +0.000 |
| **ORACLE realised margin (ceiling)** | 11,703 | 1,030 | 0.9906 | **+5.334** | 0.405 | +3.480 |

Label-shuffle placebo reads −43.8 to −50.6 c/share against an arithmetic prediction of
−43.4 to −47.8 — the harness prints **CONTROL IS VACUOUS** on every row, correctly (bug #30).
Side-flip placebo: −7.1 to −20.4 c/share. Use those, not the shuffle.

### 2.4 The bug #32 latency tell, run deliberately

Same gate, same rows, estimator swapped for staler and for **clairvoyant** versions:

| estimator | acc | net c/share | lift vs market |
|---|---|---|---|
| est_ahd5 (reads 5 s of FUTURE ticks — bug #25 recreated on purpose) | 0.9812 | +1.426 | +1.180 |
| est_ahd2 | 0.9680 | −0.032 | +0.756 |
| **est_live** (what the bot has) | 0.9623 | −0.279 | +0.744 |
| est_lag2 | 0.9566 | −0.509 | +0.579 |
| est_lag5 | 0.9490 | −0.754 | +0.456 |

**Monotone decay from clairvoyant to stale.** This is the healthy direction: the edge
shrinks when execution is slowed. Nothing in this round shows the bug #32 signature except
the one candidate killed in §3.4.

Note the size of the prize: 5 s of perfect foresight moves net from −0.28 to +1.43 c/share.
That is the whole value of the relay race, and it is +1.7 c/share — consistent with the
memory's "perfect zero-lag oracle worth $0.67/day" once fill rates are applied.

---

## 3. Target 1 — LOSS AVOIDANCE on `evals_live`

`models/ev_build.py` → `data/evx.parquet`; `models/ev{0..8}.py` → `out/models/ev*.txt`.
Frame: `PF_TE_EVAL` (the bot's tl≈28 decision record on every bar it saw) joined to
`PF_TE_SETTLE` outcomes. **53,311 bars, 30 days, 3,280 fires.** Nothing in the feature
set reads anything the bot did not have at t.

### 3.1 The baseline nobody had measured

| | value |
|---|---|
| fired rows / bars / days | 3,280 / 3,280 / 30 |
| accuracy | 0.9351 |
| mean displayed ask | 0.9214 |
| **net** | **+0.918 c/share**, se_bar 0.407, se_coin-day 0.453, **se_day 0.549 → t = 1.67** |
| losses | 213 (6.5 %) |
| payoff | win **+6.64** c/share, loss **−81.53** c/share (≈12:1 in c/share; ≈30:1 in $ because sweeps buy more shares) |
| $ at measured band fill rates, $8 dollar-denominated clip | $3.41/day (the live fleet is $8.37/day — the bot sends several clips per bar; this universe is one eval per bar) |

**The fired set's own edge is not significant at 30 day-clusters.** Everything below is a
paired difference against this, which is the only inference the day-level noise permits.

### 3.2 The p(win) model — it works as a model

Expanding-window walk-forward **by day** (train days[0:i], predict day i, min 10 train days).
Trained on **all 53,311 bars**, fired or not, so the small selected fired set is never in
the fit. The price enters only at the decision: keep ⟺ `p̂ − ask − fee(ask) > τ`.

| feature set / learner | OOS rows | AUC(win) | Brier | calib slope |
|---|---|---|---|---|
| margin-only / logit | 36,947 | 0.9449 | 0.01793 | 1.131 |
| margin-only / hgb | 36,947 | 0.9435 | 0.01804 | 1.109 |
| est-block / logit | 36,947 | 0.9593 | 0.01707 | 1.042 |
| **est-block / hgb** | 36,947 | **0.9579** | 0.01703 | **0.988** |
| full (+ask) / hgb | 36,947 | 0.9710 | 0.01497 | 1.004 |

On the **selected OOS fired set** (the population that matters) the same models read
AUC 0.793 (est-block, calib 0.750) and 0.831 (full, calib 0.914). Predicted edge sorts
realised net: decile rank-corr 0.661 (est-block) and 0.697 (full).

**The model is genuine and well calibrated. It still changes nothing.** §3.3–3.4.

### 3.3 The decision: the veto pays nothing

18 pre-registered cells (6 models × τ=0, then 2 models × τ ∈ {−4,−2,−1} c/share, each on
all fires and on ask ≥ 0.90). Paired **day-level** difference vs the bot's own gate; the
dropped rows *are* the treatment, so this is the exact counterfactual.

* **τ = 0 (drop every row with E[net] ≤ 0)**: drops 40–48 % of fires, paired delta
  **−0.83 to −0.14 $/day, every |t| ≤ 0.83.** The model correctly identifies rows whose
  net is ≈0 — and dropping ≈0 recovers ≈0. This is a **capacity** result (the same money
  from half the trades), not a PnL one; hand it to portfolio-strategist, not to a gate.
* **Best of all 18: p_full, τ = −2 c/share, all fires: +0.934 $/day, day t = +1.11,
  deflated t = −0.68** after 18 configs. LOO-day range [+0.60, +1.37], all positive.
  That was the only cell worth attacking.

### 3.4 …and it dies four ways (`models/ev7_break.py`)

| break test | result |
|---|---|
| **concentration** | dropped 387 rows, recovering $18.68 over 20 d. **Top-1 = 22 %, top-5 = 110 % of the recovery. Ex-top-5: −$0.097/day.** The candidate is 5 rows. |
| **band** | restricted to ask ≥ 0.90 — the only band where $ is computable offline (bug #23/#33) — it is **+0.14 $/day, t = +0.20**. The entire effect lives where the displayed ask is not the live fill population. |
| **30-day blocked CV** | +0.19 $/day, t = +0.30. |
| **coin holdout** (train with the coin removed) | bnb +0.19, btc −0.04, doge −0.07, eth +0.13, hype +0.02, sol −0.01, **xrp −0.36**. Nothing survives. |
| **latency tell** | paired value by relay-lag tercile: low **−0.54**, mid **+0.39**, high **+1.08** $/day. **Grows with staleness.** (Benign reading available — stale rows are where the estimator is worst, so there is more to catch — but combined with the four above it is a fifth flag, not a defence.) |
| **hand rules, no model** | `ask<0.90 & est<1.5bps` +0.17 (t=0.21); `ask<0.90 & est<1.0` −0.23; `est<1.0 any ask` −0.81. A model is not buying anything a rule could not. |

### 3.5 The power bound — the result worth keeping

`models/ev8_ceiling.py`

* **Perfect loss oracle** (drop every loss, non-causal positive control): **+$17.57/day**,
  t = +10.01, 28/30 days improved, every coin positive. That is the ceiling of the lane.
* Partial oracles, **zero false positives**: catch 10 % of losses → +$1.76/day;
  25 % → +$4.36; 50 % → +$8.74.
* Day-level sd of daily $ = **10.46** ⇒ **MDE at G=30 = +$5.35/day** at 80 % power.

⇒ **A loss-avoidance rule is detectable in this dataset only if it catches ~30 % of all
losses while dropping essentially no winners.** Our best model catches 47 % of losses but
pays 326 winners for it. The 30:1 payoff argument is right in principle and the arithmetic
still does not close, because the veto's false-positive rate is the binding term and this
model's is ~13 %.

### 3.6a ⭐ SIZING — the one thread that is alive, and exactly how it dies

`models/ev9_size.py`, `ev10_break_size.py`, `ev11_size2.py` → `out/models/ev{9,10,11}.txt`

The veto fails because it is a hard threshold on a model whose discrimination is in the
tails: it pays 326 winners to catch 61 losses. **Sizing is the soft version of the same
information and it is budget-neutral by construction** — total stake per day is held
identical to flat, only its distribution across the *same* fires changes. That removes the
"won by trading less" escape route entirely.

`w ∝ clip(1 + 20·(p̂ − ask − fee), 0.5, 2.0)`, renormalised per day, on OOS fires
(n=2,430, 20 days):

| scheme | model | paired Δ $/day | day t | days+ | ex-best-day | LOO range |
|---|---|---|---|---|---|---|
| edge-prop (uncapped) | p_full | +16.98 | +3.19 | 14/20 | +14.81 | [+14.8, +18.9] |
| edge-prop (uncapped) | p_est | +13.91 | +3.15 | 16/20 | +12.06 | [+12.1, +16.3] |
| **cap 2.0x** | **p_full** | **+2.723** | **+2.75** | **15/20** | **+2.159** | **[+2.16, +3.01]** |
| cap 2.0x | p_est | +2.087 | +2.71 | 14/20 | +1.670 | [+1.67, +2.38] |
| cap 1.5x | p_full | +1.748 | +2.65 | 15/20 | +1.404 | [+1.40, +1.95] |
| cap 1.25x | p_full | +0.873 | +2.08 | 13/20 | +0.668 | [+0.67, +1.02] |

Uncapped edge-prop is not a candidate — its stake multiplier reaches 48.7× and it is the
rejected buy-the-dip lever in disguise. **cap2x is the candidate.** What it survives:

| attack | result |
|---|---|
| **weight-shuffle placebo** (permute the same weights within day, 300 draws) — the only honest null for a sizing rule, and the direct answer to "the permutation null reads t≈2-3 on noise here" | mean +0.055, sd 0.702, **z = +3.80, p(≥obs) = 0/300** |
| **side-flip placebo** | **+0.015 $/day, t = +0.09** |
| **band** (ask ≥ 0.90, the only band where $ is computable, bug #23/#33) | **+1.361 $/day, t = +1.98**; ask < 0.90 +1.248, t = +2.51. Roughly half in each — *not* a cheap-band artefact |
| **per-coin** | **all seven positive**: bnb +0.33, btc +0.45, doge +1.06, eth +0.25, hype +0.27, sol +0.20, xrp +0.15 |
| **feasibility** | stake multiplier p50 0.98, p99 2.07, max 2.3. Rows wanting more shares than the displayed size: **15.2 % vs 15.6 % for flat** — no worse than what the bot already does |
| **cap sensitivity** | monotone and smooth from 1.25x to 2.0x; not a tail artefact |
| **mechanism** | up-weight +1.813 (t=2.64), down-weight +0.978 (t=1.96). Both contribute; the down-weight half is a *soft veto* that works where the hard veto did not |
| **coin holdout** (p retrained with the coin removed) | sum +$1.20/day; only eth individually significant (t=2.28), btc −0.10. Weaker, not refuting |
| **latency tell** | low-lag tercile +0.044, mid +1.381, high +1.160. ⚠️ **Not clean** — value is ~0 at the freshest tercile. Benign reading (stale rows are where the model has most to correct) is available but unproven; `evals_live` carries one estimator so the proper degradation test cannot be run here |

**And the attack it does not survive** (`ev11_size2.py` (C)). Every number above assumes a
2× clip fills at the same band rate as a 1× clip. Force the extra shares not to fill:

| fill assumption for multiplier m > 1 | Δ $/day | day t |
|---|---|---|
| same band rate (everything above) | **+2.723** | +2.75 |
| degraded, rate·(1/m)^0.5 | +1.380 | +2.19 |
| **hard: rate·(1/m) — the extra size never fills** | **+0.326** | **+0.66** |

**The entire result is a wager that displayed depth is real.** This venue's own history says
that is precisely the thing not to trust: §72 retracted a whole finding because 271
decisive bars showed cheap asks of which *one* ever printed, and bug #33 exists because the
live filled population below 0.90 is not the displayed one. The feasibility check in
ev10 (c) uses `ask_sz`, which is the same displayed number under suspicion — it cannot
rescue the assumption it depends on.

**Verdict: CONDITIONAL, not a result.** It is the only thing in this round that beats its
own placebo, and it is not resolvable from any data we have. Resolving it requires
observing fills at more than one clip size, which no existing tape contains.
Deflated over this round's ~75 configs (√(2 ln 75) = 2.94) the t of +2.75 reads −0.19;
deflated over the 8-cell sizing family alone (2.04) it reads +0.71. Neither is a green light.

### 3.6 The mirror question (add, don't veto)

Eligible-but-not-fired rows (the cap ladder blocked them): 1,912 rows over 20 OOS days,
ask 0.9657, acc 0.9634, **net −0.441 c/share**. Adding back the 433 rows with model edge
≥ 0: **+$0.60/day, day t = +1.16, 13/20 days, top-5 = 27 %.** Below MDE. Tighter thresholds
collapse to n=50–70 and go negative. Nothing here.

---

## 4. Target 2 — FILL QUALITY

`models/fl1_sweep.py`, `fl2_value.py`, `fl3_mech.py`, `fl4_clean.py` → `out/models/fl*.txt`
Universe: the pod ledger, **8,496 attempts / 4,390 settled fills / 29 days**, real prices,
real PnL, no fill model.

### 4.1 ⚠️ A leak, in my own first pass

`build_fills.py`'s own docstring documents that `clip` means two different things:
on a **matched** row it is the 1-based index of the clip that filled; on an **unmatched**
row it is the count of clips filled so far. So

```
clip == prior_fills + 1{matched}
```

**the column contains the label.** Fed to a `P(match)` model it produced an OOS
**AUC of 1.0000** (crosstab: `clip=0` for 96 % of unmatched, `clip≥1` for all matched).
`fl2_value.py` and `fl3_mech.py` as first written both used it. Their headline results were
already null so the leak produced no false positive, but **`fl4_clean.py` is the version to
trust** and `clip` must never enter a pre-send feature set again.

*Candidate bug-ledger entry: "`clip` in PF_TE_WHALE_ORDER is a post-outcome field —
it is `prior_fills + 1{matched}`. Any model using it to predict fill reads AUC 1.0."*

### 4.2 The attempt-value model: the object is not predictable

`E[net $ | attempt]`, where an unmatched attempt is worth exactly $0 — the complete economic
object, folding fill probability and fill quality into the one number the bot can act on.
Strictly pre-send features. Walk-forward by day, 19 OOS days, 4,314 attempts.

| model | OOS corr(pred, realised $) |
|---|---|
| hgb, all features | **−0.000** |
| hgb, heavy regularisation | +0.014 |
| hgb, coin removed | +0.002 |
| expanding cell mean (ask-band × tl-band) | +0.003 |

Every skip rule loses money: −$2.79 to −$9.63/day paired, and the recovery is negative in
every LOO-day window. **Clean negative, and it is the right kind: the payoff is dominated
by book accidents that no pre-send state anticipates.**

### 4.3 What *is* predictable is worth nothing

`P(match | pre-send)`, leak-free: **AUC 0.9416**, Brier 0.0830, calib 1.096. Carried by
`absest` (ablate → 0.8926), `att_idx` (→ 0.9244), `seen_ask` (→ 0.9315).

A strong model — and **worth exactly $0**, because an unmatched FAK costs nothing. There is
no decision behind it. (It would matter for a re-aim or a resize policy; neither is
answerable offline, since both change the fill set.)

### 4.4 The sweep lane is adverse selection with a lottery attached

`fl1_sweep.py`. Split by realised improvement `seen_ask − avg_px`:

| lane | n | win rate | $/day | day t | top-5 share | **ex-top-5 $/day** |
|---|---|---|---|---|---|---|
| ordinary (imp < 0.005) | 4,096 | 0.9749 | +4.65 | +1.01 | 34 % | **+3.09** |
| **sweep (imp ≥ 0.005)** | 294 | 0.8367 | +3.72 | +0.59 | **181 %** | **−3.01** |

Win rate falls monotonically with depth — this is the tell:

| improvement | n | ask | avg_px | **win rate** | net/fill |
|---|---|---|---|---|---|
| ≤0.0005 | 4,086 | 0.969 | 0.971 | 0.975 ± 0.003 | +$0.038 |
| 0.0005–0.02 | 108 | 0.936 | 0.926 | 0.972 ± 0.016 | +$0.694 |
| 0.02–0.05 | 96 | 0.913 | 0.883 | 0.854 ± 0.036 | −$0.297 |
| 0.05–0.15 | 61 | 0.888 | 0.808 | 0.787 ± 0.053 | +$0.221 |
| **0.15–2.0** | 39 | 0.864 | 0.530 | **0.513 ± 0.083** | +$0.697 |

**A deep price improvement is the market telling you the bar has moved against you.** At
the deepest bucket the "bargain" is a coin flip. The lane's positive $ is 10 fills in the
(0.4, 1.0] depth bucket — the memory's "top-5 fills are 80 % of net", reproduced exactly.

### 4.5 The fill-quality model: real, small, and pinned by concentration

`E[improvement | match]`, leak-free, with the 0.96 tick regime entered as a break:
**R² 0.042, spearman 0.16, AUC(imp ≥ 0.005) 0.742.** Top quintile: predicted 0.0150,
realised 0.0174 — genuinely calibrated. But it is the cheap band wearing a model's clothes
(top-quintile mean ask **0.919** vs 0.982 elsewhere), and:

* top quintile $+7.05/day, **day t = +0.98**, 11/19 days, **top-5 = 89 %**,
  **ex-top-5 +$0.76/day**, per-coin 3 of 7 negative (doge −1.34, eth −1.95, xrp −2.25).
* **MDE at G=19 is +$20.15/day.** The effect is a quarter of the resolution of the sample.

**Underpowered and concentrated. Not a result.** Worth re-running when the ledger is 3–4×
longer; it is the one target-2 thread that is not refuted, merely unresolved.

### 4.6 One live-only positive, which is not a model

The existing **+0.01 limit buffer** produces 783 above-ask fills worth **+$3.09/day,
day t = +1.68, 21/29 days positive, top-5 = 29 %, ex-top-5 +$2.18/day** — the least
concentrated positive number in this whole round. These are fills that would otherwise have
been $0 (the ask moved up between sight and send). **It is not offline-counterfactualable**
— a different buffer changes the fill set — so the correct statement is: the buffer is
paying, its size is unanswerable from this data, and it is the natural subject of a live
A/B, not a backtest. (Not a deploy proposal.)

---

## 5. Configs, deflation, and what would change the answer

~75 scored cells this round (ev2:3, ev4:6, ev6:12, ev7:4, ev8:1, ev9:8, ev10:8, ev11:13,
dir2:5, dir3:5, fl2:8, fl3/fl4:6). Deflation factor √(2 ln 75) = **2.94**.

* Largest raw |t| on any *veto* or *fill* candidate: **1.11**. Not close; no deflation needed.
* Largest raw |t| overall: **+2.75** (cap2x sizing) → **deflated −0.19**. Over the 8-cell
  sizing family alone (√(2 ln 8) = 2.04) it reads **+0.71**. The empirical weight-shuffle
  null (z = +3.80, p = 0/300) is the stronger evidence and the one I would defend; the
  deflation is the reason it is still filed as CONDITIONAL rather than as a finding.

**What would actually change these answers**

1. **More ledger days.** Target 1 needs ~4× the day-clusters before a 47 %-recall veto with
   a 13 % false-positive rate becomes distinguishable from zero. Target 2's fill-quality
   thread needs ~3×.
2. **A decision-time book snapshot on `evals_live`.** The 30-day set has *one* tl, no
   ladder, no trade flow, no Binance. The panel has all of that and 3 days. The single
   highest-value data change in this program is **recording the panel's feature block at
   the eval instant into `PF_TE_EVAL`** — it would turn 53,311 bars from a 16-feature
   decision record into a modellable panel, at no research cost.
3. **Nothing about model class.** Logit, shallow HGB and deep HGB agree to within 0.01 AUC
   everywhere. The ceiling is information, not capacity.

**What is closed**: the direction question (again, now with the 0.8493 figure located),
the attempt-value question, and the model-veto-on-the-fired-set question.

**What is open, in priority order**
1. **Does extra clip size fill?** It decides a +$2.72/day-vs-+$0.33/day question (§3.6a) and
   it is the single highest-value unknown this round produced. No tape we have contains
   fills at more than one clip size, so no amount of re-analysis resolves it.
2. Fill-quality sizing above the 0.96 tick break (§4.5) — underpowered, needs ~3× the days.
3. The limit-buffer size (§4.6) — not offline-counterfactualable.
