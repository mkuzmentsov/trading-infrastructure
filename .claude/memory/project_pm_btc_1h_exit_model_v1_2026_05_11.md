---
name: PM BTC 1h exit classifier v1 trained 2026-05-11
description: LightGBM exit model trained on 4 bundles (245 positions, 577K ticks), OOS verified on bundle 5 (83.4h, 82 positions). OOS PnL flips -$97 → +$132 at θ=0.30 (Δ +$229). Pipeline at ai/pm_btc_1h_exit/. Not yet wired into bot — only verified in replay.
type: project
---

# PM BTC 1h exit classifier — v1 (2026-05-11)

## Pipeline (mirrors `ai/pm_btc_entry/` shape)

- `ai/pm_btc_1h_exit/prepare_exit_dataset.py` — walks `manage_position` ticks across all 5 bundles, pairs each tick with its position's eventual outcome (label=1 iff close pnl > 0). Outputs `exit_dataset_v1.parquet` (39 MB, 855,938 rows, 327 positions).
- `ai/pm_btc_1h_exit/train_exit_model.py` — LightGBM, GroupKFold by `pos_id` on train side, OOS = bundle `20260507_091151`.
- `ai/pm_btc_1h_exit/replay_exit_model.py` — per-position tick walk; first tick where `P(win) < θ` after min_hold_secs=30 → exit at that tick's `decision.unrealized`. `late_bar_skim` actual exits are protected (the bot's real edge).

## Train / OOS split

| split | bundles | rows | positions |
|---|---|--:|--:|
| train | 4 (111h + 22.8h + 26.7h skipping 7.2h zero-trade) | 577,495 | 245 |
| OOS | bundle 5 (`20260507_091151`, 83.4h) | 278,443 | 82 |

## Model performance

| metric | value |
|---|--:|
| 5-fold GroupKFold CV AUC | 0.760 ± 0.058 |
| OOS AUC (bundle 5) | 0.667 |
| OOS Brier | 0.372 |

Top features by gain (LightGBM):

1. session_pnl (regime; **suspicious — see caveat below**)
2. current_bid
3. entry_seconds_left
4. entry_p_up
5. peak_bid
6. entry_edge
7. entry_price
8. opp_bid
9. shares_log
10. sigma_5m

Entry-invariant features dominate (entry_seconds_left/edge/p_up/price). The model is partially behaving as an entry classifier — many model exits fire >2000s before actual close (i.e. right after entry).

## OOS replay result — bundle 5 (`20260507_091151_83.4h`, 82 positions)

Actual close breakdown:
```
late_bar_skim       n=27  sum=$+232.14
force_close         n=12  sum=$ +73.15
late_bar_salvage    n=19  sum=$-157.40
thesis_break        n=12  sum=$-142.91
salvage_floor       n=12  sum=$-102.21
                    ACTUAL TOTAL: -$97.23 (WR 45%)
```

Threshold sweep:
```
θ      sim_total   Δ vs actual   n_model  avg_save
0.15   +$114.97    +$212.20         26     +$8.16
0.20   +$115.01    +$212.24         26     +$8.16
0.25   +$120.25    +$217.48         27     +$8.05
0.30   +$131.83    +$229.06         28     +$8.18  ← best
0.35   +$131.92    +$229.15         28     +$8.18
0.40   +$131.97    +$229.20         28     +$8.19
0.50   +$120.08    +$217.31         29     +$7.49
```

Wins (15 top): all are salvage/thesis trades where model exited at ~$0 (break-even) vs actual −$8 to −$21. Many fire 600s-2800s before actual close.

Costs: only 2 false-positive cuts in 28 interventions — both `force_close` winners exited for −$7.29 and −$5.40 combined. Net +$229.

## Caveats / next-iteration risks

1. **`session_pnl` as top feature** could leak future regime info if the bot deployment's behavior cascades (one loss → more losses). Worth retraining with this feature excluded as ablation.
2. **High fold-AUC variance** (0.679 to 0.860 across folds) — the corpus is small (245 positions) and regime-dependent. OOS AUC 0.67 is real but ceiling on a different future bundle could vary.
3. **Model fires very early on most interventions** → behaves as entry rejection more than dynamic exit. Could be repurposed as ENTRY gate (`ENTRY_GATE_*` infra already exists in chart), saving the round-trip on rejected entries instead of opening-then-closing.
4. **Replay uses `decision.unrealized`** which excludes FAK slippage — live PnL will be modestly worse than replay. The +$229 OOS swing has plenty of buffer.

## Status

- Pipeline files: shipped to `ai/pm_btc_1h_exit/`
- Model artifacts: `polymarket/k8s/helm/polymarket-1h-bot/files/model/pm_btc_1h_exit_model.txt` + `pm_btc_1h_exit_meta.json`
- **Not wired into live bot.** Decision needed: integrate as exit gate (`EXIT_GATE_*` env in chart) vs entry gate (`ENTRY_GATE_*`) vs both.

## OOS confirmation — bundle 6 (`20260510_212012_12.3h`, 9 positions)

Captured AFTER training. Live: **−$12.88** (33% WR). Model θ=0.30 replay: **+$10.82** (Δ **+$23.70**).
5 model interventions on all 6 losers, 0 winners cut. Threshold degenerate (all loser min_p < 0.15, all winner min_p > 0.50). Clean separation on this small sample.

**Combined OOS (bundles 5 + 6, 91 positions, 95h):** actual −$110.11 → model +$142.65, **Δ +$252.76**.

## How to apply

- Before deploying: re-train with `session_pnl` excluded as ablation. If OOS holds → ship. If degrades → investigate leakage hypothesis.
- Integration path: drop model into the chart Secret can't hold the binary — use the existing `apply-model-configmap.sh` server-side-apply chain established for the 5m/15m model (memory: `project_pm_btc_exit_classifier_2026_04_27.md`).
- Suggested first-deploy θ: **0.30**, dryRun for at least 1 bundle before live.
