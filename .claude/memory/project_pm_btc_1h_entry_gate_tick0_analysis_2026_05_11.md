---
name: PM BTC 1h entry-gate tick-0 analysis 2026-05-11
description: Two-bundle OOS test of "reuse v3-exit at entry time" idea. Bundle 1 (n=197): +$98 at thr=0.50. Bundle 5 (n=82): +$94 at thr=0.60. Signal real but modest (~$0.70/position) and bundle-dependent. NOT deployed — recommended either conservative thr=0.85 experiment or build dedicated entry model.
type: project
---

# PM BTC 1h entry-gate tick-0 analysis (2026-05-11)

## Setup

Premise: v3 exit model fires within 30s of entry on most "would-be loser" positions. Hypothesis: if we evaluate v3 against the FIRST-tick features pre-entry, we can skip the entry entirely and save fees + slippage.

For each position in the 7-bundle corpus, took the tick with smallest `time_held` (~0.2s after open) as proxy for pre-entry state. Predicted v3 `p_win` on those features. Bucketed by `p_win`, computed counterfactual PnL if we'd skipped entries above `p_loss > THRESHOLD`.

## OOS validation (only real signal)

Trained two leave-one-out v3 variants:
- `pm_btc_1h_exit_model_v3_oos_bundle5.txt` — bundle 5 (n=82) held out
- `pm_btc_1h_exit_model_v3_oos_bundle1.txt` — bundle 1 (n=197) held out

In-sample tick-0 buckets show >97% WR separation — that's memorization, not signal. OOS results below are the real measure.

### Bundle 1 OOS (n=197, actual −$207)

| thr | n_skip | pnl_skip | pnl_kept | Δ | kept_WR | $/kept |
|---:|---:|---:|---:|---:|---:|---:|
| 0.50 | 59 | −$98 | −$109 | +$98 | 59% | −$0.79 |
| 0.60 | 40 | −$63 | −$144 | +$63 | 58% | −$0.92 |
| 0.70 | 22 | −$36 | −$171 | +$36 | 57% | −$0.98 |
| 0.85 | 8 | −$10 | −$197 | +$10 | 56% | −$1.04 |
| 0.95 | 1 | +$4 | −$211 | −$4 | 55% | −$1.08 |

**Bucket non-monotonicity:** "high p_win" bucket [0.90, 1.0) has 64% WR and −$15 PnL. Model's confident "winners" don't actually win.

### Bundle 5 OOS (n=82, actual −$97)

| thr | n_skip | pnl_skip | pnl_kept | Δ | kept_WR |
|---:|---:|---:|---:|---:|---:|
| 0.50 | 46 | −$84 | −$13 | +$84 | 50% |
| 0.60 | 42 | −$94 | −$3.5 | +$94 | 52% |
| 0.80 | 28 | −$84 | −$14 | +$84 | 48% |
| 0.85 | 18 | −$91 | −$6 | +$91 | 50% |
| 0.95 | 3 | +$17 | −$114 | −$17 | 44% |

**Bucket pattern cleaner:** losers cluster in [0.10, 0.20) with WR 35% and −$84.

### Combined (279 OOS positions)

| Strategy | thr | Bundle 1 Δ | Bundle 5 Δ | Combined Δ |
|---|---:|---:|---:|---:|
| Conservative | 0.85 | +$10 | +$91 | **+$101** |
| Moderate | 0.70 | +$36 | +$86 | +$122 |
| Aggressive | 0.50 | +$98 | +$84 | +$182 |
| Too tight | 0.95 | −$4 | −$17 | −$21 |

Average improvement: **~$0.36–0.65 per position** depending on threshold.

## Caveats

1. **Bundles disagree on optimal threshold** (Bundle 1 wants 0.50; Bundle 5 fine anywhere 0.60-0.85). A single fixed threshold compromises.
2. **Kept PnL stays negative** on both bundles even at best threshold. Entry gate trims worst-case losses but doesn't make the bot profitable.
3. **Bundle 1's calibration is poor** — model's [0.90, 1.0] bucket has 64% WR (only 9 pp above random). The signal at tick 0 is weak on this bundle.
4. **Replay savings already include post-exit-gate PnL** — i.e., the skipped −$84 on bundle 5 represents what the bot lost after the exit gate cut it. The entry gate adds fee savings (~$15-30/bundle) on top.

## Why NOT ship immediately

1. **Modest magnitude.** ~$0.36-0.65/position improvement OOS.
2. **Exit gate already catches most losers.** The marginal value is fee/slippage savings on rejected entries, not the bulk of the loss-avoidance.
3. **Dedicated entry model is the right tool.** v3 was trained on in-flight ticks; tick-0 features are a constrained sub-region. A model trained directly on `position_opened` events with richer entry features (entry book depth, recent multi-position context, regime indicators) should generalize better.

## Recommendations (not yet executed)

**Option X — Conservative experiment:**
Wire v3-prod into entry path. Set `ENTRY_GATE_THRESHOLD=0.85`. Skips only the most-confident losers (~3-10% of entries). Validates plumbing while building the dedicated model. Expected: ~$10-100/bundle improvement + fee savings.

**Option Y — Build dedicated entry model (cleaner):**
Use existing scaffolding at `ai/pm_btc_entry/` (built 2026-04-27 for 5m bot). Adapt for 1h bundles. Train on entry-time features only:
- Entry-time: entry_p_up, entry_edge, entry_seconds_left, sigma_5m, btc_ret_30m, session_pnl
- Pre-entry book: ask, ask_size, bid, bid_size, spread, imbalance
- Regime: wr_30min, recent volatility, position cadence

Probably 1-2 days. Cleaner than reusing exit-model tick-0 features.

**Default if uncertain — defer.** v3 exit gate just deployed today; let it accumulate 3-5 more bundles of live data before adding another model in the path.

## Files (untracked)

- `ai/pm_btc_1h_exit/pm_btc_1h_exit_model_v3_oos_bundle1.txt` — leave-bundle-1-out v3 model
- `ai/pm_btc_1h_exit/pm_btc_1h_exit_model_v3_oos_bundle5.txt` — leave-bundle-5-out v3 model

## How to apply

If a future analysis needs an entry-time scoring of a model: take the first tick of each position from `manage_position` logs (smallest `time_held` per pos_id) and predict. That replicates what an entry gate would compute pre-trade.
