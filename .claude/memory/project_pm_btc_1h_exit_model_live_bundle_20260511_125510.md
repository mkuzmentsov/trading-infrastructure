---
name: PM BTC 1h exit model v1 — live bundle 20260511_125510_5.4h
description: First non-trivial live bundle of exit-model v1 (θ=0.70). 5 trades, all closed by model in 27-29s, net −$1.84. Replay uninformative (live closes precede 30s min_hold). Per-tick trace shows model is in degenerate near-zero state on every position (no winner/loser discrimination). Likely session_pnl self-reinforcing loop or post-CLOB-v2 regime drift.
type: project
---

# PM BTC 1h exit model v1 — first live bundle (2026-05-11)

Bundle: `polymarket/logs/1h/btc/pm-logs_pm-btc-1h-smart_20260511_125510_5.4h`
Model: v1 (`pm_btc_1h_exit_model.txt`), threshold `SMART_EXIT_MODEL_THRESHOLD=0.70`.

## Live result

| | |
|---|---:|
| Trades | 5 |
| WR | 20% (1 win, 1 break-even, 3 losses) |
| Net PnL | **−$1.84** |
| All close reasons | `model_exit` |
| Held duration | 27–29s (all 5) |

Per position:

| # | Dir | Entry | Bid path | Closed | p_win first→last |
|---|---|--:|---|--:|---|
| 1 | UP | 0.71 | 0.70→0.68 | −$0.47 | 6e-7 → 2e-7 |
| 2 | DOWN | 0.67 | 0.66→**0.61** | −$1.14 | 3e-7 → 2e-7 |
| 3 | DOWN | 0.61 | 0.61→0.60 | −$0.44 | 6e-9 → 9e-9 |
| 4 | UP | 0.65 | 0.64→**0.66** | **+$0.21** | 4e-7 → 4e-7 |
| 5 | UP | 0.69 | 0.68→0.69 | $0.00 | 6e-7 → 7e-7 |

## Replay = actual (uninformative)

`replay_exit_model.py` on this bundle returned −$1.84 across all θ ∈ {0.15…0.90}: 0 model fires in replay. Two reasons compound:
1. Actual close `model_exit` is treated as the canonical exit — no simulation needed.
2. Replay's `min_hold_secs=30` blocks firing in the 0–30s window; all 5 live closes happened at 27–29s.

So this bundle can't be used to evaluate "model vs no-model" via the existing replay tool. Need to (a) capture a bundle where actual closes are mixed (skim / force_close + model_exit) or (b) write a counterfactual sim that extrapolates bid beyond actual close.

## The interesting finding — model is degenerate

**Every prediction across all 282 ticks is p_win ≈ 0** (range 6e-9 to 7e-7). The model gives Pos 4 (winner +$0.21) and Pos 2 (loser −$1.14) virtually identical scores. No discrimination.

OOS bundle 5 (training memo, `project_pm_btc_1h_exit_model_v1_2026_05_11.md`) had 28/82 = 34% fire rate with spread probabilities. Here we have 5/5 = 100% fire rate, all clustered at p_win=0. Behavior is qualitatively different.

## Hypotheses

1. **`session_pnl` self-reinforcing loop.** Top feature by gain in v1. Once session_pnl turns negative early in the session, every subsequent prediction skews toward "loss", model fires, position gets cut, session_pnl stays negative → loop. — **Tested 2026-05-11 (see below): v2 ablation is degenerate in OPPOSITE direction (p_win 0.75-0.99 on everything). session_pnl isn't the root cause; it's covering for general model overfitting.**
2. **Post-CLOB-v2 regime drift.** Training corpus is mostly pre-v2 (cutover May 6). Bundle is May 11. Feature distributions for `current_bid`, `entry_seconds_left`, book features may have shifted.
3. **Insufficient training data on extreme p_win=0 region.** Model never saw enough "actual losers caught early" — when test conditions match this region, output saturates.

## v2 ablation replay (2026-05-11)

Ran `pm_btc_1h_exit_model_v2_no_session_pnl.txt` on same bundle.

| feature | v1 (with session_pnl) | v2 (no session_pnl) |
|---|---|---|
| p_win range across 282 ticks | 6e-9 to 7e-7 | 0.7545 to 0.9957 |
| p_win mean | ≈0 | 0.955 |
| Fires @ θ=0.70 (deployed), min_hold=5s | 5/5 | 0/5 |
| Fires @ θ=0.85, min_hold=5s | 5/5 | 2/5 |
| Sim PnL @ best (min_hold=5) | +$0.02 | −$1.56 |

**Both models are saturated, in opposite directions.** v1 says all-loser; v2 says all-winner. Removing `session_pnl` doesn't fix the structural problem — it shifts which feature subset drives the saturation (entry-time features dominate v2, predicting "good entry → win" universally).

**Don't ship v2.** On this regime it's effectively "no model"; on clean regimes (bundles 5+6) it's strictly worse than v1.

## What to do next (none of this done yet)

- ~~Replay v2 (no-session_pnl) model on this bundle~~ — DONE, both v1 and v2 saturated (different directions). See v2 ablation section above.
- Feature drift audit: distributions of top-10 features in this bundle vs train corpus.
- Wait for ≥10 model_exit fires (multiple bundles) before deciding θ retune vs retrain.
- **Higher priority now (since session_pnl wasn't the cause):**
  - Retrain on full corpus including post-CLOB-v2 data (this bundle + future bundles) with a calibration-aware regularizer (penalize p_win extremes).
  - OR add an inference-time safety: if last N ticks of model show ALL p_win < 1e-3 (or all > 0.99), treat as degenerate, fall back to static rules.
- Consider entry-gate use of v1 instead of exit-gate. The "every position p_win=0 from tick 0" output behaves more like "should never have entered" — block at entry instead of opening then immediately closing.

## How to apply

If a future live bundle shows the same degenerate pattern (all p_win ≈ 0, fire rate 100%):
- Don't tune θ — there's no spread to tune over.
- Either (a) swap to v2 (no-session_pnl), (b) retrain with new bundles, or (c) escalate to an entry gate.

If subsequent bundles show 30–40% fire rate with mixed reasons (skim survives), v1 is working as intended and this bundle was just a small-sample regime outlier.
