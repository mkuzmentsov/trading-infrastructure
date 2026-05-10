---
name: PM BTC 1h fat-tail model overconfidence 2026-05-08
description: Math model is severely fat-tail-blind at extreme p_up. Real moves on losers are 3-4× implied sigma; "95% confident" bets win 50-63% in reality. This is the structural cause of the −$363 corpus bleed.
type: project
---

**Core finding:** the bot's directional model (math_smart) uses Gaussian assumptions that fail catastrophically at the extremes where the bot makes ~95% of its bets.

## The numbers

Across 271 corpus trades (187h, live PnL −$363):

| Model says | n | Actual WR | Calibration gap |
|---|---|---|---|
| "Very confident UP" (p_up ≥ 0.90) | 131 | **63%** | model claims ~95%, off by **−32 pp** |
| "Very confident DOWN" (p_up ≤ 0.10) | 127 | **50%** | model claims ~95%, off by **−45 pp** |
| Medium confidence (0.10 < p_up < 0.90) | 13 | 15% | — |

**258 of 271 trades (95%) are at the extremes.** The model never produces moderate-confidence signals — it always thinks it's nearly certain. And at those extremes its calibration is wildly off.

## Sigma underestimates fat tails

Compared actual `|btc_move from entry to close|` against `sigma_5m × √time_remaining`:

```
extreme losers (pnl<-$5):  actual / implied_σ   p25=2.91  p50=3.77  p75=4.36
big winners (pnl>$5):      actual / implied_σ   p25=0.71  p50=1.74  p75=3.49
```

When a trade loses big, BTC moves **3-4 standard deviations** beyond what the model expected. The Gaussian assumption built into `_compute_signal` (math_smart.py:262, `_norm_cdf(z)`) is the problem — it assigns near-zero probability to 3σ events that occur ~30% of the time on losers.

## Why this matters

The bot bets $22 at 0.70 expecting BTC to drift further on-thesis. Real BTC paths mean-revert $124 (median reversal magnitude on losers, in $-terms at BTC≈80K). The position halves. Model confidence at p_up=0.95 implies a payoff that exists only in the model's imagination.

## What this rules out

- **Knob retunes** (skim, ceil, min-elapsed, peak-flat, chop-ratio) cannot fix a miscalibrated edge. Four corpus sweeps confirmed this.
- **Kelly sizing changes** don't help — the bet cap binds for nearly all trades; the real problem is the cap-sized bets are placed on trades where edge is fictional.

## What might work

1. **Shrink p_up at extremes** — apply additional shrinkage when `|p_up - 0.5| > 0.4`. The bot's `SMART_SHRINKAGE` already shrinks toward 0.5 but not enough.
2. **Use a fat-tailed distribution** for fair-probability calculation — Student-t with low df, or empirical historical CDF instead of `_norm_cdf`.
3. **Separate sigma estimator** for tail-prediction vs central-tendency. `sigma_5m` is too short a window to see fat-tail behavior.
4. **Block bets when `|p_up - 0.5| > X` AND `sigma_5m > Y`** — see [killer quadrant memory](project_pm_btc_1h_killer_quadrant_2026_05_08.md).

## How to apply

When considering ANY change to math_smart's entry logic, remember: the underlying model is mis-calibrated by 30-45 percentage points at the extremes. Tighter knobs around a broken model are second-order. The first-order fix is calibration. Until that's fixed, treat all model-derived edges with skepticism — especially when `|p_up - 0.5| > 0.4`.
