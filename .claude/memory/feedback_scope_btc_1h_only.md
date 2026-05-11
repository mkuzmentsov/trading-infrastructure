---
name: Scope is BTC 1h bot only
description: Only the polymarket-1h-bot BTC instance is in scope. Ignore 5m, 15m, ETH/XRP/SOL variants unless user explicitly reopens them.
type: feedback
---

We are working only on the **BTC 1h bot** (chart: `polymarket/k8s/helm/polymarket-1h-bot`, BTC instance via `MARKET_SLUG_PREFIX`).

**Why:** User stated 2026-05-11 that the other variants (PM BTC 5m, 15m, and ETH/XRP/SOL 1h overlays) are out of scope for current work.

**How to apply:**
- Bundles: only those under `polymarket/logs/1h/btc/pm-logs_pm-btc-1h-smart_*`
- Charts: only `polymarket-1h-bot` BTC values (`pm_btc_1h_smart.yaml`)
- Models: only `ai/pm_btc_1h_exit/` and `ai/pm_btc_entry/` (BTC 1h)
- Do NOT propose tuning, retunes, replays, or "next steps" that touch 5m/15m/ETH/XRP/SOL unless the user re-opens that scope.
- If a memory references the other variants, treat it as historical context only.