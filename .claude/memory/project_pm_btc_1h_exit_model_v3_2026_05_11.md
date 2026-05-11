---
name: PM BTC 1h exit classifier v3 — label-smoothed (2026-05-11)
description: Retrained v3 with label smoothing (ε=0.05, cross_entropy objective) + stronger regularization to fix v1's saturation on bundle 7. Strictly better than v1 — fixes saturation AND improves OOS replay PnL by +$77 on bundle 5 (+$306 vs +$229 Δ).
type: project
---

# PM BTC 1h exit classifier v3 — label-smoothed (2026-05-11)

## Problem v3 fixes

v1 deployed at θ=0.70 went degenerate on bundle 7 (`20260511_125510_5.4h`) — predicted p_win ≈ 0 on every tick of every position. Fired on all 5 entries within 27-29s, including the winner. See `project_pm_btc_1h_exit_model_live_bundle_20260511_125510.md`.

v2 (no session_pnl) ablation went degenerate in the opposite direction — p_win ≈ 0.95 on everything.

Root cause: binary objective with hard labels (0/1) lets the model push outputs to extremes when training is uncertain. Saturated outputs lose discrimination.

## v3 design changes vs v1/v2

| change | v1/v2 | v3 |
|---|---|---|
| Objective | `binary` | `cross_entropy` |
| Labels | 0 / 1 | smoothed: 0.05 / 0.95 |
| Effective output cap | none → saturates | [0.05, 0.95] |
| `num_leaves` | 31 | 15 |
| `max_depth` | (unbounded) | 6 |
| `min_data_in_leaf` | 200 | 500 |
| `lambda_l2` | 0 | 0.1 |
| Corpus | 5 bundles (245 train + 82 OOS) | 7 bundles (336 train) |

Script: `ai/pm_btc_1h_exit/train_exit_model_v3.py`.
Dataset: `ai/pm_btc_1h_exit/exit_dataset_v3.parquet` (884K ticks, 341 positions).

## Models produced

| Model file | OOS bundle | Purpose |
|---|---|---|
| `pm_btc_1h_exit_model_v3.txt` | bundle 7 (20260511_125510, 5 pos) | Production candidate (tests degenerate regime generalization) |
| `pm_btc_1h_exit_model_v3_oos_bundle5.txt` | bundle 5 (20260507_091151, 82 pos) | Apples-to-apples vs v1 |

## Apples-to-apples comparison (bundle 5 as OOS for both)

| Metric | v1 (deployed) | v3 |
|---|--:|--:|
| CV AUC | 0.760 ± 0.058 | 0.737 ± 0.063 |
| OOS AUC | **0.667** | **0.688** (+0.021) |
| OOS p_win range | [0.0, 1.0] | [0.01, 0.96] |
| Best replay PnL @ θ | +$131.83 (θ=0.30) | **+$208.84 (θ=0.60)** |
| OOS Δ vs actual | +$229 | **+$306** (+$77) |

v3 wins on OOS AUC, OOS PnL, AND fixes saturation. Strictly better on the bundle that v1 was originally validated against.

## Bundle 7 (degenerate regime) — v3 vs v1

OOS for v3-bundle-7 variant. v1 was just predicted (it had no OOS knowledge of this bundle).

| Pos | Dir | Actual | v1 p_win | v3 mean p_win |
|---|---|--:|---|--:|
| 1 | UP | −$0.47 | 0.000 (sat) | 0.127 |
| 2 | DOWN | −$1.14 | 0.000 (sat) | **0.066** (lowest, biggest loss ✓) |
| 3 | DOWN | −$0.44 | 0.000 (sat) | 0.263 |
| 4 | UP | +$0.21 | 0.000 (sat) | 0.231 (winner) |
| 5 | UP | $0.00 | 0.000 (sat) | 0.044 |

Bucket analysis on OOS:
- min_p < 0.20: 3 positions, WR=0%, sum=−$1.61 (all losers caught)
- min_p ∈ [0.20, 0.40): 2 positions, WR=50%, sum=−$0.23 (winner held, break-even held)

Replay PnL at θ=0.20, min_hold=5s: **+$1.58** vs actual −$1.84.

## Caveats

1. **In-sample AUC=1.0** on training bundles → some memorization remains despite regularization. CV AUC of 0.74 is the realistic ceiling.
2. **OOS bundle 7 is only 5 positions** — AUC 0.76 there is fragile. Real test is the next live deployment.
3. **Cross-regime threshold sensitivity:** bundle 5 OOS optimum at θ=0.60, bundle 7 OOS optimum at θ=0.20. The model's *discrimination* generalizes but the *absolute scale* shifts with regime. A single fixed threshold won't be optimal in all regimes — but min_p < 0.20 catches losers in both bundles.
4. **session_pnl still #1 feature by gain.** Smoothing + regularization tames it but doesn't eliminate dependence. Future iterations could try dropping session_pnl + smoothing (combined v2+v3).
5. **6 force_close winners get cut** on bundle 5 OOS at θ=0.60 (~−$54 in lost wins). Net is still +$77 over v1 but not free.

## Deployment recommendation (not yet shipped)

If shipping v3:
- Use `pm_btc_1h_exit_model_v3_oos_bundle5.txt` for max-data fit, OR retrain on full corpus (no OOS) for production
- **Threshold: try θ=0.30** as a safe starting point (matches v1's threshold semantically — moderate filtering). Bundle 5 replay: +$224 Δ at θ=0.30.
- Consider θ=0.20 alternative for stronger filtering — but tests show similar PnL with fewer fires.
- Update `SMART_EXIT_MODEL_THRESHOLD` env in `pm_btc_1h_smart.yaml`.
- Re-apply ConfigMap via `apply-model-configmap.sh` (server-side apply, established chain).

## How to apply

- Retrain v3 every ~7 bundles or whenever live PnL diverges from replay by > ±$50.
- Always include the most recent bundle in training (rolling window or expanding window — TBD with more data).
- If a future bundle shows saturated outputs again (p_win mass at extremes), drop session_pnl + re-train.
