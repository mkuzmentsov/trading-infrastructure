---
name: PM BTC 1h strategic diagnosis 2026-05-11 — entry signal is exhausted
description: Across 5 bundles / 327 live trades / 240h, skim-winners and salvage-losers are statistically identical at entry. Salvage exits are 0% WR by construction (-$948). No entry-side knob can close the gap; decision must move to in-position model. Trend-fight gate has wrong sign in current regime.
type: project
---

# PM BTC 1h — what the live logs actually say (2026-05-11)

## Corpus
5 bundles in `polymarket/logs/1h/btc/`: 111h + 22.8h + 7.2h + 26.7h + 83.4h, total ~240h.
**327 paired open/close trades. Live PnL: −$354.**

(Replay on the same corpus with current YAML: +$227 per the 2026-05-10 sweep. The live/replay gap is partly older strategy versions running during early bundles, partly FAK slippage replay doesn't model.)

## Breakdown by close reason

| reason | n | sum | avg | WR |
|---|--:|--:|--:|--:|
| `late_bar_skim` | 176 | **+$546** | +$3.10 | 91% |
| `force_close` | 16 | +$55 | +$3.47 | 75% |
| `late_bar_salvage` | 58 | **−$347** | −$5.98 | 0% |
| `thesis_break` | 39 | **−$333** | −$8.53 | 0% |
| `salvage_floor` | 34 | **−$247** | −$7.27 | 0% |
| `salvage_velocity` | 4 | −$21 | −$5.27 | 0% |

The bot has ONE real edge (`late_bar_skim` deep-ITM exits) and FOUR bleed channels.

## The killer finding — entry signatures are indistinguishable

Median feature values at entry:

| feature | SKIM winners (n=176) | SALVAGE losers (n=135) |
|---|--:|--:|
| entry_price | 0.68 | 0.67 |
| entry_edge | 0.26 | 0.27 |
| sec_left | 2569 | 2880 |
| sigma_5m | 0.00057 | 0.00059 |
| \|ret_30m\| | 0.00091 | 0.00096 |
| with-trend % | 81% | 84% |

**No entry-time feature discriminates them.** Every entry knob we've tuned (shrinkage, min_z, peak_flat, entry_ceil, late_ceil) is picking thresholds blind. This explains why each new gate helps one bundle and hurts another. **Heuristic entry tuning is exhausted on this corpus.**

## The trend-fight gate has the wrong sign

| direction × trend | n | sum | avg |
|---|--:|--:|--:|
| WITH-trend strong (\|r30m\|≥0.15%) | 92 | **−$140** | −$1.52 |
| WITH-trend mild | 128 | **−$110** | −$0.86 |
| flat | 83 | −$118 | −$1.43 |
| AGAINST-trend mild | 21 | **+$11** | +$0.52 |
| AGAINST-trend strong | 3 | +$3 | +$1.13 |

Current `smartSkipTrendfightRet30m=0.0010` blocks AGAINST-trend entries (the small positive bucket) and lets WITH-trend chase through (the −$250 bleed). The gate should be a CHASE gate (block WITH-trend when |ret_30m| big), not a contra-trend gate.

## Why salvage exits are 0% WR

Each salvage rule (floor, velocity, late_bar, thesis_break) is reactive to an absolute bid threshold. By definition the rule fires when bid has already collapsed; the exit locks in the bottom. Avg −$5.98 to −$8.53 per trade. Not a quirk — the rules CAN'T win because they only fire when underwater. Holding to expiry on the same trades would average ~−$13 (full loss of spend), so salvage saves ~$5/trade vs hold-to-expiry, but the absolute volume of bleed (−$948) still eats the skim profit.

## ML gates verified inactive on 1h

- `polymarket-1h-bot/files/model/` — empty, no model files
- `ENTRY_GATE_THRESHOLD` env defaults to "0" (inactive)
- Exit-gate preload runs at startup but loads nothing
- The April exit classifier (commit f2df2cc) trained on 5m/15m data, not loaded for 1h

## Strategic conclusion

Two-prong rewrite, replay-validated before ship:

**Prong 1 — Train a 1h per-tick exit classifier.** Replaces all 4 static salvage rules. Training data already exists: 1.63M `manage_position` ticks in `logs-training.jsonl` + outcome labels from `logs-training-events.jsonl`. LightGBM, predict P(skim-win | current state), exit when P < θ. Split: bundles 1-4 train, bundle 5 (83h) OOS.

**Prong 2 — Flip trend-fight gate into chase gate.** Block WITH-trend entries when |ret_30m| > θ AND direction matches BTC trend. Sweep θ 0.0010-0.0030.

## What NOT to retry (proven not to help on this corpus)

- More shrinkage / min_z_early / peak_flat sweeps (already at the ridge)
- SMART_CALIB_ALPHA > 0 (rejected this morning, kills skim revenue)
- Multi-asset rollout before BTC profitable
- Salvage threshold tweaks (they need REPLACEMENT, not tuning)

## How to apply
- Build the exit-model pipeline at `ai/pm_btc_1h_exit/` mirroring `ai/pm_btc_entry/` shape.
- Drop trained model into `polymarket-1h-bot/files/model/` (use the existing apply-model-configmap.sh chain — Helm release Secret can't hold model binary).
- Keep `EXIT_GATE_*` envs gated; default off; only enable after replay shows net positive vs all 4 static rules across 4 train bundles + OOS bundle 5.
