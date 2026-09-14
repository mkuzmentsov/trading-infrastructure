# Two-agent research program on the mrec+Binance tape — CLOSED
**2026-09-14/15. `quant-analyst` + `ml-engineer`. Nothing deployed; no live-fleet change proposed.**

User asked for: build feature datasets → find features that make sense → train models for several
strategy archetypes (named "vacuum" and "divergence/buy-cheap-expect-reversal", plus whatever the
agents invented) → backtest with execution realism.

**Result: no new strategy. The program stopped on its own pre-registered kill criteria.** The
durable output is a bound, a substrate, and seven corrections to previously committed claims.

## 0. Two facts that collapsed the idea space before any modelling

* **The one-book identity collapses the direction 2×2 to one cell.** `UP ask ≡ 1 − DOWN bid`, so
  buying the dog *is* selling the favourite. The four cells are two pairs of the same trade and one
  of each pair was already refuted on 376k obs. **There is one tradeable primitive: take the
  favourite below fair.** The user's "divergence, buy a side cheap and expect reversal" **is** the
  refuted cell, by identity — demoted to a control, not tested as a candidate.
* **The fee is quadratic** (`0.07·p·(1−p)`): 1.750 c/sh at p=0.50, **0.069 at p=0.99**. That is the
  mechanical reason all 47 maker cells and every mid-band idea died and only the extreme-price lane
  ever had room.

## 1. A1 — dislocation supply census: SUPPLY PASSES, ECONOMICS FAIL

Quote-based framing (⚠️ superseded, see below): $2,227/day contestable notional, 19.8% already
vacmaker-eligible — all three supply kills passed. Then, on realised outcomes with the fee charged:
466 prints / 173 bars / $6,681 → **+2.89% ROI at bar-clustered t = 0.35**, **−$136 ex-09-14**,
**−$300 ex-btc**, **top-5 prints −$523** against a +$193 total, and **px ≥ 0.55 = −5.28%**.

⭐ **Split on the recon gate: eligible +37.65%, not eligible −5.67%, recon-decisive-but-opposite
−36.41%.** ⇒ **The gate is the edge; the sweep is only the delivery mechanism.** An oracle-free
harvester harvests the −5.67% slice. **A2 dead at its premise; A6 arrival model cancelled unbuilt.**

⭐⭐ **Quote-free re-cut (after the ml-engineer showed 17.8% of fills land ABOVE the displayed ask
and 14.5% below, so any quote-based census is wrong in both directions):** every late-window BUY
print, bucketed only by the price actually paid — **33,935 prints / 1,075 bars / $697,693 of real
stake / −1.00% ROI**, negative on all three days and **every** leave-one-coin-out fold (−0.85% to
−1.12%). The **0.98-1.00 band is 71% of the entire stake ($497,250) and prices to −0.00%**.
**This is the headline to carry**; the $2,227/day figure is quote-dependent and is NOT settled.

## 2. A3b — the mid-bar family, CLOSED BY ARITHMETIC

> mid-bar miscalibration **1-3 c/sh** vs half-spread **1.0-2.2 c/sh** + fee **0.3-1.75 c/sh**.
> Cost exceeds mispricing **in every band at every τ**. The maker mirror is already closed at
> **−4.6 c/sh** of terminal adverse selection, and by the one-book identity there is no third way
> to express it.

The mispricing is **real** — 28 of 32 (τ × price) cells have |δ| > fee, 17 with |t| > 2, sign
structure consistent at every τ from 15s to 300s (unlikely side over-priced, likely side under-).
It is the documented dog premium, re-derived on a third instrument. **On the ask it vanishes**:
row-mean, bar-clustered SE, τ ≥ 60s gives −2.95 / −4.47 / −3.91 / −3.01 c/sh across
[0,0.20)…[0.50,0.65), all |t| > 6. 4 of 21 grid cells positive; the best fails three pre-registered
conditions simultaneously.

**This is a bound, not a variant list** — which is why it outranks refutation-by-exhaustion.

## 3. A4 / A7 — closed

**A4 cross-duration dominance**: premise verified *exactly* (15m bars are `ws%300==0, end%300==0`,
so a 15m and its final 5m share a TWAP endpoint; 181/181 agreement) — but the bound never binds.
Median `gap` **−0.320**: the pair costs **$1.32 for a ≥$1.00 payoff**. Tape confirmation is a
bug-#32 artefact (both-legs rate 14.8% → **59.0%** as the window goes 0.2s → 15s; 11.5% under a
0.5s round trip; **0.0%** on eth once both legs must print ≥20 shares).
**A7 openlag**: `avgask` **0.760 / 0.722** vs a 0.58 reopen threshold. Stays closed.

## 4. ⭐ What the program actually produced

**`PF_TE_EVAL` — 53,311 bars over 30 days.** The bot logs a decision record at tl≈28 for *every bar
it sees, fired or not*: **12.4× the panel's bars, 10× its day-clusters**, MDE on `E[y−mid]` falling
**0.76 pp → 0.22 pp**. ⚠️ **But its `ask` is recorded on the estimator's own side** (`side = "UP" if
tw1 > 0`), so **every row is oracle-conditioned** — it measures the recon's edge at a displayed
price, not market calibration. Cut naively it returns **+17.9 c/sh, t_day +2.70, 7/7 coins**, which
is **not a finding**: it is the recon-eligible cheap-ask cell, the same object §38 rejected as
buy-the-dip. Genuinely valuable for oracle-conditioned questions only.

**Power, the number that governed the round.** Fleet $8.37/day against a day sd of **$35.93** ⇒
**t = 1.25 on its own 29-day record — the fleet cannot distinguish itself from zero.** Detecting
+$4/day needs ~635 days. 3-day panel MDE is **+0.73 c/sh** against a *perfect-oracle* ceiling of
+5.33 — only effects ≥14% of perfect foresight are resolvable.

**Concentration**: top-1 fill **31%** of net, top-5 80%, top-10 **108%**. The sample size that
matters is 5.

## 5. Corrections to previously committed claims

| claim | status |
|---|---|
| `binance/panel.py` row picker | ⛔ **bug #46** — ~80 ms look-ahead (`tl` counts DOWN, so smaller `tl` is later). Fixed. |
| bug #45 "panel is quieter and **better**" | ⛔ backwards — 95.90% vs **97.46%** at tl 30. Fidelity argument stands. |
| "+0.456 c/sh of estimator quality" | ⛔ **below** the 3-day MDE of +0.73. Unconfirmable either way. |
| "reconstruction fails the live gate on 28%" | ⛔ **RETIRED** — pre-bug-#45 estimator; corrected one reproduces the bot at **corr 0.9937, median |Δ| 0.003 bps**. |
| "≥0.98 deep sweep is the business" | ⚠️ **conditional on the recon gate** — does NOT support sizing into sweeps. |
| "30 days × 7 coins" of ledger | ⚠️ eth/xrp have not fired since **09-09**, hype since 09-13. An `ls` check does not reveal it. |
| 3 interpolated fill-rate rows | ⭐ **now measured** on 8,496 attempts: 0.173 / 0.220 / 0.512 / **0.749**. |

## 6. Two methodology traps worth more than the archetypes

⚠️ **The bar-mean/row-mean weighting trap.** On ask [0.65,0.80) a **bar-mean** statistic reads
**+3.18 c/sh, t=+5.78** — the *opposite sign* to the row mean (−0.862, t=−1.23). Bar-mean gives a
bar that touched the band for one violent second the same weight as one that sat there 200 seconds,
and **the transitional seconds are the mispriced ones**. The tradeable object is "the ask is in this
band *now*" ⇒ **estimate on the row mean, put the dependence in the SE.**

⚠️ **Gaussian inversion on a fat-tailed residual.** A3b's implied/realised first read **0.66-0.68**
(an apparent vol mispricing). The residual is strongly fat-tailed (sd/robust **1.61-1.84**) so the
inversion lands on the robust scale of the bulk. Against the right yardstick it is **1.07-1.25 and
flat across the whole term structure**. No vol trade. Caught by the agent in its own result.

## 7. Verdict

**Stop the strategy hunt.** Seven archetypes designed, five tested, all closed; the two named by the
user are closed by identity and by arithmetic respectively. Per the program-level kill, no eighth
archetype was invented.

⚠️ Every number above is measured at the **displayed** ask, and only **25-72%** of displayed asks are
takeable — so the true taker economics are **worse** than everything stated. The closure is
conservative.

Artefacts: `research/{PROGRAM,DATASET,LEDGER,A1-census,A3b-vol,A4-crossduration,A7-openlag}.md`,
`research/data/{panel,fills,delays,bars_live,evals_live}.parquet`, `research/harness/hx.py`.
