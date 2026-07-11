---
name: cur2-pnl-chart
description: Chart cumulative realized PnL by coin for the cur+2 50c bettor fleet (sol-cur2, eth-cur2, …) and compute the wallet's mark-to-market equity (free USDC + open positions). Use when the user asks for cur2 PnL, a PnL chart, bot equity, or "balance adjusted for open positions".
---

# cur2-pnl-chart

The cur+2 "50c bettor" bots (`entrypoint: cur2_bettor.py`, deployments
`{coin}-cur2-every-tick-single` in ns `every-tick-single`) predict the cur+2 5m bar
and rest a 0.50 BUY on the predicted side. This skill (a) charts each coin's
cumulative **realized** PnL and (b) computes the wallet's **mark-to-market equity**.
Distinct from `pm-orders-chart` (that charts the maker-engine bots' price+fills).

Kube context MUST be Hetzner first (silently hits AWS EKS otherwise):
`cd <repo root> && source .dev-env-source && kubectl config current-context`
→ must print `hetzner-k3s-cluster-master1`. Run every step from the **repo root**
(the shell cwd persists between calls; if `source .dev-env-source` errors, you
`cd`'d into a subdir — go back to repo root).

## 1. Cumulative PnL chart

```
python3 .claude/skills/cur2-pnl-chart/build_pnl_chart.py <scratch>/pnl.html \
    --coins sol,eth --since "2026-07-10 19:35:04"
```
Pulls `CUR2_BET_SETTLE` events live from each `{coin}-cur2` pod, sums per-bet
`pnl`, and renders a self-contained interactive HTML chart (dark/light aware,
crosshair+tooltip, stat tiles, data table). Deliver with SendUserFile
(`display: render`) or publish with Artifact. Add `--from-dir DIR` (files
`{coin}_settle.txt`) to rebuild offline from saved `kubectl logs` dumps.

**Pick `--since` = the top-up**, not run start. The pod can run for days but sits
**starved** (~$5.13, one cent short of the $5.175 order+fee) until the wallet is
funded — those bars log settles with `filled=0.0` / `pnl=0` and flatten the curve.
The top-up = the last balance rejection:
```
kubectl logs -n every-tick-single deploy/sol-cur2-every-tick-single \
  | grep "not enough balance" | tail -1     # timestamp here = --since
```

## 2. Mark-to-market equity ("balance adjusted for open positions")

Equity = **free USDC** + **current value of open (unresolved) positions**.

Free USDC (live, via any running cur2 pod — same shared wallet):
```
POD=$(kubectl get pods -n every-tick-single --no-headers | grep sol-cur2 | awk '{print $1}')
kubectl exec -n every-tick-single "$POD" -- sh -c \
  'cd /app/scripts && python3 -c "from engine.clob import fetch_usdc_balance; print(round(fetch_usdc_balance(),2))"'
```

Open positions (Polymarket data-api; wallet/funder = `0xD632C1e14323B75456eA0A58d90B05fB7B7a1b2F`):
```
curl -s "https://data-api.polymarket.com/positions?user=0xD632C1e14323B75456eA0A58d90B05fB7B7a1b2F&sizeThreshold=0.1&limit=500&sortBy=CURRENT&sortDirection=DESC" \
 | python3 -c "import sys,json;d=json.load(sys.stdin);o=[p for p in d if not p['redeemable']];print('open value \$%.2f'%sum(p['currentValue'] for p in o));[print(f\"  {p['title'][:44]:44} {p['outcome']:4} sz={p['size']:.1f} cur={p['curPrice']:.3f} val=\${p['currentValue']:.2f}\") for p in o]"
```
**equity = free_USDC + open_value.**

## Gotchas

- **`redeemable=true` + `curPrice=0` = resolved-and-LOST**, worth $0 — ignore
  (there are hundreds of these dust tokens). Only `redeemable=false` rows are OPEN.
  A won position is auto-redeemed into cash, so free USDC already includes all wins;
  don't double-count. (If you ever see `redeemable=true` + `curPrice≈1`, that's an
  un-redeemed win — rare — add it.)
- data-api titles are **ET**; the bot logs are **UTC**. A "2:45AM ET" market = 06:45 UTC.
- Only `filled>0` settles move PnL. Fill rate is low when starved (~17%) and ~100%
  once funded — filter starved bars via `--since`.
- **Realized-only**: btc never traded (model was sklearn-1.8.0-pickled, image is 1.9.0,
  crashes on `_loss`); a coin whose pod was deleted before its last bets settled
  won't appear. Note both when scoping.
- Chart colors come from the validated dataviz categorical palette
  (sol=blue, eth=aqua, xrp=yellow, btc=green); direct end-labels satisfy the relief rule.
