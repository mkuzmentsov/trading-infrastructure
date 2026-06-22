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
