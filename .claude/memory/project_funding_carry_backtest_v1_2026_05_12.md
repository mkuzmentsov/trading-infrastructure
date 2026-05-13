---
name: Funding-carry bot — v1 backtest (HL perp short + Kraken spot long) 2026-05-12
description: New trading-bot direction (away from Polymarket). Backtested delta-neutral funding carry on 12mo HL data. Verdict: "hold, don't time" — always-hold beat every timing variant. BTC+ETH ≈ 8%/yr, +HYPE+LINK ≈ 11-12%/yr blended, tiny DD in this regime. Real risks (basis blowout on unwind, HL short liquidation) NOT in the backtest. Modest at $1-5k capital. Code at funding-carry/.
type: project
---

# Funding-carry bot — v1 backtest (2026-05-12)

## Context
Pivot away from the Polymarket bot ("too many problems with Polymarket"). User has funded accounts on Hyperliquid + Binance + Kraken, ~$1-5k capital, plus ~99,784 KFEE (Kraken fee credit ≈ $998 of fee coverage, no expiry, applies to Kraken Pro spot+margin, NOT Kraken Futures). Plan: funding/basis carry first, then market making (Hummingbot) second.

## Strategy
Delta-neutral: **long Kraken spot** (fee-free via KFEE) + **short Hyperliquid perp** (hourly funding, ~1bp maker fee each side — the carry trade isn't latency-sensitive so use limit/maker orders on the HL leg). Short the perp ⇒ collect funding when it's positive (the common case). PnL/hr (frac of notional) = +fundingRate. Cost ≈ 3bps round-trip (HL maker ×2 + Kraken free), + a basis haircut.

## Data
`funding-carry/fetch_data.py` → `funding-carry/data/hl_funding.parquet` (HL fundingHistory, hourly) + `hl_candles_1h.parquet`. 12 months (2025-05-17 → 2026-05-12), 8640 hrs × 8 coins.

## Backtest (`funding-carry/backtest.py`)
Two policies: `always_hold` (open at t0, never close) vs `threshold` (hold only while trailing-mean annualized funding > open%, close when < close%). Sweep over open/close/smoothing.

**Result: always-hold beat every timing variant.** Best timed BTC+ETH ≈ 7.3%/yr vs always-hold 8.0%/yr — timing adds churn, fees, and a basis-risk event per cycle for *less* return. More selective thresholds → monotonically worse. Funding is positive on net; negative stretches are brief/small enough that holding through beats churning.

Annualized always-hold funding, 2025-26:
| Asset | Ann | MaxDD of funding curve |
|---|--:|--:|
| HYPE | +14.0% | 0.27% |
| LINK | +11.9% | 0.03% |
| BTC | +8.0% | 0.15% |
| ETH | +8.0% | 0.24% |
| DOGE | +7.7% | 0.67% |
| AVAX | +6.8% | 1.30% |
| XRP | +6.4% | 1.67% |
| SOL | +2.4% | 2.44% (skip) |

BTC+ETH hold ≈ 8%/yr; +HYPE+LINK ≈ 11-12%/yr blended; small DD in this regime. KFEE matters: without it the Kraken spot leg's ~0.8% round-trip roughly halves BTC/ETH carry — with it, free.

## What the v1 backtest does NOT capture (the risks that matter)
1. **Basis blow-out on unwind** — modeled as flat 3bps; real HL-perp/Kraken-spot basis can spike 0.5-2% for minutes-hours in stress. Always-hold minimizes this (unwind once, on your terms). v2 backtest needs actual HL perp + Kraken spot price series → real basis P&L on entry/exit.
2. **HL short liquidation** — BTC rips +25% before you move Kraken-side gain to HL margin ⇒ a 2× short nears liquidation though net-flat. Needs ≤1.5× effective leverage (more capital tied up) + auto-rebalance + kill switch. Backtest ignores entirely.
3. **Regime shift** — 2025-26 was positive-funding. If funding inverts for months, always-hold bleeds ⇒ bot needs ONE exit rule: "close if funding negative for N days" (not aggressive churn).
4. **Counterparty** — HL is young; size accordingly.

## Scale reality
$3k × 8-12%/yr ≈ $240-360/yr. "Build infra, earn pocket change, scale to $20-50k if proven" — not a moneymaker at $1-5k.

## Files
- `funding-carry/fetch_data.py` — HL funding + candle fetcher
- `funding-carry/backtest.py` — the v1 sim
- `funding-carry/data/*.parquet` — cached data (gitignore-able, refetchable)

## v2 backtest (2026-05-12) — `funding-carry/backtest_v2.py`
Used the HL `premium` field (perp-vs-index basis) for real basis P&L + HL candles for a liquidation stress test. **Edge holds up:**
- Basis P&L over the year nets ~0 (premium mean-reverts). Forced-unwind worst case (open at median premium, forced to close at the worst-for-a-short premium spike): **BTC −0.27%, ETH −0.21%, HYPE −0.33%, others ~−0.2-0.3%, LINK −1.39%** (LINK had a +137bps perp-over-index spike once). For majors this is rounding error vs a year of funding; the v1 3bps haircut was conservative.
- Liquidation: max +24h up-move BTC +14%, ETH +16%, HYPE +30%, XRP +33%, others ~19-22%. Liq-move at L=2 ≈ 45-49%, L=3 ≈ 28-32%, L=5 ≈ 15-19%. With a minutely rebalance loop the relevant window is ~1h (BTC +4.4%, HYPE +11%) → L=2-3 comfortably safe. The 24h numbers are the "rebalancer/exchange down for a day" scenario.

**Recommended config:** BTC+ETH+HYPE basket (or BTC+ETH for max safety), L=2 on the HL short (margin=50% of notional), minutely delta check + auto top-up HL margin from Kraken when delta drifts >~7%, kill switch (close all if can't rebalance / funding negative N days). Expected ~8-10%/yr net, sub-1% DD in this regime. No timing layer — just regime-flip protection.

## Bot built (2026-05-12) — `funding-carry/bot/`
Core skeleton done & smoke-tested (py_compile + strategy unit checks pass):
- `config.example.yaml` — schema: assets[{coin,notional_usd}], leverage (2.0), deleverage_liq_room (0.15) / emergency_liq_room (0.05), delta_rebalance_pct (0.08), funding regime-flip params (exit_apr 0, persist 48h, reentry_apr 0.03), kill-switch (max_consecutive_errors), HL+Kraken creds. `dry_run: true` default.
- `exchanges.py` — `MarketData` (public HL mids+funding), `HyperliquidPerp` (positions/account_value/open_short/reduce_short/close_short/set_leverage), `KrakenSpot` (ccxt: balance/buy/sell/price). All honor `dry_run` (log intended orders, send none). In dry_run with creds → reads real state; without → mocks flat.
- `strategy.py` — `decide(CoinState, Cfg) -> [actions]`, pure logic. Actions: open_pair, close_pair (incl. emergency), deleverage, rebalance_spot, mark_regime_exit/reentry. Smoke-tested: flat+positive→open; spot-drift→rebalance; funding<0 for 50h→close+exit; liq-room 5%→emergency close.
- `main.py` — loop: refresh funding window (HL funding_history, ≤10min cache) → read mids/funding/positions/balances → build CoinState per coin → decide → execute (or log) → save fc_state.json (regime_exited flags) → log STATE json. Kill switch on N consecutive errors → flatten.
- `requirements.txt` (ccxt, hyperliquid-python-sdk, eth-account, PyYAML), `README.md`.
- `.gitignore`: `funding-carry/data/`, `funding-carry/bot/config.yaml`, `funding-carry/bot/fc_state.json`.

**Not done / TODO:** (1) actually run the dry-run loop end-to-end (needs `pip install -r requirements.txt`). (2) Helm chart (Dockerfile + deployment + secret + PVC + deploy.sh) mirroring `freqtrade/k8s/helm/freqtrade-bot`. (3) v1 simplifications to revisit: HL orders are IOC-taker (~9bp RT; maker-with-fallback → ~3bp is a TODO); no precise basis alert; deleverage cuts a fixed fraction.

## Status / next
v1+v2 backtests done, edge validated, bot core skeleton built. Next: dry-run test (after `pip install -r requirements.txt`), then Helm chart + deploy in dry_run, watch STATE logs ~1-2 weeks, then go live tiny ($200 BTC) before scaling. Then market making (Hummingbot on Kraken, fee-free via KFEE) as the #2 strategy.

## How to apply
- Don't build a timing/threshold layer — the data says hold. The only exit logic needed: regime-flip protection ("funding negative N days → close").
- Build with low HL leverage + auto-rebalance + kill switch from day one. The backtest's clean DD numbers assume you never get liquidated or forced to unwind at a bad basis.
- Refetch data with `fetch_data.py --months N` before re-running; funding regimes shift.
