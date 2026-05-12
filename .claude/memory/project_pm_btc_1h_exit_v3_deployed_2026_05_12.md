---
name: PM BTC 1h exit model v3 — DEPLOYED 2026-05-12
description: v3 (label-smoothed, 7-bundle full-corpus refit, CV AUC 0.760) deployed to pm-btc-1h-smart on 2026-05-12 13:31 via ./deploy.sh — helm rev 14. Live config now: v3 model, θ=0.50, minHeld=120 (three changes at once from old v1/0.70/30). Deployed despite full-strategy harness showing v3@0.50 ≈ v1@0.70 — accepted as a calculated bet since v3 at least fixes the saturation pathology.
type: project
---

# PM BTC 1h exit model v3 — DEPLOYED 2026-05-12

## Timeline

- **2026-05-11 ~22:00** — v3 trained + committed (commits `0c42d68`, `027506c`): v3-prod model into `files/model/`, `smartExitModelThreshold: "0.50"` into yaml. First `./deploy.sh` attempt failed (kubectl `i/o timeout`) — **not deployed**, an earlier memo wrongly said it was.
- **2026-05-12 13:31** — `./deploy.sh pm_btc_1h_smart` succeeded. ConfigMap `pm-btc-1h-smart-model` server-side applied; `helm upgrade` → **revision 14**; pod restarted.

## Live state after deploy (verified 2026-05-12 ~13:32)

| Check | Value |
|---|---|
| Pod | `pm-btc-1h-smart-594dfdc5c-7hrxx`, fresh (age <1m), 0 restarts |
| Helm release | revision 14 |
| Model on pod | `pm_btc_1h_exit_model.txt` (raw, **no `.gz`** — v3 is 887 KB, under the 900 KiB gzip threshold) |
| Model header | `version=v4 objective=cross_entropy` ⇒ v3 ✓ |
| Load log | `Exit gate: loaded model from /app/model/pm_btc_1h_exit_model.txt (36 features expected, 36 known)` ✓ |
| `SMART_EXIT_MODEL_THRESHOLD` | `0.50` (was `0.70`) |
| `SMART_EXIT_MODEL_MIN_HELD_SECS` | `120` (was `30`) |
| `SMART_EXIT_MODEL_MIN_SECS_LEFT` | `30` (unchanged) |

**Three changes shipped at once:** v1→v3 model, θ 0.70→0.50, minHeld 30→120. If something regresses, hard to attribute — consider this when reading the next bundle.

## Why deployed despite the harness caveat

`replay.py` (full `math_smart.py` + yaml config + top-of-book fill model) on bundle `20260511_125510_19.8h`:
- v1@0.70, minHeld=120: +$0.03 / WR 56%
- v1@0.70, minHeld=30 (≈ prior live): −$0.98 / WR 44%
- **v3@0.50, minHeld=120: −$1.44 / WR 54%**

So v3@0.50 was *marginally worse* than v1@0.70 in the harness on the latest bundle (tiny dollar amounts on $213 invested either way). The "+$77 / +$229 v3 advantage" was a `replay_exit_model.py` tick-walk artifact (priced exits at `unrealized`, ignored the rest of the strategy). Deployed anyway because:
1. v3 fixes the saturation pathology — v1 was emitting `p_loss=1.000` on *every* position (degenerate; no winner/loser discrimination). v3 produces graded predictions [~0.02, ~0.95].
2. Both models are roughly break-even in the harness; the live loss (−$8.36 on that bundle) is mostly execution slippage (FAK fill latency on thin PM book) — not the exit-gate model. So the v1↔v3 choice is second-order.

## What to monitor on the next bundle

1. **`p_loss` distribution** in `SMART_MODEL_EXIT` log lines — must NOT be saturated at 1.000 like v1. Expect a spread (the model now caps at ~0.95).
2. **Fire rate** — on the 19.8h-bundle regime, v3@0.50 fired on ~24/26 in replay (still high). Watch whether it stays that aggressive. If it cuts >90% of entries, the gate is acting like "don't trade" — consider raising θ.
3. **minHeld=120 effect** — model can't fire until 120s held now (was ~30s). Positions get more room to develop before a cut. Compare model_exit held-durations to the old all-at-30s pattern.
4. **Aggregate model_exit PnL** vs the static-reason exits.
5. **Live vs replay gap** — pull the next bundle, run `replay.py` with the deployed yaml, expect live ~$5-50 worse than replay (execution slippage). If the gap is much bigger, something else is wrong.

## Rollback

- Disable model entirely: `smartExitModelThreshold: "0"` in `pm_btc_1h_smart.yaml` → `./deploy.sh pm_btc_1h_smart`. Falls back to static salvage rules.
- Revert to v1: restore `polymarket/k8s/helm/polymarket-1h-bot/files/model/pm_btc_1h_exit_model.txt` from commit `3bb634b` (or `b084bb3`), set threshold back to `0.70` + minHeld `30` in the yaml, `./deploy.sh`.
- Cluster context: `hetzner-k3s-cluster-master1` (k3s, not EKS — the kubeconfig also has stale EKS entries that time out; the working one is the k3s master).

## How to apply

- Use `replay.py` (full strategy) for deploy go/no-go, NOT `replay_exit_model.py` (tick-walk — optimistic, ignores the rest of the strategy).
- Verify deployment with `kubectl -n polymarket exec deploy/pm-btc-1h-smart -- sh -c 'env | grep SMART_EXIT_MODEL; ls -la /app/model/'` + `helm -n polymarket list`. Committing files ≠ deploying.
- Pre-deploy, the chart's `files/model/pm_btc_1h_exit_model.txt` must be the model you want live (the deploy script ships whatever is there — it doesn't pick a version).
