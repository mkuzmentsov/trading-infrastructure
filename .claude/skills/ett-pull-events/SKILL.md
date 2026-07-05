---
name: ett-pull-events
description: Pull event data (logs-training-events.jsonl + rotated daily archives) from the every-tick-single pods for analysis/backtests. Use whenever fresh bot data is needed — status checks, experiment runs, charts.
---

# ett-pull-events

Pulls event files from the 4 paper bots (btc/eth/sol/xrp, ns `every-tick-single`).

## Steps

1. Kube context MUST be Hetzner first (silently hits AWS EKS otherwise):
   `cd <repo root> && source .dev-env-source && kubectl config current-context`
   → must print `hetzner-k3s-cluster-master1`.
2. Today's live file (into a scratch dir):
   ```
   for c in btc eth sol xrp; do
     kubectl exec -n every-tick-single deploy/${c}-every-tick-single -- \
       cat /app/logs/logs-training-events.jsonl > <dir>/${c}_snap.jsonl
   done
   ```
3. A full past day (rotated archives + matching klines) — use the repo script:
   `python3 every-tick-single/tests/fetch_day.py <YYYY-MM-DD>`
   (writes to every-tick-single/tests/data/<date>/; archives kept 30 days on pod PVCs)
4. Sims expect files named `{coin}_snap.jsonl[.gz]` in one dir; run via
   `python3 every-tick-single/backtest/sim.py <dir> <klines_json>`.

## Gotchas
- ALWAYS dump before any helm upgrade/restart (even though logs are on PVCs now — belt and braces).
- `cat` via kubectl needs no `-i`; writing INTO a pod (`sh -c 'cat >> file'`) DOES need `kubectl exec -i`.
- Event-file schema notes and join traps live in `every-tick-single/backtest/sim.py` docstring.

## Rule: every rotated day gets a test baseline

When a pod has a rotated archive `logs-training-events.jsonl.<DATE>.gz` with NO
committed baseline yet (`every-tick-single/tests/data/<DATE>/expected_metrics.json`
absent), close the gap immediately:
```
python3 every-tick-single/tests/fetch_day.py <DATE>     # pulls archives + klines
python3 every-tick-single/tests/gen_baseline.py <DATE>  # writes expected_metrics.json
python3 every-tick-single/tests/test_backtest_integration.py   # must pass
git add every-tick-single/tests/data/<DATE>/expected_metrics.json   # baseline only (.gz gitignored)
```
Check for the gap on any status/experiment session:
`kubectl exec -n every-tick-single deploy/btc-every-tick-single -- ls /app/logs/*.gz`
vs `ls every-tick-single/tests/data/`. Each committed baseline is a permanent
regression check; the bulk .gz is fetchable on demand, not committed (except the
2026-07-03 reference fixture).

## Running the ML outcome model (ST-1)

Needs numpy+sklearn (not in system python). Use a venv:
```
python3 -m venv /tmp/mlvenv && /tmp/mlvenv/bin/pip install -q scikit-learn
/tmp/mlvenv/bin/python every-tick-single/backtest/ml_outcome.py <date> [<date> ...]
```
Saves per-run JSON to backtest/ml_runs/. ALWAYS read the flowonly/moveonly
attribution: a high AUC that lives entirely in the "moveonly" feature is the
current price (already priced, not tradeable) — not a real forecast. Pre-bar AUC
is the only honest "can we forecast at open" number.
