---
name: pm-btc-strategy-tuning
description: Tune a Polymarket BTC bot toward profitability by adjusting parameters, position-management rules, signal logic, and supporting code. Use when the user wants to test strategy variants, change pm_btc YAML settings, modify entry or exit logic, compare alternatives, or iterate from logs and backtests toward better expected PnL.
---

# PM BTC Strategy Tuning

Use this skill when the user wants to change the PM BTC strategy or configuration to improve results.

## Scope

This skill covers:
- `polymarket/k8s/helm/bots/pm_btc*.yaml`
- PM BTC strategy code and position-management logic
- log-driven hypotheses from `logs-training-events.jsonl` and `loki.log`
- repeated tuning loops across config changes and code changes

## Workflow

1. Start from evidence, not intuition.
2. Inspect the active config and the relevant runtime code before proposing changes.
3. Use recent logs to identify failure modes:
   - stop-loss churn
   - buying too close to the open
   - late exits that give back edge
   - fills that convert good signals into bad realized prices
   - redemption or inventory effects that obscure true strategy quality
4. Form a small set of hypotheses tied to measurable metrics.
5. Change one coherent thing at a time:
   - entry filters
   - sizing
   - stop-loss or take-profit behavior
   - hold-to-expiry behavior
   - late-bar rules
   - signal model or drift parameters
6. Validate with whatever local evidence exists:
   - log replay
   - dry-run PnL reconstruction
   - tests
   - targeted simulation scripts
7. Report outcomes in terms of expected PnL, trade count, win rate, drawdown, and behavior changes.

## Rules

- Do not optimize only for raw PnL. Track trade count, exposure, variance, and drawdown.
- Separate true strategy changes from artifacts caused by external wallet positions.
- Prefer changes that can be explained from market structure or logged behavior.
- If multiple changes are needed, stage them as explicit variants so they can be compared cleanly.
- When a profitability claim is weak, say so directly.

## Common adjustment areas

- Entry gating:
  - `minEdge`
  - `costBuffer`
  - `maxEntrySpread`
  - `minEntryPrice`
  - `maxEntryPrice`
  - `minBtcDistance`
  - `minBookDivergence`
  - `entryConfirmationTicks`
- Sizing:
  - `betSizeMin`
  - `betSizeMax`
  - `maxBudgetFraction`
  - `kellyScale`
  - `minPositionShares`
- Exit behavior:
  - `takeProfit`
  - `stopLoss`
  - `slArmDelaySecs`
  - `signalExitEdge`
  - `aggressiveExitSlippage`
  - `trailingArmGain`
  - `trailingStopGap`
  - `holdToExpiryDefault`
- Strategy logic:
  - cheap-tail inversion
  - late-entry discounts
  - late-bar bonuses
  - drift coefficients
  - signal-model blending

## Output guidance

- Lead with the concrete variant you changed and why.
- Quantify expected effect using logs or tests.
- If results are inconclusive, recommend the next highest-signal experiment instead of pretending the strategy is fixed.
