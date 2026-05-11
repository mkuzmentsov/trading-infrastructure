---
name: PM BTC 1h exit model v3 deployed to production 2026-05-11
description: v3 (label-smoothed, 7-bundle full-corpus refit) shipped to pm-btc-1h-smart at threshold 0.50 (down from v1's 0.70). Commit 0c42d681. Fixes v1's degenerate p_win≈0 saturation observed on bundle 20260511_125510.
type: project
---

# PM BTC 1h exit model v3 — DEPLOYED 2026-05-11

**Commit:** `0c42d681a9ff5d506f86e9a74e7d9fc8fa1c6da7` ("add ml gate")
**Release:** `pm-btc-1h-smart` (namespace `polymarket`)
**Chart:** `polymarket/k8s/helm/polymarket-1h-bot`

## What shipped

| Artifact | Path | Detail |
|---|---|---|
| Model binary | `polymarket/k8s/helm/polymarket-1h-bot/files/model/pm_btc_1h_exit_model.txt` | v3 full-corpus refit (no holdout) — 907 KB (no gzip needed) |
| Model meta | `polymarket/k8s/helm/polymarket-1h-bot/files/model/pm_btc_1h_exit_meta.json` | features list + CV AUC 0.7598 |
| Threshold | `polymarket/k8s/helm/bots/pm_btc_1h_smart.yaml` | `smartExitModelThreshold: "0.50"` (was 0.70) |

## Training summary (v3-prod, full corpus)

- Dataset: `ai/pm_btc_1h_exit/exit_dataset_v3.parquet` (7 bundles, 884,460 ticks, 341 positions, label mean 0.632)
- Hyperparameters:
  - `objective=cross_entropy`, label smoothing ε=0.05 (effective output range [0.05, 0.95])
  - `num_leaves=15`, `max_depth=6`, `min_data_in_leaf=500`, `lambda_l2=0.1`
  - 5-fold GroupKFold by `pos_id`
- **CV AUC: 0.760 ± 0.076** (vs v1's 0.760, parity in CV)
- In-sample (full refit) AUC=1.000 (expected — pos_id-correlated features memorize)
- Top features by gain: `session_pnl`, `current_bid`, `entry_seconds_left`, `entry_edge`, `entry_p_up`

## Why threshold 0.50

Bot semantics: exits when `p_loss > THRESHOLD ⇔ p_win < (1 - THRESHOLD)`. So:
- v1 deployed at 0.70 ⇔ exit when p_win < 0.30
- **v3 deployed at 0.50 ⇔ exit when p_win < 0.50** (more aggressive)

v3 OOS replay on bundle 5 (validation, n=82) sweep:
| bot thr | sim_total | Δ vs actual |
|---:|---:|---:|
| 0.30 (replay θ=0.70) | dominated | — |
| 0.50 (replay θ=0.50) | **+$208.84** | **+$305.37** |
| 0.70 (v1's value) | +$127.09 | +$224.32 |
| 0.80 (cautious) | +$101 | +$198 |

θ=0.50 was the joint optimum on bundle 5 OOS. On bundle 7 it fires on all 5 positions (no winner-protection at this threshold), but bundle 7's max p_win was only 0.29 so no threshold in [0.30, 0.95] differentiates there.

## What to monitor on next bundle

1. **`p_loss` distribution** in `SMART_MODEL_EXIT` log lines — should now span [0.05, 0.95] instead of saturating to 1.000 like v1.
2. **Fire rate** — expect ≈40-60% of trades to fire model_exit (vs v1's 100% on bundle 7).
3. **Aggregate model_exit PnL** — target positive net (was −$1.84 on bundle 7 with v1).
4. **Held duration distribution** of model_exit fires — v1 fired at 27-29s due to saturation; v3 should fire at varied times based on actual signal.

## Rollback procedure

If v3 misbehaves:
1. Roll back the commit: `git revert 0c42d681` (restores v1 model + threshold 0.70)
2. Re-run `./polymarket/k8s/helm/polymarket-1h-bot/deploy.sh pm_btc_1h_smart`
3. ConfigMap will revert v1; helm upgrade applies threshold 0.70.

To disable model entirely (fall back to static salvage rules):
- Set `smartExitModelThreshold: "0"` in `pm_btc_1h_smart.yaml`
- Helm upgrade (no configmap change needed)

## Untracked work (not in commit 0c42d681)

These were used to build v3 but stay local — gitignored or not added:
- `ai/pm_btc_1h_exit/train_exit_model_v3.py` (trainer with label smoothing + cross_entropy)
- `ai/pm_btc_1h_exit/exit_dataset_v3.parquet` (40 MB, gitignored — rebuildable from bundles via `prepare_exit_dataset.py`)
- `ai/pm_btc_1h_exit/pm_btc_1h_exit_model_v3_oos_bundle5.txt` (apples-to-apples validation model)

To rebuild v3-prod from scratch:
```
python3 ai/pm_btc_1h_exit/prepare_exit_dataset.py --out ai/pm_btc_1h_exit/exit_dataset_v3.parquet
python3 ai/pm_btc_1h_exit/train_exit_model_v3.py --oos-bundle ZZZ_NO_HOLDOUT \
  --model-out polymarket/k8s/helm/polymarket-1h-bot/files/model/pm_btc_1h_exit_model.txt \
  --meta-out polymarket/k8s/helm/polymarket-1h-bot/files/model/pm_btc_1h_exit_meta.json
```

## How to apply

- When evaluating the next bundle: replay v3 on it via `replay_exit_model.py --data <new-dataset> --model polymarket/k8s/helm/polymarket-1h-bot/files/model/pm_btc_1h_exit_model.txt --thresholds "0.30,0.50,0.70"` to compare actual vs different threshold ops.
- Don't retune θ on a single bundle. Wait for ≥3 post-v3 bundles before considering threshold change.
- If a future bundle shows the saturation pattern returning (all p_loss=1.000), it means corpus drift outpaced training — refresh dataset and retrain v3 with current bundles.
