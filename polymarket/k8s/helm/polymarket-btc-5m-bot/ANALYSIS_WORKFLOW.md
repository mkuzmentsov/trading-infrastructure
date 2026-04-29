# BTC Bot Archive + Analysis Workflow

This file defines the required process for each performance-analysis cycle.

## 1) Commit source snapshot first
- Commit source/code changes before analysis notes.
- Always include `polymarket/k8s/helm/bots/pm_btc_1.env` in that commit.
- Record the commit SHA and use it as the analysis baseline.

Required in every analysis note:
- `Baseline commit: <sha>`
- `Compared commits/runs: <list>`

## 2) Archive current run logs
Create a timestamped folder under:
- `polymarket/k8s/helm/polymarket-btc-bot/update-log/logs-<YYYY-MM-DD_HH-MM-SS_TZ>/`

Copy into it:
- `logs-local.txt`
- `logs-training.jsonl`
- `logs-training-events.jsonl`

Add `README.txt` containing:
- archive timestamp
- source absolute paths
- baseline commit SHA

## 3) Produce run summary (`<timestamp>.txt`)
Create:
- `polymarket/k8s/helm/polymarket-btc-bot/update-log/<YYYY-MM-DD_HH-MM-SS_TZ>.txt`

Include at minimum:
- baseline commit SHA
- run duration
- opened/closed/open positions
- realized PnL
- win rate
- avg closed PnL
- avg winner / avg loser
- stop-loss rate
- thesis-decay rate
- WS error/reconnect counters (`INVALID OPERATION`, reconnect attempts)
- top `NO_TRADE` reasons
- comparison vs previous archived runs

## 4) Create next plan (`<timestamp>-plan.txt`)
Create:
- `polymarket/k8s/helm/polymarket-btc-bot/update-log/<YYYY-MM-DD_HH-MM-SS_TZ>-plan.txt`

Plan rules:
- compare current run against previous archived runs and previous plan files
- suggest only parameter values that were not tried before
- explicitly state that proposed values were checked against prior plans
- include expected effect for each change

## 5) No-repeat rule for experiments
Before proposing changes, check all previous:
- `update-log/*.txt`
- `update-log/*-plan.txt`

Do not repeat exact values already used in prior plans unless a deliberate rollback is requested.
If rollback is chosen, state it explicitly as rollback and reference the original timestamp/commit.

## 6) Commit policy
- Commit only source/config files unless explicitly requested to commit archives.
- If `update-log` is gitignored, keep archive files local but still generate them every run.
- Keep unrelated local artifacts out of commits (`.DS_Store`, `__pycache__`, temporary files).

## 7) Suggested analysis cadence
- Short run: 1-2 hours for smoke validation.
- Main comparison run: 6-8 hours.
- Use the 6-8 hour run for parameter decisions.
