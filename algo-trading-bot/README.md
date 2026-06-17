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
skeleton (§2). Implemented and tested (43 tests): ccxt data ingest + interval-aware
point-in-time Parquet store, causal feature pipeline, the Tier-1 trend baseline,
forecast combiner + vol-target sizer, risk gate, idempotent OMS, fill simulator with
costs, the shared backtest==live engine with run provenance, an OOS validation
harness (in-sample grid tune → out-of-sample test + Deflated Sharpe + gate), the full
meta-label ML loop (triple-barrier labeling, average-uniqueness weights, purged &
embargoed K-fold CV, GBT, MDA importance, leak-check, economic test), and a
cross-sectional momentum panel backtest (lookahead-careful, cost-aware, IS/OOS + DSR),
CPCV + Probability of Backtest Overfitting (CSCV) wired into both validators, and
stress/scenario replay (flash crash, de-peg, outage, liquidity drought) checking
solvency / de-risk / no-order-storm invariants — with a test proving the drawdown
breaker fires and flattens the book on a deep crash. A paper runner (replay or live
poll) drives the same engine with simulated fills, structured audit logging, and
persistent safe-restart, runnable via Docker/compose; real-money live is guarded. Real
venue order I/O (Kraken spot, Hyperliquid perps) is implemented via a single ccxt broker
and verified with a mock exchange (no live orders in tests). Remaining stubs (cite their
requirement section): regime classifier, model registry, funding settlement in live PnL.

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
atb xsec      --config configs/xsec_1d.toml  # cross-sectional momentum panel OOS — WORKING
atb stress    --config configs/btc_1h.toml   # pathological tapes; assert SAFE    — WORKING
atb paper     --config configs/paper.toml    # run engine, simulated fills        — WORKING
atb live      --config configs/paper.toml    # real orders                        — GUARDED (refuses)
```

## Run it locally (Docker)

Paper mode runs the **same engine** as backtest/validate (NFR1) against a live-style
feed, with simulated fills (no API keys), persisting NAV/positions + a JSONL decision
log to `./state` (safe restart, NFR4).

```bash
cd algo-trading-bot
./scripts/fetch.sh           # one-shot: pull BTC 1h into ./data  (docker)
./scripts/paper.sh           # build + paper-trade (replays stored bars through the engine)
# or directly:
docker compose --profile tools run --rm fetch
docker compose up --build paper
```

`--source replay` (default) streams stored bars through the engine so you can watch it
run deterministically; `--source live` polls the venue for newly-closed bars. Real-money
`live` is intentionally **guarded** — it refuses to start unless a recorded approve-for-live
gate pass exists, and nothing has cleared the gate (§4).

When something does clear the gate, real orders go through one ccxt broker. Credentials
come only from the environment, never config/code:

```
# Kraken (spot)
export ATB_KRAKEN_API_KEY=...      ATB_KRAKEN_API_SECRET=...
# Hyperliquid (perps)
export ATB_HL_WALLET_ADDRESS=...   ATB_HL_PRIVATE_KEY=...
```

### What the harness already tells you (real BTC 1h, 2024-01 → 2026-06)

- `backtest` (untuned baseline, after costs): total return **−0.5%**, Sharpe **−0.04**, skew **+0.51**.
- `validate` (grid-tune on train, test OOS): best train Sharpe **+0.65** → **OOS Sharpe −0.92**,
  Deflated Sharpe **0.15** (need ≥0.95), **PBO 0.77** (need ≤0.3) → gate **REJECTED**. The
  harness caught an overfit edge before any capital saw it (principle #2).
- `metalabel` (triple-barrier label, GBT, purged & embargoed CV): pooled **OOS AUC 0.62**
  (consistent across 6 folds). Leak-checked: **shuffling labels collapses AUC to 0.500**,
  dropping calendar features keeps 0.59 — a real, leak-free signal, dominated by `ret_vol`
  (vol-clustering / "is a move coming"), **not directional alpha**.
- **`metalabel` economic test (the verdict):** trained on train, run OOS after costs, the
  meta-labeled book scores Sharpe **−1.35 vs the baseline's −0.93 — it makes things WORSE**.
  Gate **REJECTED**. The 0.62 AUC did not become profit: confidence-sizing a non-directional
  ranking signal just concentrated risk into volatile periods, and costs ate it. **AUC ≠
  profit**, demonstrated end-to-end (principle #4). The harness stopped a plausible signal
  from being mistaken for an edge — which is exactly its job (principle #1).
- `xsec` (cross-sectional momentum, 16-alt universe, 1d, dollar-neutral): in-sample best
  lookback Sharpe **+1.27**; even where a grid happens to yield a positive OOS Sharpe
  (~+0.45), **PBO 0.73** and **DSR 0.30** expose it as overfit, and skew runs to **−3.47**
  (momentum-crash / negative-skew, the §6.2/§12 account-killer). Gate **REJECTED**. PBO is
  the lesson here: a single train/test split can look positive while the *selection* is a
  coin-flip — PBO catches what one split misses.

Three strategy families tested (single-asset trend, meta-label ML, cross-sectional
momentum); **all three show strong in-sample and no robust OOS edge after costs**. That
consistent train→OOS collapse — caught every time, and now quantified by PBO — is the
harness doing its job. No edge has cleared the bar yet, and that conclusion is trustworthy.

## Build order (§6.1)

data → friction+metrics → **dumb trend baseline (the benchmark)** → feature/label
pipeline → meta-label ML (must beat baseline OOS, after costs) → validation harness →
arbitration → paper → live. Nothing ships that can't beat the dumb baseline.

## What's next

See **`docs/ROADMAP.md`** — prioritized future work (regime classifier, stops in the
loop, walk-forward retraining, vol-managed momentum, multi-strategy arbitration, model
registry, live drift auto-disable, funding ingestion, and more), grounded in what's
built and the findings so far.
