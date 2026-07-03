---
name: pm-orders-chart
description: Chart the every-tick Polymarket paper/live bots — 5m price per coin with chop/trend regime shading and every fill marked U/D, green=won red=lost. Use when the user asks for a bot performance chart, regime chart, or "show orders on the price chart".
---

# pm-orders-chart

Renders per-coin (btc/eth/sol/xrp) 5-minute price charts with:
- background shading per 5m bar: green = chop (|move| ≤ p60 of window), red = trend (≥ p85), per-coin thresholds
- every filled position marked at its bar: letter = bid side (U/D), green = won, red = lost

## Steps

1. Dump events from the paper fleet (kube context MUST be Hetzner: `cd <repo root> && source .dev-env-source` first):
   ```
   for c in btc eth sol xrp; do
     kubectl exec -n every-tick-single deploy/${c}-every-tick-single -- \
       cat /app/logs/logs-training-events.jsonl > <scratch>/${c}_snap.jsonl
   done
   ```
2. Build the chart (fetches Binance 5m klines itself):
   ```
   python3 .claude/skills/pm-orders-chart/build_chart.py <scratch> <scratch>/orders_regimes.html [start_utc_ms]
   ```
3. Deliver with SendUserFile (display: render).

## Gotchas (learned 2026-07-03)

- `paper_bar_settle.market_start_ts` belongs to the NEXT bar; the settled bar's start is
  `floor(settle.ts/300)*300 − 300`. For snapshot↔settle joins use `condition_id == paper_condition_id`.
- A win = `position.win or exit_kind == "tp"`.
- Regime thresholds are per-coin (sol/xrp baseline vol ≈ 20 bps/5m vs btc ≈ 13) — never share one cutoff.
- Interpretation: losses cluster in/after red bars (adverse selection); chop stretches are where 0.48 fills win.
