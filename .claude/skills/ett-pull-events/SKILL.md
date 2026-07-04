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
