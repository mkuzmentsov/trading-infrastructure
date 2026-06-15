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

**Phase 0 → 1 scaffold.** Full 8-layer skeleton per requirements §2. Interfaces,
domain types, and the standard metric/stat functions are implemented; business logic
is `NotImplementedError` stubs that name what they must do and cite the requirement
section. Everything imports and the implemented metrics are tested.

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

## CLI (planned)

```
atb fetch    --venue kraken --symbols BTC ETH --interval 1h --start ... --end ...
atb backtest --config config.toml      # equity curve, ledger, metrics, provenance
atb validate --config config.toml      # §4 harness + approve-for-live gate
atb paper    --config config.toml      # paper-trade live data (gate before capital)
atb live     --config config.toml      # guarded: requires passed gate + paper run
```

## Build order (§6.1)

data → friction+metrics → **dumb trend baseline (the benchmark)** → feature/label
pipeline → meta-label ML (must beat baseline OOS, after costs) → validation harness →
arbitration → paper → live. Nothing ships that can't beat the dumb baseline.
