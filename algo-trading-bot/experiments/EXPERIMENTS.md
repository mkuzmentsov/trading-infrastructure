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
