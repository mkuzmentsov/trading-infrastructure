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

---

## PLANNED — "How do I get the Binance-leaderboard numbers" roadmap (2026-06-28)

Context: user saw Binance copy-trading accounts posting +2,500% / 30d, 88% win rate, 10–20× leverage,
and asked to replicate them — risk-accepting. **Framing (not negotiable, it's just arithmetic):** those
ROIs are a *survivorship + leverage* artifact, not a strategy. 88% win + 31% MDD + 10–20× lev is the
martingale/grid signature — wins almost daily, then gives back principal on one move; the accounts that
already did that aren't on the leaderboard. So we do NOT chase a coin-flip at 20×. We do three things,
**in order**: (1) scale the *real* edge (`tstrend_multiwindow`) the only honest way — leverage/vol-target
+ compounding; (2) study the copy-traders with real data so the blow-up risk is *visible*, not assumed;
(3) ring-fence a small degen sleeve that bets a real edge at high size with a hard kill-switch.

These rows are **proposals** (hypothesis + how-to-measure + decision rule), not results. Run #13 first.
User OK'd 1m-interval data (see #16). Each follows the same baseline-first / verdict workflow as above.

### DIRECTION 1 — Scale the real edge (START HERE)
The candidate already has the edge. "Bigger dollars" comes from **leverage × compounding × time**, which
*scales* a Sharpe-0.8 book — it does NOT raise Sharpe, and it scales drawdown linearly + ruin super-linearly.
The knobs are `[risk] target_annual_vol` (0.20) and `max_gross_leverage` (2.0) in `tstrend_multiwindow.toml`.

#### #13 — Leverage / vol-target FRONTIER ⭐ (the core "scale" experiment) — DONE (2026-06-28)
- **Did:** `scripts/leverage_frontier.py` sweeps `target_annual_vol` ∈ {0.15,0.20,0.30,0.40,0.60} × gross
  cap ∈ {2,3,4,6}× on the full 2014–26 panel (3069 bars, every bar OOS — windows pre-committed, nothing
  fit). Per cell: Sharpe, compounded CAGR, realized gross leverage, full-sample maxDD, and a **block-
  bootstrap (21-day blocks, 8000 resamples) 1-year drawdown distribution** → 5th-pct "bad-year" DD +
  P[1-yr path breaches −50% / −80% / −100% (liquidation)]. Raw: `experiments/leverage_frontier/frontier.txt`.

| tgtVol | cap | Sharpe | CAGR | realLev | maxDD | badYrDD | P<−50% | P_ruin |
|-------:|----:|-------:|-----:|--------:|------:|--------:|-------:|-------:|
| 0.15 | 2× | 1.26 | 13.9% | 1.43× | −19.2% | −18.8% | 0% | 0% |
| 0.20 | 2× | 1.21 | 16.2% | 1.71× | −24.5% | −22.8% | 0% | 0% | ← baseline |
| 0.20 | 3× | 1.25 | 18.7% | 1.95× | −24.8% | −25.0% | 0% | 0% |
| **0.30** | **4×** | **1.26** | **27.6%** | 2.87× | −35.2% | −34.8% | 0.1% | 0% | ← best Sharpe×CAGR |
| 0.40 | 6× | 1.25 | 36.4% | 3.90× | −44.3% | −45.0% | 2.1% | 0% |
| 0.60 | 6× | 1.21 | 45.3% | 5.12× | −59.7% | −56.4% | 11.6% | 0% | ← aggressive |

- **Result — hypothesis CONFIRMED.** Sharpe is **flat (~0.96–1.26) across the entire grid**: leverage only
  *scales* the edge, it does not create or destroy it (exactly the honest signature). CAGR runs 14%→45%,
  maxDD 19%→60%, moving together. Top-right (0.60/6×) shows the predicted **volatility-drag rolloff** —
  realized 5.12× but CAGR gains decelerate and Sharpe slips while bad-year DD blows out to −56%.
- **The headline finding for the user's question:** **P_ruin = 0% in every cell**, even at 5.12× realized
  leverage. A *diversified, vol-targeted, 24-asset daily* book essentially cannot be liquidated in a
  bootstrapped year — the polar opposite of the Binance-leaderboard accounts (single-direction, 10–20×,
  martingale) whose whole return *is* ruin risk. Same nominal "leverage," categorically different survival.
- **Caveat (honesty):** these CAGRs are full-sample compounded with pre-committed-but-crypto-bull-heavy
  history; temper forward to the #11 walk-forward Sharpe (~0.7–0.9), so a forward CAGR roughly ~0.6–0.7× the
  table. The DD/ruin columns are the durable part — those are what sizing must respect.
- **Recommended operating points (user picks by bad-year DD tolerance, per the decision rule):**
  *conservative* tv0.20/cap3× (CAGR ~19%, bad-yr −25%); *efficient sweet-spot* **tv0.30/cap4× (highest
  Sharpe 1.26, CAGR ~28%, bad-yr −35%)**; *aggressive* tv0.40/cap6× (CAGR ~36%, bad-yr −45%). Beyond that,
  0.60/6× buys little Sharpe for a −56% bad year — the drag wall.
- **Verdict: IMPROVED / characterized.** Establishes the dial. Next: #14 (fractional-Kelly + compounding —
  is tv0.30/cap4× actually near half-Kelly?) then #15 (DD-throttle to push the safe ceiling higher).

#### #14 — Fractional-Kelly + compounding check for the chosen point — DONE (2026-06-28)
User chose the **aggressive 0.40/6×** operating point from #13 → `configs/tstrend_multiwindow_aggr.toml`
(target_vol 0.40, gross cap 6×). #14 locates the Kelly peak to confirm the pick is on the safe (sub-Kelly)
side. `scripts/kelly_compounding.py` traces realized-vol → compounded-CAGR by sweeping target_vol with a
non-binding cap (the book already compounds, equity = Π(1+r)). Raw: `experiments/kelly_compounding/kelly_curve.txt`.

| target_vol | realized vol | real lev | Sharpe | CAGR | maxDD |
|-----------:|-------------:|---------:|-------:|-----:|------:|
| 0.20 | 22% | 2.0× | 1.17 | 18.0% | −24.8% |
| **0.40** | **43%** | **4.0×** | **1.18** | **34.7%** | **−44.7%** | ← chosen |
| 0.70 | 75% | 7.0× | 1.20 | 55.8% | −68.0% |
| 1.10 | 117% | 10.9× | 1.23 | **69.4%** (PEAK) | −86.8% |
| 1.40 | 146% | 13.6× | 1.25 | 68.5% | −93.8% |
| 1.80 | 177% | 16.2× | 1.24 | 48.3% (drag) | −97.9% |

- **Result — both predictions CONFIRMED.** (1) The **empirical Kelly peak** is at ~117% realized vol /
  10.9× leverage (CAGR 69%) — and full-Kelly vol ≈ Sharpe (1.18), exactly the growth-theory relation.
  (2) **Past the peak CAGR FALLS** (1.40→68.5%, 1.80→48.3%) while maxDD keeps climbing to −98% — the
  volatility-drag wall, demonstrated not asserted. Analytic cross-check agrees: k* = μ/σ² = **2.98×** the
  chosen sizing (full-Kelly ≈ 3× current → ~128% vol, matching the 117% peak).
- **Where 0.40/6× sits:** realized 43% vol = **0.36× of full-Kelly on full-sample** (deeply sub-half-Kelly,
  safe). On the HONEST forward Sharpe (~0.8, per #11), full-Kelly vol ≈ 0.80 so half-Kelly ≈ 0.40 → the
  chosen point is **≈ half-Kelly forward** — the textbook prudent ceiling (~¾ the growth at ~½ the DD).
  Either lens says it is well-chosen and NOT over-levered.
- **Why not chase the 10.9× peak:** its −87% drawdown is unsurvivable psychologically, AND it's only optimal
  on the optimistic full-sample Sharpe; at the honest forward Sharpe the peak moves *below* 10.9×, so sitting
  there forward would be PAST Kelly = pure drag. Half-Kelly is the correct stopping point.
- **Verdict: CONFIRMED — 0.40/6× is the aggressive-but-sane ceiling (≈ half-Kelly forward).** Compounding is
  already on (geometric equity). No fractional-Kelly *sizing mode* needed — the target_vol dial already
  expresses it; documented that tv ≈ forward-Sharpe × (Kelly fraction). Next: #15 (DD-throttle to cut the
  −45% bad year without giving up the growth — buys back headroom toward a higher safe point).

#### #15 — Drawdown-throttle overlay — DONE: DEAD END (2026-06-28) ✗
- **Did:** `scripts/dd_throttle.py` adds a causal HWM de-lever overlay (factor ramps 1→floor between a
  `start` and `halt` drawdown) on the 0.40/6× book. Part A: throttle vs off at fixed sizing. Part B: the
  real test — run the firm throttle at HIGHER target-vol and see if any row matches off@0.40's −45% bad
  year at MORE CAGR (= headroom bought). Bad-year DD bootstrapped on raw blocks with the throttle applied
  to each path. Raw: `experiments/dd_throttle/throttle.txt`.

| variant @ tv0.40 | Sharpe | CAGR | maxDD | badYrDD |
|------------------|-------:|-----:|------:|--------:|
| **off** | **1.25** | **36.4%** | −44.3% | −45.0% |
| gentle 15→40 | 1.10 | 26.9% | −37.4% | −37.1% |
| firm 10→30 | 0.97 | 17.5% | −29.9% | −29.8% |

  Headroom test (firm throttle, higher tv): tv0.55→CAGR 13.4%/badYr −32%, tv0.70→CAGR 16.0%/badYr −34%.
  None beats off@0.40 (36.4% CAGR). No higher-leverage row recovers the lost growth.
- **Result — hypothesis REJECTED.** The throttle **lowers Sharpe monotonically** (1.25→1.10→0.97) and buys
  **zero** leverage headroom: it trades CAGR for DD at *worse* than 1:1, and you cannot lever back to the
  same CAGR. Strictly dominated by the clean book.
- **Why (the lesson):** this is a **trend-following** book — its drawdowns are *followed by its best runs*
  (the trend reverses and the book is already positioned for it; it shorted the 2022 crash, +1.63 that
  year per #11). An equity-curve throttle de-levers into exactly those troughs → it **sells the recovery**.
  Drawdown-control overlays help mean-reverting/martingale books; they HURT trend. (Contrast: the
  leaderboard martingales *would* be "helped" by a throttle — because their drawdowns are terminal, not
  followed by recovery. Different sign of edge, opposite overlay.)
- **Verdict: DISIMPROVED — do NOT add the throttle.** The scaled real-edge book stays clean:
  `configs/tstrend_multiwindow_aggr.toml` (0.40/6×, vol-overlay only). Useful negative result: confirms the
  −45% bad year is *structural* to running trend at half-Kelly and can't be overlay-engineered away without
  killing the edge — it must be accepted (it's the price of the 0% ruin) or sized down (#13's lower rows).

#### #16 — 1m / intraday probe — DONE: signal@1m DEAD, exec@1m deferred (2026-06-28) ✗
- **Did (a) signal at 1m:** ran the trend engine on `binance__BTC__1m` (43,201 bars, 30 days 2026-05-19→06-18,
  the only 1m data on disk) net of 4.5bps taker, `atb backtest` + `atb validate`. Raw: `experiments/onemin_probe/`.

| 1m trend | trades | turnover | OOS Sharpe | hit | DSR | gate |
|----------|-------:|---------:|-----------:|----:|----:|------|
| untuned | 17,531 | 210× | −164 | 3.4% | — | — |
| tuned (ema 10/240, slowest the grid allows) | — | — | **−105** | 6.6% | 0.000 | REJECTED |

  buy&hold over the same (bull) window: OOS Sharpe **+3.82**. P(OOS loss)=1.00, PBO 0.00 (not overfit — just
  genuinely bad). The tuner fled to the slowest slow-EMA to trade less and *still* lost — every 1m crossing
  is whipsaw, and 210× turnover × 4.5bps eats the book alive.
- **Result — hypothesis CONFIRMED: no edge at 1m, fully fee-dominated.** Consistent with
  [[perp-scalper-findings]] and [[listing-sniper-findings]] — intraday direction is a coin-flip and costs
  win. More trades = more bleed, not more edge. **Do not pursue 1m signals.**
- **(b) execution at 1m — DEFERRED, not run.** The only *sensible* 1m use is modeling better fills/slippage
  on the **daily** book's rebalances (not generating signal). Can't test rigorously now: only 30 days of 1m,
  BTC alone, vs the 24-symbol daily universe. Would need intraday bars for the full universe to estimate the
  slippage saving — left as a future data-fetch task, NOT claimed. (Expected payoff is small: the daily book
  rebalances once/day, so execution refinement is a few bps, not an edge.)
- **Verdict: DISIMPROVED for signal; the daily horizon stays the home of the edge.** Closes Direction 1.

#### #16b — Full frequency ladder 5m/15m/1h (user asked; data from data.binance.vision) — DONE (2026-06-28) ✗
- **Did:** pulled long-history spot BTCUSDT klines from data.binance.vision (`scripts/fetch_binance_vision.py`,
  2022-01→2026-05, 4.4y, venue `bvision`, files `bvision__BTC__{5m,15m,1h}.parquet`; 5m=464k bars) and ran the
  same `backtest`+`validate` trend probe at each. Configs `btc_{5m,15m,1h}_bv.toml`. Raw:
  `experiments/onemin_probe/frequency_ladder.txt` (+ `validate_5m.txt`).

| interval | bars | backtest Sharpe | OOS (tuned) | buy&hold OOS | gate |
|----------|-----:|----------------:|------------:|-------------:|------|
| **1d** (the edge) | 3,228 | **+0.68** | **+0.62** | +1.04 | the one that works |
| 1h | 38,687 | −2.38 | −2.68 | +0.55 | REJECTED, DSR 0.000 |
| 15m | 154,747 | −6.20 | −0.85 | +0.55 | REJECTED, DSR 0.000 |
| 5m | 464,240 | −10.38 | −0.21 | +0.55 | REJECTED, DSR 0.000 |
| 1m | 43,201 | −163 | −105 | +3.82 | REJECTED, DSR 0.000 |

- **Result — MONOTONIC and decisive: no intraday timeframe has a trend edge, and finer = worse.** Backtest
  Sharpe degrades smoothly −2.4→−6.2→−10.4→−163 as the bar shrinks. Tuned-OOS at 5m/15m only creeps toward
  ~0 because the grid flees to the slowest EMA (10/240) = "trade less / approximate flat" — still negative,
  never positive, never beats buy&hold. All four DSR = 0.000.
- **Mechanism (per-regime breakdown):** in TRENDING bars the intraday signal is genuinely positive (1h
  trend_up Sharpe +7.18 / +10.9%), but RANGE bars are **57–61% of all intraday bars** and bleed it out (1h
  range −12.0 / −30.9%). Finer bars = more range/noise = more whipsaw = more fee bleed. The **daily** bar
  averages through intraday noise, which is exactly why the same signal survives at 1d. **The edge is a
  horizon property; it does not exist intraday.**
- **Verdict: DISIMPROVED at every intraday frequency. Final answer to "what about 5m/15m/1h": no.** The
  scaled daily book (`tstrend_multiwindow_aggr.toml`) remains the only home of the edge. Reusable bulk
  downloader added (`fetch_binance_vision.py`) for any future long-history intraday work.

### DIRECTION 2 — Study the copy-traders (make the risk visible)
Goal: turn "+2,500% looks great" into a quantified P(blow-up) the user can *see* before risking a dollar.

#### #17 — Reconstruct a leaderboard account's risk profile
- **Do:** pull a few top accounts (e.g. 榴莲基金 / ETH詹哥) via Binance copy-trade public API or scrape;
  characterize per-trade leverage, frequency, win/loss size asymmetry, max adverse excursion; rebuild the
  equity path and estimate risk-of-ruin.
- **Hypothesis:** the 88% win / 31% MDD profile resolves to martingale/averaging-down: many small wins,
  rare huge losses, expectancy fragile to one trend. Quantify P(−80% within 90d) for that leverage.

#### #18 — Survivorship correction on the leaderboard itself
- **Do:** snapshot N "High ROI" accounts now; re-snapshot over weeks; track how many vanish / collapse.
- **Hypothesis:** the *cohort* expected ROI of "copy a current top account" — including the ones that later
  blow up and drop off — is far below the visible survivors, plausibly negative net of the DD you inherit
  as a late copier. This is the number that actually predicts the user's outcome, and the leaderboard hides it.

### DIRECTION 3 — Ring-fenced "degen" sleeve (high risk, can't sink the ship)
Only after #13–#14 set the core book. The whole point is *containment*: a −100% here must not touch core.

#### #19 — Hard-capped, segregated sleeve + kill-switch — DONE (2026-06-28)
- **Built:** `src/algo_trading_bot/risk/sleeve.py` — `SegregatedSleeves` composes two fully independent
  `PanelPaperBook`s (core + degen) and reuses the existing `DrawdownBreaker` as the kill-switch. `step()`
  rebalances core unconditionally, gates degen by its own breaker factor, and liquidates the degen sleeve
  (flatten + floor at 0 + permanent halt) on an isolated-margin floor breach. Default alloc 3%, degen DD
  tiers derisk −50% / halt −90%. +6 tests `tests/test_sleeve.py` (full suite 76 pass).
- **The three guarantees, each unit-pinned:**
  1. **Separate cash** — a total degen wipeout leaves `core.equity` byte-identical (test asserts core cash
     literally never moves through a degen blow-up).
  2. **Bounded loss** — degen equity is floored at 0 (isolated margin: the exchange liquidates the
     *subaccount*, can't claw from core); a 20× position through a −90% move loses the sleeve, ≤ the 5%
     allocation, never a cent more.
  3. **Permanent kill-switch** — on deep DD the breaker halts; a halted sleeve stays flat even on a juicy
     signal at a recovered price, and only an explicit `reset_degen()` (ops decision, never automatic)
     re-arms it. Also refuses any `degen_fraction > 0.25` at construction.
- **Verdict: DONE — the ring-fence is real and proven.** The high-risk outlet now physically cannot harm
  the core book, so the risk appetite has a safe home. Next: #20 (a high-leverage strategy to run *inside*
  it, with real liquidation modeling from `markPriceKlines` + `liquidationSnapshot`), then #21 (ruin sizing).
  Data note: for #20/#21 pull perps from `data.binance.vision/data/futures/um/...` (USDT-M mark price +
  liquidation snapshots), not spot klines — `fetch_binance_vision.py` is the starting point to extend.

#### #20 — High-leverage strategy inside the sleeve, with REAL liquidation — DONE (2026-06-28)
- **Did:** pulled 6.4y BTC USDT-M perp price + **mark price** (`scripts/fetch_binance_vision.py --market um`,
  venues `umperp`/`ummark`; liquidationSnapshot is 404 — Binance discontinued it, but mark-price OHLC is the
  faithful liquidation trigger). `scripts/degen_liquidation.py` runs the sleeve at leverage L∈{2,3,5,10,20}
  rebalanced daily, **liquidated when the day's MARK adverse excursion (from open) ≥ 1/L − maint(0.5%)** —
  the real Binance isolated-margin mechanic. TREND (EMA 20/100 sign) vs NAIVE (always long). 20k bootstrapped
  1-yr sleeve paths → full terminal-multiple distribution. Raw: `experiments/degen_sleeve/liquidation.txt`.

| mode | lev | P(liquidated) | median | 95th-pct | mean |
|------|----:|--------------:|-------:|---------:|-----:|
| trend | 2× | **0%** | **1.24×** | 8.7× | 2.54× |
| trend | 3× | 0% | 0.77× | 14.7× | 4.09× |
| trend | 5× | 27% | 0.02× | 9.7× | 10.3× |
| trend | 10× | **99.8%** | 0.00× | 0.00× | 0.04× |
| trend | 20× | **100%** | 0.00× | 0.00× | 0.00× |
| naive | 10× | 99.6% | 0.00× | 0.00× | **29.3×** (mean!) |
| naive | 20× | 100% | 0.00× | 0.00× | 0.00× |

- **Result — the leverage cliff is real, steep, and quantitative.** P(liquidation within a year): ~0% at 2–3×,
  27–38% at 5×, **~100% at 10× and 20×.** The leaderboard's exact leverage (10–20×) = **near-certain ruin
  within a year**, regardless of signal. (And this is the *optimistic* bound: daily re-levering pushes the liq
  price away after good moves; a statically-held position liquidates even faster.)
- **Does a real edge help?** A little, only at modest leverage: TREND liquidates less than NAIVE (5×: 27% vs
  38%) because it goes flat/short in downtrends. But by 10× both are ~100% liquidated — **leverage dominates;
  signal quality becomes irrelevant.** A good edge cannot out-run a 5% wick at 20×.
- **The mean is a lie (the survivorship lesson, made of numbers):** naive 10× has **mean 29×** while median 0,
  P(liq) 99.6%, P(>1×) 0.2%. The "mean" is entirely a handful of moonshot paths — the 0.2% who post the
  screenshot. The other 99.6% are liquidated and invisible. **That IS the Binance leaderboard.**
- **Verdict: a high-leverage directional sleeve has NEGATIVE typical outcome (median 0 past 5×); it is a
  lottery ticket, not a strategy.** The only sane uses of the sleeve: (a) modest leverage (2–3×) on the real
  edge — 0% liq, positive median — but that's barely "degen"; or (b) treat it as an explicit lottery sized at
  fully-losable capital (#21). Either way the #19 ring-fence is what makes (b) survivable. Next: #21 formalize
  the sizing/ruin rule from this distribution.

#### #21 — Risk-of-ruin & sizing rule (capstone of Direction 3) — DONE (2026-06-28)
- **Did:** `scripts/degen_sizing.py` turns #20's distribution into a dollar sizing rule on a real bankroll
  ($100k, 3% = $3k stake) and applies two formal lenses: repeated-betting ln-growth g=E[ln(mult)] (ruin →
  g=−∞) and the one-shot dollar payoff distribution. Raw: `experiments/degen_sleeve/sizing.txt`.

| lev | P(total loss) | P(≥2×) | median $ | mean $ | 99th-pct $ | ln-growth g |
|----:|--------------:|-------:|---------:|-------:|-----------:|------------:|
| 2× | 0% | 34% | $3,721 | $7,612 | $59,264 | **+0.229** |
| 3× | 0% | 30% | $2,322 | $12,269 | $147,521 | −0.244 |
| 5× | 27% | 12% | $62 | $30,787 | $242,947 | −∞ (ruin) |
| 10× | 99.8% | 0% | $0 | $132 | $0 | −∞ (ruin) |
| 20× | 100% | 0% | $0 | $0 | $0 | −∞ (ruin) |

- **The rule, derived not asserted:**
  * **COMPOUND only at ≤2×.** 2× is the *highest* leverage that is both 0%-liquidation AND growth-positive
    (g=+0.23). Even **3× is growth-NEGATIVE** (g=−0.24) despite 0% liquidation — on a single BTC perp the
    fee/whipsaw drag makes the typical (median 0.77×) outcome a slow bleed. ≥5× has g=−∞ (ruin): **repeated
    high-leverage betting is mathematically certain ruin regardless of signal.** The "don't roll it" wall.
  * **LOTTERY (≥5×): size = fully-losable capital only.** Typical outcome is $0; the bet is the $3k stake, and
    it must be chosen by its *payoff distribution* (e.g. 5× has a 12% chance of ≥2× and a thin 99th-pct of
    $243k) — **never by the mean/95th**, which are pure survivorship. The leaderboard sells you that mean.
- **Bonus insight (ties back to Direction 1):** a single-asset perp is growth-negative above 2×, yet the CORE
  book runs ~4× *realized* leverage safely (#13, 0% ruin) — because it's **diversified across 24 vol-targeted
  assets**. Diversification, not leverage, is what buys safe size. The degen sleeve proves the converse.
- **Verdict: DONE. Direction 3 complete.** The ring-fence (#19) + the liquidation reality (#20) + this sizing
  rule (#21) give the risk appetite a mathematically safe home: compound the real edge at ≤2× in the sleeve,
  OR buy an explicit lottery ticket capped at fully-losable capital — and the core book is untouchable either
  way. The honest answer to "I'm OK with risk": good — here's how to express it without ever blowing up.

---

### #24 — Intraday MEAN-REVERSION at 5m/1h (the right hypothesis for intraday) — DONE (2026-06-29)
User pushed to try 5m/1h again. Re-running TREND there is settled (#16b: dead). The honest untested
question is the OPPOSITE signal: #16b showed intraday is 57-61% range/chop — where mean-reversion earns.
`scripts/intraday_meanrev.py` fades short-term dislocations (`pos = −tanh(z/1.5)`, z over a-priori
lookbacks 24/48/96, risk-scaled, lookahead-safe) on BTC 5m/1h (bvision, 4.4y). Reports GROSS Sharpe (does
it predict?) vs NET at maker(0bps) and taker(4.5bps). Raw: `experiments/intraday_meanrev/meanrev.txt`.

| interval | lookback | GROSS Sharpe | net@maker(0) | net@taker(4.5) | turnover/bar |
|----------|---------:|-------------:|-------------:|---------------:|-------------:|
| **5m** | 24 | **+0.74** | +0.74 | **−20.6** | 23.5% |
| 5m | 48 | +0.43 | +0.43 | −14.7 | 16.6% |
| 5m | 96 | +0.49 | +0.49 | −10.2 | 11.8% |
| 1h | 24 | −0.45 | −0.45 | −2.35 | 22.6% |
| 1h | 48 | −0.19 | −0.19 | −1.49 | 15.6% |
| 1h | 96 | −0.23 | −0.23 | −1.10 | 10.5% |

- **Result — FIRST positive intraday signal in the whole probe, but it's an EXECUTION problem, not a signal
  problem.** At **5m the MR signal genuinely predicts**: GROSS Sharpe +0.43–0.74, *positive across all three
  lookbacks* (robust, not a single-window fluke). **Taker fees annihilate it** (net −10 to −21; 12–24%
  turnover *per 5-min bar* is brutal). At **1h the edge is gone** (gross negative) — reversion is a
  ~minutes-scale phenomenon that has decayed by the hourly bar.
- **Honest caveat — do NOT read net@maker=+0.74 as capturable.** Maker fee = 0 here, but passive fills carry
  **adverse selection** (you get filled precisely when the move keeps going against you) and **non-fill risk**,
  neither modeled. Real maker net is below gross and unproven; capturing it means competing on latency/queue
  position with co-located market-makers — an HFT game, not a retail edge, and a crowded/decaying one.
- **Verdict: there is real 5m mean-reversion alpha, but it lives entirely inside the bid-ask/fee, so it is
  NOT capturable as a taker and unproven as a maker.** This refines #16b rather than overturning it: intraday
  isn't *signal-empty*, it's *cost-dominated* — the daily trend book remains the only signal that is positive
  NET after realistic costs. Next step (now built, below): a maker/limit execution study.

#### #24b — 5m MR under PASSIVE (maker) execution — DONE: borderline / unresolved (2026-06-29)
`scripts/intraday_maker.py`: limit-order fill model on the 5m bars — post at the prior close, fill only if
the bar's range reaches it (conditional fills = adverse selection), maker fee 1/2bps. Two signals: the
continuous tanh, and a low-turnover **threshold** version (enter |z|>2, exit |z|<0.5 — the realistic way
to trade a costly edge). Raw: `experiments/intraday_meanrev/maker.txt`.

| signal | lookback | GROSS | taker 4.5 | maker 1bp | maker 2bp | trades/yr |
|--------|---------:|------:|----------:|----------:|----------:|----------:|
| continuous | 48 | +0.43 | −14.7 | −3.16 | −6.51 | (every bar) |
| **threshold** | **48** | **+0.90** | −4.01 | **−0.29** | −1.39 | **2,213** |
| threshold | 24 | +0.42 | −7.72 | −1.55 | −3.37 | 3,565 |
| threshold | 96 | +0.32 | −2.51 | −0.37 | −1.00 | 1,291 |

- **Result — moved from "clearly dead" to "borderline / unresolved."** The low-turnover threshold version
  cuts trading to ~2k trades/yr and has a STRONG gross Sharpe (+0.32 to +0.90, positive across lookbacks),
  and at **1bp maker sits near breakeven (lb48 −0.29)**. The continuous signal stays clearly negative
  (overtrades). So the binding constraint is purely execution cost, and it's *close*.
- **The unresolved crux (why I will NOT call this a win):** my maker model is **pessimistic on spread capture**
  (fills at the prior close = earns NO spread) and **optimistic on fills** (full fill on touch, no queue /
  partial-fill / adverse-selection-vs-spread tradeoff). A real maker *earns* ~half the spread (~+0.5–1bp/trade
  on BTC) — which at 2k trades/yr could plausibly flip lb48 positive — BUT only on **adversely-selected**
  fills (you get hit when the move continues against you). Whether the earned spread beats the adverse
  selection is **the entire question, and 5m OHLC fundamentally cannot answer it.** It needs tick/order-book
  data (binance.vision `bookTicker`/`aggTrades`) or a live maker test.
- **Verdict: 5m MR is a genuine but UNPROVEN market-making edge** (resolved in #24c below).

#### #24c — RESOLVED with real tick data: 5m MR is a fee-tier edge, not capturable retail (2026-06-29)
Settled the spread-vs-adverse-selection crux by pulling real best-bid/ask. Downloaded one day of Binance
USDT-M `bookTicker` (`futures/um/daily/BTCUSDT/2024-03-15`, 300MB, **26.6M quotes**) and measured the spread,
then mapped net Sharpe across maker fee tiers. Raw: `experiments/intraday_meanrev/maker_fee_tiers.txt`.

- **Measured BTC perp spread: median 0.0147 bps, mean 0.048 bps** — i.e. **one tick** ($0.10 on $71k). The
  half-spread a maker could earn is **~0.007 bps ≈ zero.** BTC is the most liquid crypto instrument, so there
  is essentially **no spread to capture** — passive posting buys only the fee reduction, not price improvement.
- **Net Sharpe by maker fee tier (lb48 threshold, gross +0.90):**

| maker fee | net Sharpe | Binance um tier |
|----------:|-----------:|-----------------|
| 0.0 bp | +0.80 | VIP9 / rebate (~$25M+/mo vol) |
| 0.5 bp | +0.25 | VIP6–8 |
| 1.0 bp | −0.29 | VIP3–5 |
| 1.8 bp | −1.17 | VIP1–2 |
| **2.0 bp** | **−1.39** | **VIP0 (retail default)** |

- **RESOLUTION: the 5m edge is a FEE-TIER edge, not a signal edge.** Breakeven is ~0.5 bp maker → requires
  **VIP6+ (institutional volume)**. At the retail default (VIP0, 2 bp) it's **−1.39** and there is no
  spread-capture rescue because the spread is one tick. Even the +0.80 at 0 bp is optimistic (ignores queue/
  non-fill + adverse selection at the tightest tiers). **Real for HFT/market-makers with rebates;
  structurally unprofitable for retail.** This is *why* the leaderboard accounts don't run 5m MR, and why the
  firms that can don't post screenshots.
- **Final intraday verdict (closes #16/#24):** every intraday angle is now exhausted — trend is dead
  (fee-dominated, #16b), and mean-reversion is real but capturable only at institutional fee tiers (#24abc).
  **The daily trend book (`tstrend_multiwindow_aggr`, ~0.8–1.2 NET Sharpe at full 4.5 bp TAKER) is the only
  signal capturable with the fees a retail account actually pays.** Reusable: `fetch_binance_vision.py` now
  pulls spot/um/cm klines + markPrice; bookTicker via the S3 XML listing
  (`s3-ap-northeast-1.amazonaws.com/data.binance.vision?prefix=…`).

#### #24d — Forward runner for the 5m MR signal — ONE path, paper|live by flag (2026-06-29) — RUNNING
User: run a 5m runner first, MAKER orders to minimize fees, paper until it shows results, then go live.
`scripts/run_5m_meanrev.py` — polls live Binance USDT-M 5m klines (public `fapi`, no key for paper),
runs the MR signal (lb48, enter |z|>2 / exit |z|<0.5), and executes via a **pluggable broker**: identical
signal/accounting/logging, only the fill differs (the NFR1 "paper == live" principle — paper only predicts
live if it runs the live code, which matters DOUBLY here since the edge lives in execution).
- **MAKER fill model:** post a post-only limit at the signal bar's close; `PaperBroker` fills it iff the
  next bar's range reaches it (BTC spread ~0.015bp → ≈0 price improvement, so the maker win is the lower
  FEE 2.0bp vs 4.5 taker). `LiveBroker` posts a real GTX (post-only) limit via signed fapi REST + a
  `--max-loss` kill-switch — GUARDED (needs `--live --notional --max-loss --i-understand-live` + keys),
  wired but UNEXERCISED until the user flips it on with tiny size.
- **Why one file, not two (user's design call, correct):** the original `paper_5m_meanrev.py` was paper-only;
  refactored to a single `run_5m_meanrev.py` with `--live`. Behavior-preserving: refactored PaperBroker
  reproduces the prior replay to the digit (+2.878% net).
- **Maker vs taker (same ~3.5d replay window):** lowering fees 4.5→2.0bp halved the drag (1.8%→0.8%) →
  net +1.85%→+2.88%. (Caveat: PaperBroker posts AT the close so fill rate ≈100% — optimistic on fills,
  understates adverse selection; real fills will reveal the true rate. And 3.5d is noise — validates the
  machinery, NOT the edge; the 4.4y net-negative #24c verdict stands until weeks of live fills say otherwise.)
- **Account reality (checked live):** Binance `feeTier 0`, BNB-burn OFF, $665 futures — the exact −1.39
  Sharpe config. So this is a small ring-fenced *ground-truth* test, not a scale-up. Dockerized:
  `docker compose up -d paper-5m`; evaluate `cat state/paper_5m/summary.json`.
- Next per user: the DAILY runner for the core `tstrend_multiwindow_aggr` book.

#### #24e — Does disciplined scale-in (tranche averaging-down) help the 5m MR? — NO (2026-06-29) ✗
User asked whether to buy more as price drops further (expecting a stronger reversion) before changing the
runner. Backtested on the full 4.4y 5m data (`scripts/intraday_scalein.py`): fixed 1-tranche (|z|>2) vs
scale-2 (add at |z|>3) vs scale-3 (add at |z|>3,4); tranches ratchet, exit all at |z|<0.5; maker 2bp.
Raw: `experiments/intraday_meanrev/scalein.txt`.

| variant | GROSS Sharpe | net ret | maxDD | avg\|pos\| |
|---------|-------------:|--------:|------:|----------:|
| **fixed (\|z\|>2)** | **+0.90** | −93% | −94% | 0.43× |
| scale-2 (>2,3) | +0.78 | −98% | −99% | 0.63× |
| scale-3 (>2,3,4) | +0.81 | −99% | −99% | 0.69× |

- **Result — scale-in HURTS, and it's a signal problem not a fee problem.** GROSS Sharpe *falls* (0.90→0.81)
  before fees even enter: the first tranche (|z|>2) is where the reversion edge lives; deeper dislocations
  (|z|>3,4) are disproportionately **continuations / regime breaks**, so adding size there dilutes the edge
  with the worst-quality bets. Net return and maxDD both get worse. (Ignore net-Sharpe wobble — a
  leverage/vol-drag artifact when every variant loses 90%+.)
- **Verdict: keep the runner FIXED-SIZE — averaging down is the #20/#21 trap confirmed for this signal.**
  "Buy more when cheaper" feels smart but concentrates size into the moves most likely to keep going. No
  change to `run_5m_meanrev.py`. (Testing it is what kept a worse strategy out of the live runner.)

#### #26 — 5m MR across coins + spread/adverse-selection — XRP is the one candidate (2026-07-01)
User: add more coins (SOL/ETH/DOGE/XRP/XMR…). `scripts/multicoin_meanrev.py` ran the SAME a-priori threshold
MR on each (bvision 5m 2022-26), then measured REAL spreads (bookTicker) + adverse selection (aggTrades).
Raw: `experiments/multicoin_meanrev/`.

| coin | gross Sh | net@2bp | quoted spread | realized@1s (maker keeps) | verdict |
|------|---------:|--------:|--------------:|--------------------------:|---------|
| BTC | +0.90 | −1.29 | 0.015 bps | ~0 | dead (no spread) |
| SOL | +0.75 | −0.39 | 0.078 bps | ~0 | dead (no spread) |
| ETH | **−0.42** | −2.11 | — | — | dead (no MR signal — ETH trends) |
| DOGE | +0.90 | −0.23 | 0.70 bps | **−0.68 bps (−193%)** | **dead — passive maker PICKED OFF** |
| **XRP** | +0.76 | −0.54 | 1.63 bps | **+0.74 bps (+91%)** | **CANDIDATE** |

- **Coin-specific.** MR signal is real on BTC/DOGE/SOL/XRP (+0.75–0.90), NOT ETH (−0.42, it trends). XMR
  delisted from Binance (privacy-coin removal 2024). Alts' higher vol dilutes the fixed fee → net closer to
  breakeven than BTC even before spread.
- **Spread ≠ free money — it's adverse-selection compensation.** Measured realized spread (what a maker keeps
  after price moves against fills): **DOGE −0.68bps (picked off — a passive maker LOSES money on DOGE)** vs
  **XRP +0.74bps (~91% of half-spread captured).** Microstructurally opposite despite both being "wide-spread
  alts". DOGE's wide spread is a danger sign; XRP's noisier/less-informed flow makes its spread harvestable.
- **XRP = the first plausibly-viable 5m config at retail:** real MR signal + capturable ~0.7bps spread →
  eff fee ~1.31bp → net ~−0.09 @2bp maker, marginally **positive @1.8bp (BNB burn on)**.
- **Verdict: CANDIDATE (XRP only), not confirmed.** Caveats: 1-day/2h adverse-selection sample; general-flow
  proxy (MR's own fills may be more adverse); positive only WITH BNB burn; fill-rate/non-fills unmodeled. The
  user's multi-coin instinct found the one door ajar — but it needs multi-day spread confirmation + a proper
  MR-specific maker-fill sim before risking money. BTC/SOL/DOGE/ETH all closed.

### #25 — Profit-skim vs compounding on the daily core book (2026-06-29)
User: if EOD balance > base, withdraw the excess (1000→1100 → bank 100) to lock profits. Quantified on the
aggressive daily book (`tstrend_multiwindow_aggr` 0.40/6x, 2014-26) — same return stream, only the capital
base differs. `scripts/profit_skim.py`; raw `experiments/profit_skim/skim.txt`.

| policy | total wealth | CAGR | banked (safe) | at-risk end | total maxDD |
|--------|-------------:|-----:|--------------:|------------:|------------:|
| **compound** | **38.7×** | 36.4% | — | 38.7× | −44% |
| skim-50% (above fixed base) | 4.8× | 14.2% | 3.8× | 0.94× | −33% |
| skim-100% | 4.7× | 14.1% | 3.8× | 0.93× | −32% |

- **Compounding makes ~8× more** (38.7× vs 4.8× over 11.8y) — the geometric-growth engine. Skimming switches
  it off: the trading account never grows (oscillates near base), you bank a drawdown-PROOF ~3.8× pile and
  cut TOTAL-wealth DD 44%→33%, but convert a 36% compounder into a ~14% income stream + reserve.
- **skim-50% ≈ skim-100%** (4.8 vs 4.7×) — because both skim above a FIXED base, so the fraction barely
  matters; the base never grows. Real "income AND growth" needs skimming above a GROWING base (untested knob).
- **Verdict: for the +EV daily book, DON'T full-skim** — it forfeits the 8× that justifies running it; skim a
  small fraction above a growing base, or compound + take lump sums on need. (N/A to the −EV 5m book, where
  skimming is pure defense — nothing to compound.) CAGR full-sample-optimistic; ranking durable.

### #22 / #23 — "adjust the math to the current regime, online" (2026-06-28)
User's hypothesis: the book uses fixed math; what if it adapted to the regime while running? First, what
it ALREADY adapts: position size scales `target_vol / trailing_realized_vol` (per-asset + 60d overlay +
trailing-cov cluster sizing) — so it de-levers in high-vol regimes already. What it does NOT adapt: trend
QUALITY (chop vs clean) and the leverage/Kelly fraction. Tested both, baseline-first, vs the static
multiwindow candidate (0.20/2×). `scripts/adaptive_regime_experiment.py`; raw `experiments/adaptive_regime/`.
ER gate built into `sleeved_target_weights(er_window=…)` (off by default; 76 tests pass).

| variant | Sharpe | PSR | WF median | WF %+ | WF worst | boot CI | maxDD |
|---------|-------:|----:|----------:|------:|---------:|--------:|------:|
| baseline (static) | **1.21** | 1.000 | +0.97 | 83% | −1.05 | [0.65, 1.73] | −24.5% |
| **#22** trend-quality gate (ER, a-priori) | 1.19 | 1.000 | **+1.45** | 83% | −1.13 | [0.64, 1.74] | −25.0% |
| **#23** adaptive Kelly leverage (online) | **0.78** | 0.987 | **−0.16** | **50%** | **−2.33** | **[0.22, 1.35]** | **−39.4%** |

- **#22 (trend-quality gate) — NEUTRAL.** Reused the EXACT a-priori soft ER gate that lifted the *engine*
  btc_1d (#2): ER window 20, thresholds 0.15/0.45, scale forecast by the ER weight. On the panel it's a
  wash: full Sharpe 1.21→1.19, PSR/CI/%-positive unchanged, WF *median* nicer (+0.97→+1.45) but the *worst*
  block slightly worse (−1.05→−1.13) and maxDD ~flat. **Diagnosis: the panel's vol-targeting already captures
  most of what an ER gate would add** — the engine needed it (single asset, no vol overlay); the diversified
  vol-targeted panel doesn't. Doesn't hurt, doesn't clearly help → not worth the added complexity.
- **#23 (adaptive Kelly leverage) — DISIMPROVED, badly.** Scaling the book by its trailing-126d realized
  Sharpe (a-priori: target 1.0, mult clip [0,2]) wrecks everything: Sharpe 1.21→**0.78**, WF %-positive
  83%→**50%**, worst block −1.05→**−2.33**, maxDD −24.5%→**−39.4%**, CI lower 0.65→0.22. **Same failure mode
  as the #15 DD-throttle:** performance-reactive sizing LAGS the regime — it levers up after a good run (just
  before the mean-reversion) and de-levers after a drawdown (just before the trend's recovery). In a trend
  book, reacting to your own recent P&L sells low and buys high.
- **Verdict: the user's instinct was worth testing and the test is decisive — the *defensible* adaptivity
  (vol-targeting) is ALREADY in the book; adding a trend-quality gate is neutral, and online performance-
  reactive leverage HURTS.** This is now the THIRD independent confirmation (with #2 hysteresis and #15
  throttle) of the project's core lesson: **pre-committed/robust survives; reactive/fitted deflates.** Keep
  the static `tstrend_multiwindow_aggr.toml`. The `er_window` knob stays available (off) for the record.

**Bottom line written down for reference:** the leaderboard number is not reproducible as a *strategy*; it's
leverage + survivorship. The reproducible path to large *dollars* is #13–#14 (scale the validated edge via
prudent leverage + compounding over time), with #17–#18 to keep the fantasy quantified and #19–#21 as a
contained outlet for risk appetite. Start #13.
