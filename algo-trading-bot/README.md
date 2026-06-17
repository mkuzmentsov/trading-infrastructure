# algo-trading-bot

Systematic **directional** crypto trading bot — pattern + ML — built validation-first.
Market-neutral carry/arb is out of scope (separate project). The existing
`trading-mcp` server stays separate; this system reaches it (if at all) only through
a venue adapter.

> The validation harness is the product. The model is a few lines of code; the
> machinery that stops a backtest from lying to you is the real engineering.
> This design maximizes *survival probability* and *test trustworthiness* — it does
> **not** promise an edge. See `docs/INITIAL_REQUIREMENTS.md` §11.

## Status

**Phase 1–4 vertical slice working end-to-end** on real data, atop the full 8-layer
skeleton (§2). Implemented and tested (23 tests): ccxt data ingest + point-in-time
Parquet store, causal feature pipeline, the Tier-1 trend baseline, forecast
combiner + vol-target sizer, risk gate, idempotent OMS, fill simulator with costs,
the shared backtest==live engine with run provenance, an OOS validation harness
(in-sample grid tune → out-of-sample test + Deflated Sharpe + gate), and the
meta-label ML path (triple-barrier labeling, average-uniqueness weights, purged &
embargoed K-fold CV, GBT, MDA importance) with a leak-check regression test.
Remaining stubs (cite their requirement section): CPCV/PBO, regime classifier,
stress replay, model registry, live/paper runners.

## Phase-0 decisions

- **Horizon:** swing (hours–days) + position (days–weeks). No scalping/L2.
- **Venues:** Hyperliquid + Kraken, one active per run, behind a common adapter.
- **Engine:** custom thin event loop now (backtest==live), evaluate `nautilus_trader` later.

See `docs/ARCHITECTURE.md` for the layer→module map and resolved design tensions.

## Layout

```
src/algo_trading_bot/
  core/         domain types, events, clock          §2
  data/         ingest, point-in-time store, bars     §2.1
  features/     pipeline, fracdiff, triple-barrier     §2.2
  strategy/     forecast generators by risk tier       §2.3 / §6.2
  arbitration/  combiner, regime gate, sizing          §2.4 / §7
  risk/         limits, stops, drawdown, kill, gate     §2.5  (absolute precedence)
  execution/    idempotent current→target OMS           §2.6 / §7.3
  adapters/     hyperliquid, kraken                     §2.1 / §8
  engine/       shared loop, backtest, live             §3.1  (NFR1)
  backtest/     friction, metrics, report               §3.2-3.3
  validation/   purged CV, CPCV/PBO, DSR, gate          §4
  model/        registry, champion-challenger           FR10
  monitoring/   audit log, NAV, drift, deadman          §2.7
  cli.py        `atb` entry point                       §9
```

## Setup

```bash
# from repo root, with the project venv active
pip install -e "algo-trading-bot[dev,storage,ml,venues]"
pytest algo-trading-bot/tests
```

Extras are split so the research/validation path installs light:
`storage` (parquet+duckdb), `ml` (lightgbm+sklearn), `venues` (ccxt+hyperliquid).

## CLI

```
atb fetch     --venue binance --symbols BTC --interval 1h --start 2024-01-01  # WORKING
atb backtest  --config configs/btc_1h.toml   # equity curve, metrics, provenance — WORKING
atb validate  --config configs/btc_1h.toml   # in-sample tune -> OOS test + gate — WORKING
atb metalabel --config configs/btc_1h.toml   # triple-barrier + GBT in purged CV — WORKING (needs [ml])
atb paper     --config configs/btc_1h.toml   # paper-trade live data            — stub
atb live      --config configs/btc_1h.toml   # guarded live                      — stub
```

### What the harness already tells you (real BTC 1h, 2024-01 → 2026-06)

- `backtest` (untuned baseline, after costs): total return **−0.5%**, Sharpe **−0.04**, skew **+0.51**.
- `validate` (grid-tune on train, test OOS): best train Sharpe **+0.65** → **OOS Sharpe −0.92**,
  Deflated Sharpe **0.15** (need ≥0.95) → gate **REJECTED**. The harness caught an overfit
  edge before any capital saw it (principle #2).
- `metalabel` (triple-barrier label, GBT, purged & embargoed CV): pooled **OOS AUC 0.62**
  (consistent across 6 folds). Leak-checked: **shuffling the labels collapses AUC to 0.500**,
  and dropping calendar features keeps AUC 0.59 — so it's a real, leak-free statistical
  signal, dominated by `ret_vol` (vol-clustering / "is a move coming"), **not directional
  alpha**. AUC ≠ profit: the decisive test is still whether it lifts the baseline Sharpe
  OOS after costs (principle #4), which is the next step.

This `Sharpe ≈ 0` baseline is the bar any model must clear OOS, after costs.

## Build order (§6.1)

data → friction+metrics → **dumb trend baseline (the benchmark)** → feature/label
pipeline → meta-label ML (must beat baseline OOS, after costs) → validation harness →
arbitration → paper → live. Nothing ships that can't beat the dumb baseline.
