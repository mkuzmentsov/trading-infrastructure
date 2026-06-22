# Experiments backlog

Running log of changes to the engine/strategy and their measured effect on the
engine-based backtests, so every change is judged against a fixed baseline (principle #4:
beat the baseline OOS, after costs). Raw captured outputs live in `experiments/<label>/`.

**What's measured here:** the *engine* path only (`atb backtest` / `atb validate`), because that
is what the regime gate, risk gate, and arbitration layer actually touch. The vectorized
`xsec` / `tstrend` panel backtests bypass the engine and are tracked separately.

**How to reproduce a row:**
```
PYTHONPATH=src python3 -m algo_trading_bot.cli backtest --config configs/<cfg>.toml
PYTHONPATH=src python3 -m algo_trading_bot.cli validate --config configs/<cfg>.toml
```

Metric legend: *Sharpe(full)* = full-sample backtest Sharpe; *OOS Sharpe* = test-segment Sharpe
after in-sample tuning; *DSR* = Deflated Sharpe P[true SR>0] (gate needs ≥0.95); *PBO* =
prob. of backtest overfitting via CSCV (gate needs ≤0.30); *Gate* = approve-for-live verdict.

---

## Baseline — commit `b527ff7` (2026-06-21)

Regime gate is a **passthrough** (`TrendRangeDetector.detect` → `UNKNOWN`), so all trend
forecasts pass ungated. This is the reference every later change is compared against.
Raw: `experiments/baseline_b527ff7/`.

### `backtest` (full sample)

| Config | Venue/interval | Bars | Sharpe(full) | Total ret | maxDD | Trades | Turnover |
|--------|----------------|------|--------------|-----------|-------|--------|----------|
| btc_1d | hyperliquid 1d | 3228 (2017→2026) | **0.68** | +22.2% | −5.1% | 1713 | 10.7× |
| btc_1h | hyperliquid 1h | 21577 (2024→2026) | **0.24** | +2.0% | −5.0% | 11398 | 89.2× |

### `validate` (in-sample tune → OOS test + gate)

| Config | Best params | Train Sharpe | OOS Sharpe | OOS maxDD | DSR | PBO | Gate |
|--------|-------------|--------------|------------|-----------|-----|-----|------|
| btc_1d | ema 10/60 | 1.06 | **0.62** | −3.1% | 0.732 | 0.21 | REJECTED (DSR<0.95) |
| btc_1h | ema 20/120 | 0.54 | **−0.12** | −5.4% | 0.398 | 0.70 | REJECTED (Sharpe<0, PBO>0.3) |

Notes: btc_1d is the project's promising-but-underpowered result — passes overfitting (PBO 0.21)
but fails significance (DSR 0.732). btc_1h has no OOS edge (Sharpe −0.12, PBO 0.70). buy&hold OOS
Sharpe: btc_1d 1.04, btc_1h −1.04 (the 1d window was a BTC bull; the 1h window was not).

---

## Change log

Each entry: what changed, why, the same metric rows after the change, and the **verdict**
(improved / disimproved / neutral) vs the row directly above it.

### #1 — Regime classifier (2026-06-22)
Replaced the `TrendRangeDetector` passthrough with a causal classifier: Kaufman **efficiency
ratio** (trend strength) + **vol percentile** (high-vol) + EMA-spread sign (direction), fixed
a-priori thresholds (ER≥0.30 trend, vol_pct≥0.90 high-vol — NOT tuned). The gate zeroes the
FOUNDATION trend forecast in RANGE and HIGH_VOL. Added a per-regime metric breakdown to the
report and 6 unit tests (`test_regime.py`). Raw: `experiments/regime_classifier/`.

**`backtest` (full sample)**

| Config | Sharpe(full) | Δ | Total ret | maxDD | Trades | Turnover | skew |
|--------|--------------|---|-----------|-------|--------|----------|------|
| btc_1d | 0.63 | −0.05 | +13.1% (was +22.2%) | −4.4% (was −5.1%) | 816 (was 1713) | 21.6× (was 10.7×) | +1.82 (was +0.36) |
| btc_1h | **−3.20** | **−3.44** | −15.0% (was +2.0%) | −16.3% (was −5.0%) | 4585 (was 11398) | 155× (was 89×) | +1.31 |

**`validate` (OOS + gate)**

| Config | OOS Sharpe | Δ | DSR | Δ | PBO | Δ | Gate |
|--------|------------|---|-----|---|-----|---|------|
| btc_1d | 0.63 | +0.01 | 0.652 | −0.080 | 0.13 | −0.08 | REJECTED |
| btc_1h | **−3.75** | **−3.63** | 0.000 | −0.398 | 0.46 | −0.24 | REJECTED |

**Per-regime breakdown (the real insight) — annualized Sharpe by detected regime:**

| | trend_up | trend_down | range | high_vol |
|---|---|---|---|---|
| btc_1d | **+3.72** (+20.4%) | **+1.23** (+4.1%) | −1.64 (−8.6%) | −0.33 (−1.3%) |
| btc_1h | **+5.66** (+6.3%) | **+3.80** (+3.2%) | **−12.86** (−21.9%) | −1.17 (−0.8%) |

**Verdict: DISIMPROVED on the headline — but the experiment is a success at *diagnosis*.**
- The regime **signal is real and strong**: trends carry essentially all the PnL (Sharpe +3.7 to
  +5.7), ranges and high-vol bleed. The classifier correctly identifies where the trend edge lives.
- But the **hard on/off gate wiring is counterproductive**, badly so at 1h. Forcing the book
  flat-then-reopen on every regime flip whipsaws it in choppy markets: turnover ↑ (89→155×) on
  *fewer but larger* round-trip trades, and the "range" bucket bleeds −21.9% — far worse than
  ungated. At 1d (flips are rarer) it's mild: maxDD ↓ (−5.1→−4.4%), skew way up (+0.36→+1.82),
  PBO ↓ (0.21→0.13, less overfit), but OOS Sharpe flat (0.62→0.63) and **DSR actually dropped**
  (0.732→0.652) — it did NOT fix the significance problem; it traded headline edge for a cleaner
  risk shape.
- Mechanism: rapid regime **flicker** around the ER/EMA boundary → churn. The signal is good; the
  execution of it (hard zero, no persistence) is the problem.

**Next step (#2 candidate): debounce/soften the gate** — either regime **hysteresis** (require N
consecutive bars before switching) or **soft gating** (scale the forecast by ER confidence instead
of a 0/1 switch), so the book isn't flattened-and-reopened on every flicker. Re-test against this
same baseline. The per-regime table predicts a real win IS available if the churn is removed.

### #2 — Gate modes: hysteresis vs soft (2026-06-22)
Added a configurable gate `mode` (`config.RegimeConfig.mode`, also `--regime-mode`):
**hysteresis** debounces the regime label (switch only after `persist=3` consecutive bars);
**soft** drops the 0/1 switch entirely and scales the FOUNDATION forecast by a continuous
ER-derived weight (ramp 0.15→0.45, cut in the top vol bucket). Raw: `experiments/regime_gate_modes/`.

**btc_1d** (the config where a trend edge exists — vs the #1 hard gate and the no-gate baseline):

| Variant | full Sharpe | OOS Sharpe | DSR | PBO | Gate |
|---------|-------------|------------|-----|-----|------|
| baseline (no gate) | 0.68 | 0.62 | 0.732 | 0.21 | REJECTED |
| hard (#1) | 0.63 | 0.63 | 0.652 | 0.13 | REJECTED |
| hysteresis | 0.78 | 0.51 | 0.716 | **0.58** | REJECTED (PBO) |
| **soft** ✅ | **0.80** | **0.78** | **0.788** | 0.22 | REJECTED (DSR) |

**btc_1h** (the 1h trend has no underlying edge — baseline OOS −0.12):

| Variant | full Sharpe | OOS Sharpe | DSR | PBO |
|---------|-------------|------------|-----|-----|
| baseline (no gate) | 0.24 | −0.12 | 0.40 | 0.70 |
| hard (#1) | −3.20 | −3.75 | 0.00 | 0.46 |
| hysteresis | −0.93 | −1.48 | 0.05 | 0.69 |
| soft | −2.76 | −3.00 | 0.00 | 0.26 |

**Verdict: IMPROVED — `soft` is the winner and is now the default (`RegimeConfig.mode="soft"`).**
- On btc_1d, soft is the **first genuine improvement** in the whole chain: OOS Sharpe **0.62→0.78**
  (+0.16 vs baseline, +0.15 vs hard), full Sharpe **0.68→0.80**, DSR **0.732→0.788** (best yet, and
  moving toward the 0.95 gate), PBO 0.22 (fine). It keeps continuous trend exposure and de-weights
  chop *smoothly* — no flatten/reopen churn. Still gate-REJECTED on DSR (0.788<0.95), but materially
  closer; the daily-data statistical-power problem remains the binding constraint.
- **Hysteresis is not it**: full Sharpe looks good (0.78) but OOS drops to 0.51 and PBO blows out to
  **0.58** — debouncing adds a lagged discrete switch that overfits. Soft ≫ hysteresis.
- **At 1h, no gate variant helps** (all OOS < −1): the 1h trend strategy has no edge to protect, and
  a regime gate can't manufacture one — soft just re-weights noise. This is a *strategy* problem, not
  a gate problem. Honest cost of making soft the global default: the (already-rejected, never-
  deployable) 1h book gets worse; the deployable 1d book gets clearly better.

**Net of #1+#2:** the regime gate, done as continuous soft weighting, lifts the daily trend's OOS
Sharpe 0.62→0.78 and DSR 0.732→0.788 without raising overfitting — a real, if still sub-gate, gain.
Remaining lever for significance is statistical power (more assets / longer history), not the gate.

---

### #3 — Correlation-aware sizing for the multi-asset TSM (2026-06-22)
The roadmap follow-up to the last negative result: replace the √N independence assumption in the
managed-futures book (`ts_trend_weights`: per-asset target = `target_vol/√N`) with a portfolio
vol-target from a **shrunk covariance matrix** (`correlation_aware_weights`: scale the whole book
by `target_vol/√(wᵀΣw)`, Σ = constant-correlation-shrunk sample covariance). New `--sizing corr`
flag + `TSTrendConfig`. Engine path unaffected (this is the vectorized `tstrend` panel).
Command: `atb tstrend --config configs/tstrend_1d.toml --sizing corr`. Raw: `experiments/tstrend_corr_sizing/`.

| Sizing | OOS Sharpe | DSR | PBO | vol | maxDD | CAGR |
|--------|------------|-----|-----|-----|-------|------|
| **√N (baseline, default)** | 0.35 | **0.624** | **0.12** | 15.7% | −15.9% | +4.6% |
| corr (sh0.3, cw100) | 0.42 | 0.594 | 0.71 | 21.2% | −21.9% | +7.0% |
| corr (sh0.5, cw252) | 0.37 | 0.526 | 0.62 | 20.0% | −22.9% | +5.8% |
| corr (sh0.7, cw252) | 0.37 | 0.521 | 0.61 | 20.2% | −23.2% | +5.7% |

**Verdict: DISIMPROVED — correlation-aware sizing NOT adopted (default stays `sqrtn`).**
- It does what it's designed to: correctly recognizes the alts' high correlation and sizes the book
  to actually hit the 20% vol target (√N ran *under* at 15.7%), lifting raw OOS Sharpe (0.35→0.42)
  and CAGR (+4.6→+7.0%). The economic test confirms a correlated pair de-levers vs an independent one.
- **But it is worse on every metric that matters for the gate**, robustly across shrinkage/window:
  **PBO 0.12 → 0.61–0.71** (badly overfit), **DSR 0.624 → 0.52–0.59** (significance *down*), maxDD
  −16% → −22/23%. Higher shrinkage/longer window doesn't rescue it → fundamental, not estimation noise.
- Mechanism: covariance-based sizing lets the (fast,slow) grid exploit in-sample covariance structure
  (train Sharpe 0.74 → 1.17) that doesn't generalize — the "dumber" √N rule is more robust OOS exactly
  because it doesn't fit the data. Confirms the recurring theme: more fitting → worse deflated/PBO.
- Deeper point (matches the roadmap): correlation-aware sizing can't manufacture diversification that
  isn't there. Crypto alts lack independent bets; sizing them correctly (hit vol target) just takes
  more correlated risk → more return, more DD, more overfit — not more *significance*. The lever for
  the daily TSM is genuinely **uncorrelated markets / longer history**, not a smarter risk model on
  the same correlated crypto basket. Corr sizing kept as an option (`--sizing corr`) for when a truly
  diversified universe exists.

---

### #4 — Add uncorrelated markets (macro) to the TSM (2026-06-22)
The lever #3 pointed to: bring in genuinely uncorrelated assets so the diversification premium can
actually appear. Fetched 8 macro daily proxies from Yahoo (SPY, QQQ, TLT, IEF, GLD, DBC, USO, UUP =
US/intl equities, long/mid bonds, gold, broad commodities, oil, US dollar) via
`scripts/build_mixed_universe.py`, aligned onto a **business-day** calendar (no weekend zero-returns),
written under venue `mixed`. **Premise confirmed:** avg pairwise corr WITHIN crypto = **+0.56**, avg
corr crypto-vs-macro = **+0.02** — genuinely uncorrelated. Raw: `experiments/uncorrelated_markets/`.

| Universe (business-day cal) | best window | OOS Sharpe | DSR | PBO | maxDD | EW OOS Sharpe |
|------------------------------|-------------|------------|-----|-----|-------|---------------|
| crypto (16) | 10/50 | **0.38** | **0.609** | 0.04 | −12.4% | 0.79 |
| macro (8) | 20/200 | 0.34 | 0.623 | 0.42 | −10.8% | 1.68 |
| **mixed (24) √N** | 10/100 | **0.16** | **0.512** | 0.29 | −16.1% | 0.91 |
| mixed (24) corr sizing | 10/100 | 0.26 | 0.546 | 0.32 | −23.1% | 0.91 |

**Verdict: DISIMPROVED — uncorrelated markets did NOT lift the DSR; mixing actually HURT.**
Mixed DSR 0.512 < crypto-only 0.609, and mixed OOS Sharpe 0.16 is **below BOTH** components (crypto
0.38, macro 0.34) — the opposite of a diversification premium (two uncorrelated ~0.35-Sharpe books
*should* combine toward ~0.5). Three diagnosed causes:
1. **Single global trend window (the smoking gun).** Crypto's best (fast,slow) is **10/50** (crypto
   trends fast); macro's is **20/200** (bonds/gold trend slow). The TSM forces ONE window on the whole
   universe → mixed picks **10/100**, a compromise that fits neither → it underperforms both sleeves.
2. **√N mis-sizes the heterogeneous book** (16 correlated crypto + 8 uncorrelated macro ≠ 24 independent
   bets). Corr sizing (#3) recovers some — mixed Sharpe 0.16→0.26 — its first sign of value, on the
   universe it was designed for — but still below crypto-only with worse DD (−23%) and PBO.
3. **Macro trend had a weak OOS window** (2023–26 was tough for CTAs): macro buy-&-hold OOS Sharpe 1.68
   but *trend* on macro only 0.34, and overfit (PBO 0.42, 8 names). Uncorrelated *noise* dilutes; only
   uncorrelated *edge* diversifies.

**Conclusion:** uncorrelated markets are **necessary but not sufficient**. Bolting macro onto a
single-window, √N-sized crypto TSM makes it worse. The diversification premium needs **per-asset-class
trend windows** (let crypto run fast, macro run slow) and **cluster-aware sizing** — not just more data.
That is the indicated next experiment (#5): per-sleeve trend horizons + corr/cluster sizing on the
mixed universe. Data + configs (`tstrend_crypto/macro/mixed`, venue `mixed`) are in place to run it.

---

### #5 — Sleeved TSM: per-sleeve windows + cluster sizing (2026-06-22) ⭐
Fix the two causes #4 diagnosed. Each SLEEVE (crypto / macro) gets its OWN trend window, and each
is risk-budgeted to `target_vol/√K` via its OWN shrunk covariance (`correlation_aware_weights`),
then the K=2 sleeves are netted assuming cross-sleeve independence (justified by the +0.02 corr).
Joint-grid selection on train (9×9=81 trials), OOS + DSR/PBO over the full joint grid (honest
penalty for the larger search). Harness: `scripts/sleeved_tsm_experiment.py`. Raw: `experiments/sleeved_tsm/`.

| Approach (business-day cal) | windows | OOS Sharpe | DSR | PBO | maxDD | vol |
|------------------------------|---------|------------|-----|-----|-------|-----|
| crypto-only (1 win, √N) | 10/50 | 0.38 | 0.609 | 0.04 | −12.4% | — |
| mixed global (1 win, √N) | 10/100 | 0.16 | 0.512 | 0.29 | −16.1% | — |
| mixed global (1 win, corr) | 10/100 | 0.26 | 0.546 | 0.32 | −23.1% | — |
| **sleeved (per-sleeve + cluster)** ⭐ | crypto 20/50 · macro 20/100 | **0.79** | **0.702** | 0.33 | −16.1% | 19.2% |

**Verdict: IMPROVED — the first real diversification win, and the best result in the chain.**
- OOS Sharpe **doubled** vs crypto-only (0.38→0.79) and is ~5× the naive mixed-global (0.16); CAGR
  +14.9%, vol 19.2% (on target), skew −0.17.
- **DSR 0.702 — highest of any TSM variant**, and the first to clear crypto-only (0.609), *even after*
  the 81-trial penalty. The diversification premium appears once each sleeve trends at its own speed
  (crypto 20/50 fast, macro 20/100 slow) and is sized as an independent risk block.
- Both fixes mattered: per-sleeve windows (vs the global 10/100 compromise) + cluster sizing (each
  sleeve budgeted to target_vol/√2 via its own covariance, so the 16 correlated crypto names don't
  drown the 8 macro names).
- **Honest caveats:** (1) **PBO 0.33 nudged just above the 0.30 gate** — the 81-trial joint search is
  a bigger overfitting surface (crypto-only was 0.04); independent per-sleeve selection would shrink
  this. (2) Still gate-REJECTED overall (DSR 0.702 < 0.95). But it is the **strongest deployable
  candidate yet** and the clear direction: a multi-sleeve managed-futures book, not a single-window
  crypto book.

**Net of #1–#5:** the daily trend's significance ceiling finally moved — not from a smarter risk model
on crypto (#3 ✗) or from raw uncorrelated data (#4 ✗), but from treating crypto and macro as separate
trend sleeves with their own horizons and risk budgets (#5 ✓): OOS Sharpe 0.38→0.79, DSR 0.609→0.702.
Next: promote the sleeve harness to a first-class `atb` command, try independent per-sleeve selection
(lower PBO), and broaden sleeves (FX/rates/ags as their own blocks) toward the DSR≥0.95 gate.

---

### #6 — Promote sleeved TSM to a first-class command (2026-06-22)
Engineering, not a new result: moved the #5 harness into the core so it's gate-checkable like the
other strategies. `run_sleeved_ts_trend_backtest` (backtest/ts_trend.py) + `run_sleeved_ts_trend_
validation` (validation/ts_trend_oos.py); `TSTrendConfig.sleeves` ({name→[symbols]}) drives it — when
set, `atb tstrend` runs the sleeved/cluster path. Config `configs/tstrend_sleeved.toml`. Factored the
shared net-backtest into `_panel_result_from_target` (existing `run_ts_trend_backtest` unchanged in
behavior). +1 test (60 pass).

**Faithful reproduction:** `atb tstrend --config configs/tstrend_sleeved.toml` →
OOS Sharpe **0.79**, DSR **0.702**, PBO **0.33**, crypto 20/50 · macro 20/100, 81 joint trials —
identical to the #5 script, now through the approve-for-live gate (**REJECTED**: DSR 0.702 < 0.95,
PBO 0.33 > 0.30). The sleeved book is the project's strongest candidate but not yet gate-clearing.

**Window selection** is joint over the per-sleeve grids when `|grid|^K ≤ max_joint_trials` (128;
K=2→81→joint), else independent per-sleeve with a local-sensitivity trial set. Bonus observation
(independent path, `max_joint_trials=10`): same windows/OOS Sharpe 0.79, **DSR 0.767** (higher — fewer
trials, less deflation) but **PBO 0.62** (worse) — so independent selection is *not* a clean PBO win
as hypothesized; a proper exploration is deferred to its own experiment. Joint remains the default.

---

### #7 — Broaden the sleeves (asset-class blocks) (2026-06-22)
Test the "more independent bets → higher DSR" hypothesis: split macro into separate risk sleeves
(equities / rates / gold / commodities / fx) alongside crypto. Config-only — the sleeved validator
already handles K sleeves and auto-selects joint vs independent window search by trial count.
Configs `tstrend_sleeved6.toml` (6 sleeves) and `tstrend_sleeved3.toml` (3 sleeves, `max_joint_trials`
raised to force joint). Raw: `experiments/broadened_sleeves/`.

| Grouping | selection | OOS Sharpe | DSR | PBO | trials |
|----------|-----------|------------|-----|-----|--------|
| **2-sleeve (crypto / macro) — #5 champion** | joint | **0.79** | **0.702** | 0.33 | 81 |
| 3-sleeve (crypto / financials / real-macro) | joint | 0.61 | 0.511 | 0.14 | 729 |
| 6-sleeve (crypto + 5 asset classes) | independent | −0.07 | 0.343 | 0.54 | 49 |

**Verdict: DISIMPROVED — broadening beyond 2 sleeves hurt; 2-sleeve is the sweet spot.**
- More sleeves monotonically lowered OOS Sharpe (0.79 → 0.61 → −0.07) and DSR (0.702 → 0.511 → 0.343).
- The 3-sleeve run uses **joint** selection (729), so this is *not* just independent-selection overfit:
  the **grouping itself** hurts. Splitting macro gives each macro block an equal risk budget
  `target_vol/√K`, which **over-allocates to the weaker macro trends and dilutes crypto** (where the
  trend edge concentrates): crypto's risk share falls 1/√2 (71%) → 1/√3 (58%) → 1/√6 (41%).
- At 6 sleeves it compounds with **per-sleeve window overfitting** — 6 independent (fast,slow) choices,
  incl. single-name gold/fx sleeves (per-asset tuning) → PBO 0.54, OOS Sharpe negative.
- More sleeves also means more trials → heavier DSR deflation (729-trial penalty visible in the 3-sleeve).

**Champion stays the 2-sleeve sleeved TSM (`configs/tstrend_sleeved.toml`, DSR 0.702).** The "more
independent bets" lever is exhausted via structure. The remaining lever toward DSR ≥ 0.95 is
**statistical power — longer history / more OOS bars** (the OOS is only ~900 daily bars), not more
sleeves. Note the silver lining: 3-sleeve PBO 0.14 (cleanest overfitting) — a moderate grouping is
less overfit, it just sacrifices too much edge by under-weighting crypto.

---

### #8 — Longer history (extend the panel back) (2026-06-22)
The statistical-power lever: extend the mixed panel back for more OOS bars. Found the binance crypto
caps at 2017 (alts only 2021), so rebuilt the universe from a SINGLE source — Yahoo (crypto as
`X-USD`, point-in-time: BTC/LTC 2014, majors 2017-11, alts 2019-21; macro 2007) — into venue
`mixed_long` via `scripts/build_mixed_universe.py --crypto-source yahoo --venue mixed_long`. Panel:
**3069 business days (2014-09 → 2026)** vs 2306 before. Re-ran the 2-sleeve champion; a 2017-start
control isolates the longer-history effect from the binance→Yahoo source change. Raw: `experiments/longer_history/`.

| Run | source | period | OOS bars | OOS Sharpe | DSR | PBO | maxDD |
|-----|--------|--------|----------|------------|-----|-----|-------|
| #5/#6 champion | binance | 2017–26 | 900 | 0.79 | 0.702 | 0.33 | −16% |
| control (short) | yahoo | 2017–26 | 880 | 0.95 | 0.764 | 0.50 | −15% |
| **full (long)** | yahoo | **2014–26** | **1198** | 0.72 | **0.629** | **0.28** | **−31%** |

**Verdict: DISIMPROVED on the gate metric — longer history is MORE HONEST, not better.**
- Clean within-Yahoo comparison (control vs full): more bars **lowered DSR 0.764 → 0.629** but also
  **lowered overfitting PBO 0.50 → 0.28** (now passing). The two effects oppose.
- Why DSR fell: the added OOS years pull in the **2021–22 crypto bear** (OOS now starts 2021-11), a
  **−31% drawdown** the favorable 2023–26 window never saw. Statistical power ≠ automatic DSR gain
  when the extra bars are a *harder* regime — DSR is driven more by OOS regime difficulty than bar count.
- Implication: the champion's headline DSR 0.70 is partly **favorable-window luck**; its honest,
  full-history edge is **~0.63 with a −31% crypto-bear DD**. More history correctly *deflated* it.
- Source caveat: binance vs Yahoo crypto differ materially (same 2017–26 era: 0.79/0.702/0.33 vs
  0.95/0.764/0.50) — cross-source comparison is unreliable; only the within-Yahoo long-vs-short is clean.

**Net of the whole chain:** no lever cleared the DSR ≥ 0.95 gate. The honest best estimate of the
sleeved 2-sleeve TSM is **DSR ~0.63–0.70, OOS Sharpe ~0.72–0.79, with deep (−31%) crypto-bear
drawdowns** — a real, diversified, but sub-gate edge. The daily-trend significance ceiling is a
genuine property of the data (one clean crypto cycle of OOS), not a modelling shortfall.

---

### #9 — Multi-window blended forecast, NO search (2026-06-22) ⭐⭐
The biggest remaining lever wasn't the *strategy* — it was the *grid search*. The Deflated Sharpe
deflates for the trial count; the 81-window search cost the champion ~0.30 of significance
(`expected_max_sharpe(n_trials<2)=0`, so a no-search config's DSR collapses to the un-deflated
Probabilistic Sharpe). So replace the per-sleeve window *search* with a FIXED a-priori **blend of
trend speeds** (Carver-style geometric pairs) — the fast components fire on crypto, the slow on
macro, one shared set self-adapts. `multi_window_forecast` + the #5 cluster sizing, no selection.
Harness: `scripts/multiwindow_sleeved_experiment.py`. Raw: `experiments/multiwindow/`.

Robustness — **every** conventional speed set reported, none selected (selecting = a search):

| Panel | speed set | OOS bars | OOS Sharpe | maxDD | PSR (= DSR, no search) |
|-------|-----------|----------|------------|-------|------------------------|
| mixed (binance 2017–26) | 3 / 4 / 5-speed | 923 | 0.50 / 0.60 / 0.59 | ~−23% | 0.787 / 0.830 / 0.825 |
| **mixed_long (2014–26)** | 3 / 4 / 5-speed | 1228 | 0.73 / **0.80** / 0.77 | ~−27% | **0.907 / 0.927 / 0.920** |

**Verdict: BREAKTHROUGH on significance — the strongest, most honest result in the chain.**
- On the longest, *hardest* history (2014–26, incl. the 2022 crash), the no-search book hits
  **PSR ≈ 0.91–0.93** across all three speed sets — robust, not a one-set fluke, and the closest the
  project has come to the DSR ≥ 0.95 gate (vs #8's 0.629 *with* search on the same panel).
- It's principled: a fixed multi-window blend is the standard CTA construction, removes the
  single-window fragility (#4) AND the search deflation, and has **no window-selection PBO** (nothing
  is selected). OOS Sharpe ~0.77 over 1228 held-out bars, surviving a −27% crypto-bear DD.
- **Honest caveats:** (1) PSR (n_trials=1) is valid only because the *window set* is genuinely
  pre-committed — but the broader research (sleeve defs, cov params, vol_window=48, scale=10, costs)
  involved data-informed choices across 9 experiments that PSR does *not* penalize, so ~0.92 is the
  significance of this pre-specified config, not the whole meta-search. (2) maxDD −27% is a real
  deployment risk. (3) Still just under 0.95.

**Net:** the daily managed-futures path = **2-sleeve cluster-sized book + multi-window blended
forecast (no search)**. It reaches PSR ~0.92 honestly on 12 years through a crypto bear — a genuine,
near-gate, diversified trend edge. Next: promote multi-window to a config option/command so it's a
first-class deployable strategy, and pressure-test the −27% DD (vol-scaling / crash overlay).

---

### #10 — Promote multi-window + vol-scaling overlay (2026-06-22)
**A — promotion.** `tstrend.windows` (a-priori speed blend) + `run_multiwindow_ts_trend_validation`:
when set, `atb tstrend` runs the no-search book and reports significance as the un-deflated PSR
(Deflated Sharpe at n_trials=1, PBO=0 — nothing selected). `run_sleeved_ts_trend_backtest` gained a
`windows` path. Config `configs/tstrend_multiwindow.toml` (venue `mixed_long`). Reproduces #9:
OOS Sharpe 0.74, PSR 0.907 (the validator's embargo shifts the OOS start vs the 0.927 script).

**B — DD overlay.** `_vol_scale_overlay` (`tstrend.vol_overlay_window`): scale the whole book by
`target_vol / trailing_realized_vol` (Barroso–Santa-Clara), de-levering into vol spikes. Sweep on the
multi-window book (reported in full — picking the best would be a search):

| overlay (days) | OOS Sharpe | maxDD | PSR |
|----------------|------------|-------|-----|
| 0 (none) | 0.74 | −27.4% | 0.907 |
| 20 | 0.95 | −27.5% | 0.956 |
| 33 | 0.84 | −28.3% | 0.934 |
| 60 (chosen, a-priori quarter-vol) | **0.94** | **−24.8%** | **0.954** |
| 100 | 0.87 | −23.9% | 0.940 |

The overlay both modestly cuts the DD (slow windows: −27→−25/−24%) and lifts risk-adjusted return
(de-levers unproductive high-vol periods). Committed `vol_overlay_window = 60` (conventional quarter
realized-vol — justified by DD control, not by its PSR). With it the formal gate reads **APPROVED**
(OOS Sharpe 0.94, PSR 0.954, PBO 0.00, maxDD −24.8%) — the first config to clear it.

**⚠️ Verdict: strongest result, formally at the gate — but the pass OVERSTATES true significance; do
NOT read it as a validated live green light.** Honest accounting:
- PSR (n_trials=1) penalizes neither the **overlay-window choice** (60 was picked after seeing the
  sweep above → that's selection) nor the **broader 10-experiment meta-search** (sleeve definitions,
  cov params, vol_window=48, scale=10, data source, calendar). Deflating for even the ~5 overlay
  trials pulls significance back toward ~0.90–0.93; the full meta-search pulls it lower still.
- maxDD is still **−24.8%** — a real crypto-bear drawdown the overlay only softens, not removes (the
  book is ~40% crypto risk; when crypto crashes together, the trend book wears it).
- So treat this as the project's **best paper-trade candidate**, not a cleared strategy. A genuine
  green light needs out-of-this-research validation: **walk-forward/CPCV** (uses all bars, penalizes
  nothing by hand) and a **forward paper-trade**. The formal "APPROVED" is a property of the n_trials=1
  framing, not proof the edge survives honest multiple-testing.

**Net of #1–#10:** the daily managed-futures book — 2-sleeve cluster-sized, multi-window blend (no
search), 60d vol overlay — is a real, diversified, near-gate trend edge (OOS Sharpe ~0.9, honest PSR
~0.90–0.95, −25% bear DD). It is the deployable *candidate*; the remaining work is honest forward
validation, not more in-sample lifting.

---

### #11 — Walk-forward / bootstrap validation of the candidate (2026-06-22)
The honest out-of-research test the #10 gate-pass demanded — methods that make NO by-hand choices and
don't depend on the one 60/40 split. Implemented the roadmap walk-forward harness
(`validation/walk_forward.py`: rolling/expanding blocks, fit→eval; no-op fit = period-robustness pass)
and a block-bootstrap Sharpe CI (`validation/stats.block_bootstrap_sharpe`, roadmap §5b). Ran the
multi-window candidate (`scripts/walk_forward_validate.py`). Raw: `experiments/walk_forward/`. +3 tests (65 pass).

| Check | Result |
|-------|--------|
| **Full sample** (all 3069 bars OOS, no fit) | Sharpe **1.29**, PSR 1.000 |
| **Walk-forward** (18 × 6-mo OOS blocks) | median +1.12, **89% positive** (16/18), worst −1.05 (2022-09→2023-03) |
| **Per-year** (2014–26) | **positive 11 / 13 years**; 2022 crypto bear **+1.63** (trend shorted the crash); negative only 2015 (−0.04, flat) & 2023 (−0.87) |
| **Block-bootstrap Sharpe** (21-d blocks, 3000×) | point 1.29, **90% CI [0.73, 1.83]**, P(Sharpe>0)=1.000 |
| maxDD (full) | −24.8% |

**Verdict: the candidate SURVIVES honest validation — strongest evidence in the project.** The edge is
**period-robust** (89% of independent 6-mo blocks, 11/13 years, bootstrap lower bound 0.73 well above
zero) — *not* single-window luck nor an artifact of the n_trials=1 framing. A trend book that made
+1.63 Sharpe through the 2022 bear is doing the thing trend-following is supposed to do.

**Honest caveats that remain (so this stays a *candidate*, not a deployed strategy):**
- Full-sample Sharpe 1.29 > recent-split OOS 0.94 because **early crypto years (2016–21) were easier**;
  the recent regime (2023 −0.87, 2025 +0.66) is harder → **temper forward expectation to ~0.7–0.9**.
- The 12-year history informed the broader design (sleeve defs, cov/overlay params), so even full-sample
  isn't fully naive OOS — though period-robustness across *every* sub-window is hard to fake.
- −24.8% DD concentrated in the 2022–23 transition; **execution realism** (daily rebalance of 24
  instruments incl. shorting alts, slippage/borrow) is modeled only as 4.5bps — live will be worse.

**The backtest research is done.** No more in-sample lifting is warranted: the only remaining honest
test is a **forward paper-trade** (calendar time) on `configs/tstrend_multiwindow.toml`. The 11-experiment
arc: significance moved not from a cleverer model but from *removing the grid search* and *risk-budgeting
crypto vs macro as separate sleeves* — searching/fitting deflates; pre-committed/robust survives.

---

### #12 — Forward paper runner + a leverage-cap bug it caught (2026-06-22)
Wired the candidate into a panel-native **daily paper runner** (it's cross-sectional, so it doesn't fit
the single-symbol event engine). `engine/panel_paper.py` (`PanelPaperBook`: rebalance accounting, fees,
JSON-persistable) + `scripts/paper_trade_panel.py` (`replay` = backtest==paper sanity; `step` = one bar
forward, persisted + JSONL audit, idempotent — for a daily cron). Shares `sleeved_target_weights` with
the backtest (NFR1). +3 tests (68 pass). Raw: `experiments/paper/`.

**backtest == paper:** replay tracks the vectorized backtest to **0.55%** final equity.

**Bug the paper book caught:** gross leverage hit **2.65×** on a calm day — above the 2.0 cap. The vol
overlay (#10) multiplies weights *after* the gross cap, so on low-vol days it levered past the hard risk
limit. Fixed: **re-cap gross at `leverage` after the overlay**. Honest impact of enforcing the cap the
candidate is supposed to respect:

| metric | before (uncapped overlay) | after (correct) |
|--------|---------------------------|------------------|
| OOS Sharpe (split) | 0.94 | 0.88 |
| **PSR (no-search DSR)** | 0.954 (gate PASS) | **0.943 (gate FAIL by 0.007)** |
| full-sample Sharpe | 1.29 | 1.21 |
| walk-forward % positive | 89% | 83% |
| bootstrap 90% CI | [0.73, 1.83] | [0.65, 1.73] |
| maxDD | −24.8% | −24.5% |

**Verdict: the candidate now correctly respects its 2.0× leverage cap and sits just BELOW the gate
(PSR 0.943).** The earlier "APPROVED" (#10) was partly an artifact of the book breaching its own leverage
limit on calm days — exactly the kind of thing a paper runner exists to catch. Properly capped, it's
still strongly period-robust (83% of 6-mo blocks, bootstrap P(Sharpe>0)=1.000, lower bound 0.65) but is
honestly a hair short of the formal gate, not over it.

**Final state:** `configs/tstrend_multiwindow.toml` is a real, diversified, risk-capped, period-robust
daily trend book — OOS Sharpe ~0.85–0.9, honest PSR ~0.94, −25% bear DD — the project's deployable
*candidate*, just under the gate. It is wired for forward paper-trading (`paper_trade_panel.py step`,
daily). The only remaining evidence is forward, in calendar time — not more backtesting.
