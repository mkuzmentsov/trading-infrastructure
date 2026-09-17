# HYPE — MODELS.md

Owner: ml-engineer. Companion to `DATA.md`. Scripts carry absolute paths in their headers.
**Headline is always net bps against the measured fee stack. AUC is support, never the claim.**

Fee stack used throughout (measured by the venue agent on our own `userFees`, no staking or
referral discount): **taker 4.50 bps/side, maker 1.50 bps/side — the maker number is a FEE, not
a rebate.** Round trips: taker/taker **9.00**, mixed **6.00**, maker/maker **3.00** bps.
Median spread is **0.127 bps**. The fee is ~35–70× the spread.

---

## 1. Answer first

1. **Short-horizon directional trading on HYPE is foreclosed, not merely unproven.** A
   *perfect oracle* — one that knows the sign in advance and abstains when the move won't cover
   the fee — earns **0.003 bps at 1 s, 0.060 bps at 5 s, 2.30 bps at 60 s**. No model reaches an
   oracle. Below a minute there is nothing to compete for.
2. **Our directional model works and is still worthless.** OOS AUC **0.5306** at 60 s, shuffle
   placebo at **0.4990** (exact chance), and it **passes the latency tell**. It is a real signal.
   It is worth **+0.94 bps gross** against a 9.00 bps round trip. Every one of 36 configs is
   negative; best real cell **−9.15 bps, t = −3.84**. This is a clean, well-powered negative.
3. **⭐ The carry is the real finding, and it survives every cut.** A delta-hedged
   **long HL spot (@107 HYPE/USDC) / short HL perp** position, priced with funding *and* basis
   mark-to-market *and* 18 bps of round-trip taker fees, nets **+7.3 to +7.7 %/yr in the current
   regime** (t = +7.8 to +9.7), **0 of 21 months negative**, all leave-one-month-out positive.
   Both legs quote a **0.12 bps spread** with $45–64 k of ten-level depth on one venue.

---

## 2. ⭐ The ceiling test — run before believing any directional model

`research-hype/ceiling.py`. Fee already deducted; oracle may abstain.

```
   h  sd(mid) bps  E|mid| bps | oracle t/t   mixed  m/m | P(|mv|>9bps)  coin-flip
  1s        1.28        0.61  |     0.003   0.009  0.040|       0.2%      -9.29
  5s        3.05        1.82  |     0.060   0.145  0.423|       1.9%      -9.30
 30s        7.93        5.31  |     0.964   1.632  2.847|      17.4%      -9.30
 60s       11.45        7.82  |     2.299   3.404  5.079|      30.8%      -9.30
300s       25.41       17.76  |    10.252  12.306 14.716|      63.7%      -9.36
```

At 60 s the oracle trades 29.5 % of instants, so ~**7.8 bps per trade**. A model capturing 12 %
of clairvoyance — which would be exceptional — earns ~0.9 bps, and needs 9.00. That is exactly
what we measured (§3). The numbers agree, which is how you know neither is a bug.

Concentration (60 s oracle): top 1 % of instants = 19.4 % of gross, top 5 % = 51.8 %.
Per-day oracle mean 0.94 / 2.19 / 2.32 / 2.91 / 2.28 bps — **the ceiling is not one day.**

---

## 3. Directional control — clean negative

`research-hype/models.py` → `research-hype/models_results.csv`.
Expanding-window, **split by day, forward in time**. Grid 1 s; effective n is non-overlapping
horizons: **5,907 at 60 s, 1,181 at 300 s**, not 354,457 rows. Trades are de-overlapped before
scoring. SEs clustered by day. 59 features; horizons {60, 300} s × models {GB, LR} × thresholds
{0.50, 0.40, 0.30} = **36 configs counted**.

| h | model | variant | AUC | n | net bps | SE(day) | t |
|---|---|---|---|---|---|---|---|
| 60 s | LR | **REAL** | **0.5306** | 1521 | **−8.06** | 0.211 | −38.3 |
| 60 s | LR | placebo-shuffle | 0.4990 | 30 | −14.24 | 30.8 | −0.46 |
| 60 s | GB | **REAL** | 0.5200 | 2096 | −8.51 | 0.322 | −26.4 |
| 60 s | GB | placebo-shuffle | 0.5010 | — | — | — | — |
| 300 s | GB | **REAL** | 0.5019 | 606 | −9.48 | 0.176 | −53.9 |

**Best real cell across all 36: −9.15 bps, t = −3.84.** Bonferroni p = 1.000. Not one cell is
positive. Best placebo t in the identical pipeline: −0.28.

**The pipeline passes its own leakage test.** Label-shuffle lands at AUC 0.4990 / 0.5010 —
*exactly* chance. If the harness leaked, the shuffle would score above 0.50. It does not.

> ⚠️ Note on the side-flip placebo: for a symmetric classifier, flipping the labels flips the
> model and flipping the prediction back cancels — LR's flip placebo reproduces REAL exactly.
> It is **degenerate for symmetric models** and only the shuffle placebo is informative there.
> I am flagging this rather than quietly reporting the flip row as a passed control.

### Latency tell — passed
`research-hype/latencytell.py`. Degrade execution; an honest edge decays, a hindsight bug improves.

```
    lag     AUC   gross bps/trade   net bps/trade     n
     0ms  0.5306            0.938          -8.062  1521
   500ms  0.5242            0.282          -8.718  1149
  2000ms  0.5176            0.522          -8.478   808
```

AUC falls **monotonically** with lag. Nothing here is reading the future. The signal is real,
decays with latency as a genuine microstructure signal should — and is ~10× too small to pay.

### Power — this negative is meaningful, not an underpowered shrug
With fwd-60 s sd = 11.45 bps, a selected set of *n* independent trades has SE = 11.45/√n.
At n = 100 that is 1.15 bps, so a genuinely tradeable **+9 bps edge would show at t ≈ 7.8**.
We are nowhere near the detection limit: we can see effects far smaller than the ones we'd need.
**A tradeable taker edge at these horizons does not exist in this tape.**

The honest caveat is the reverse one: **5 days is 5 clustered observations.** Treat the *magnitude*
as approximate. But the sign and order of magnitude are safe, and they agree with the oracle
ceiling computed independently.

---

## 4. ⭐ The funding carry — the one thing that works

### 4a. Funding itself (`research-hype/carry.py`), 15,634 hourly points, 21 months, native HL

* **P(rate > 0) = 93.4 % of hours**; pinned at the **+0.00125 %/hr structural floor in 66.0 %**.
  That floor share matters: most of this is *mechanical*, not a crowded-long premium that can
  simply unwind.
* mean **+20.83 %/yr**, median hour **+10.95 %/yr**. A continuous short collected **37.2 %** of
  notional over 651 days.
* **All 22 months positive** (+5.08 % … +118.79 %). **All 22 leave-one-month-out values positive**;
  worst (drop 2024-12) **+16.66 %**.
* **Not a spike effect**: top 30 days = 29.7 % of all funding; strip them entirely and the
  remainder still pays **+15.3 %/yr**. Median day annualises to +11.0 %.
* Day-clustered **t = +18.0** on 652 days. Negative-funding days: **26/652 = 4.0 %**, mean −1.91 bps.

⚠️ **The carry is compressing.** 2024-12 paid +119 %/yr; 2026 months pay +5 – 14 %/yr.
**Do not forecast with the full-sample mean.**

### 4b. The hedged structure, honestly priced (`research-hype/basis.py`)

A naked short collects ~21 %/yr of funding and pays the **+105 %/yr** drift → ruin. The trade is
only interesting **delta-hedged**, and HL lists the hedge leg itself:

| leg | instrument | spread | 10-level depth | history |
|---|---|---|---|---|
| long | **@107 HYPE/USDC spot** | **0.12 bps** | $64.3 k bid / $55.6 k ask | 658 daily, from 2024-11-29 |
| short | **HYPE perp** | **0.12 bps** | $43.4 k / $45.9 k | from 2024-12-05 |

Same venue, same collateral. Basis (perp/spot − 1): mean **+2.90 bps**, median +1.69, sd 10.47,
P(perp > spot) 58.9 %. **Daily basis change sd = 11.38 bps — ~4× the daily carry of 2.6 bps.**
Basis risk is the real risk here and funding-only accounting flatters the trade.

P&L convention: long spot S₀ / short perp P₀ → **PnL = −(basis₁ − basis₀) + funding − fees.**

**Overlapping H-day holds, funding AND basis AND 18 bps round-trip taker fees:**

| hold | n_indep | funding | basis drag | fees | **NET** | %/yr | t | P(win) | Sharpe/hold |
|---|---|---|---|---|---|---|---|---|---|
| 7 d | 93 | +39.1 | +0.4 | −18.0 | **+21.5** | +11.2 % | +4.04 | 68.5 % | 0.44 |
| 30 d | 21 | +153.6 | +1.0 | −18.0 | **+136.5** | +16.6 % | +3.21 | 99.8 % | 0.98 |
| 90 d | 7 | +409.7 | +2.3 | −18.0 | **+394.0** | +16.0 % | +2.09 | 100 % | 1.56 |

Basis drag averages ≈ **0** — the basis is stationary, so it adds variance, not a trend cost.
30-day: **0 of 21 months negative**, worst month +21.7 bps, all LOO positive (worst +113.4).

### 4c. ⚠️ The number to actually use

Full-sample +16.6 %/yr is inflated by the launch era. Restricting forward:

| window | n_indep | 30-d net | %/yr | t | P(win) |
|---|---|---|---|---|---|
| full sample | 21 | +136.5 bps | +16.6 % | +3.21 | 99.8 % |
| ex-launch (from 2025-02) | 19 | +100.7 bps | +12.3 % | +6.83 | 99.8 % |
| **last 12 months** | 12 | **+63.4 bps** | **+7.7 %** | **+7.82** | 99.7 % |
| **last 6 months** | 6 | **+59.9 bps** | **+7.3 %** | **+9.66** | 100 % |

**Plan on ~7–8 %/yr net, not 16.6 %.** The t-statistic *rises* as the window shortens because the
launch era's variance drops out — the recent regime is lower-yielding and much steadier.

### 4d. What I have NOT established — read before sizing
* **Spot-leg fee assumed equal to perp taker (4.50 bps).** HL spot may sit on a different
  schedule. One `userFees` check settles it; at 18 bps round trip on a 7 %/yr carry, a wrong
  spot fee moves break-even by days. **Confirm before sizing.**
* **Break-even hold is 6.6–7.0 days** at current funding. This is a *hold*, not a scalp; the
  fee is paid once and amortised. Anything that forces early exit destroys it.
* **Capital efficiency and liquidation** are unmodelled: the structure needs capital on both
  legs and the short perp can be liquidated on an up-move even though the pair is hedged.
  That is the portfolio agent's call, not mine.
* **Maker entry would cut the round trip from 18 → 6 bps** and roughly halve break-even. I have
  **not** modelled it: a resting order's fill is adversely selected and this program has measured
  that cost before (the maker resting-order wall: quoted 1.5 c below mid, fills 0.47 c *above*).
  **Needs a queue sim before anyone counts the saving.** Do not assume it.
* **n_indep = 6** in the last-6-months window. The recent regime is steady but thinly sampled.

---

## 4e. ⛔ Does OI predict funding? No — and the way it failed is a warning

The carry's main forward risk is further funding compression, so I tested whether **open
interest** (21 months hourly, from the Bybit leg) predicts funding. `research-hype/oicheck.py`.

The naive version looked spectacular — day-clustered t of **+7.3 to +7.8** in every cell, with
an i.i.d.-shuffle placebo at |t| < 1.8. **All of it was an artefact.** Two defects, both inflating t:

1. **Forward windows of 168–720 h, standard errors clustered by DAY.** Day clusters do nothing
   about 30-day overlap — consecutive rows share ~719/720 of their target. Effective n is ~21
   blocks, not 15,631 rows.
2. **An i.i.d.-shuffle placebo destroys the predictor's autocorrelation.** Against an
   autocorrelated target that null is far too easy to beat. The right null is a **circular
   shift**, which preserves autocorrelation.

Redone with non-overlapping blocks and a 399-fold circular-shift null:

| predictor | H | blocks | slope | naive t | **circular-shift p** | verdict |
|---|---|---|---|---|---|---|
| ΔOI 168 h | 720 h | 21 | +0.0033 | +7.32 | **0.276** | dead |
| ΔOI 168 h | 168 h | 92 | +0.0050 | +7.77 | **0.020** | survives alone, dies at 9 cells |
| ΔOI 24 h | 720 h | 22 | +0.0051 | +7.35 | **0.596** | dead |

**t = +7.32 corresponds to p = 0.276.** A ~1.1-sigma result wearing a 7-sigma costume. One cell
of nine survives at p = 0.02; Bonferroni over the 9 cells tried gives 0.18. **OI does not predict
funding.** Clean negative.

This mattered economically — the slope implies ~11 %/yr of APR per 50 % OI move — which is
precisely why it needed the honest test rather than the flattering one.

> ⚠️ **Carried warning for anyone else touching this funding data:** the program's known folklore
> is "the permutation null reads t ≈ 2–3 on noise." On *overlapping* funding windows it reads
> **t ≈ 7**. Any predictive claim on this series needs non-overlapping blocks **and** an
> autocorrelation-preserving null. Day-clustering is not sufficient when the horizon exceeds a day.

**Does this undermine §4's carry result? No, and here is why.** The carry is not a fitted
relationship with a predictor to shuffle — funding is a directly observed cash flow that is
actually paid. Its t was already computed on **non-overlapping** blocks (`net[::Hd]`), not on the
overlapping series. And the load-bearing evidence is structural rather than statistical: **66 % of
hours sit at exactly the +0.00125 %/hr floor**, and 22 of 22 months are positive. That is a
mechanical feature of the venue, not an estimated coefficient.

The honest residual caveat: monthly blocks are themselves persistent, so the t = +3.21 is
optimistic as a strict significance claim. **Lean on the floor share and the month-by-month
consistency, not on the t-statistic.**

---

## 5. Configs tried, for deflation

36 directional cells (2 horizons × 2 models × 3 thresholds × 3 label variants), 3 latency-tell
cells, 5 oracle horizons × 3 fee regimes, 4 carry windows × 3 hold lengths. Best directional cell
does not survive Bonferroni and is negative anyway. **The carry result was not selected from a
search** — it is a single pre-specified structure, reported at every window and every hold length
I computed, including the ones that flatter it least.

---

## 6. What I would do next, in order

1. **Confirm the HL spot taker fee** (one `userFees` call). Everything in §4 hinges on it.
2. **Measure the spot leg on the tick tape** — we record perp only. Add @107 to `hrecSubs` and
   the basis becomes observable at tick resolution instead of daily closes.
3. **Queue sim for maker entry on both legs.** 18 → 6 bps is the single largest available
   improvement, and it is exactly the kind of saving this program has been burned assuming.
4. **Lead-lag HL vs Bybit** — now possible (DATA.md §3), expected to be sub-second and
   fee-swamped, but it should be measured rather than assumed away.
5. **Do not spend more effort on short-horizon direction.** §2 closes it arithmetically.

---

## 7. Reproduce

```
python3 research-hype/hlhist.py                  # HL candles + funding -> hl-hist/
python3 research-hype/hldeep.py                  # retry-on-empty deep pager
python3 research-hype/bybithist.py               # 22-month 1m proxy history (Bybit)
python3 research-hype/tapeaudit.py               # tape quality / clocks / side convention
python3 research-hype/panel_tick.py  --step 1    # tick panel (add --lag-ms for the latency tell)
python3 research-hype/panel_hist.py  --ivs 1d,4h # history panel
python3 research-hype/ceiling.py                 # perfect-oracle ceiling   <- run this first
python3 research-hype/models.py                  # directional control + placebos
python3 research-hype/latencytell.py             # latency tell
python3 research-hype/carry.py                   # funding robustness
python3 research-hype/basis.py                   # hedged carry, honestly priced
```
