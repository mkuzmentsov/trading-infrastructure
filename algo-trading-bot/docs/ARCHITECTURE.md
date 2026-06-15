# Architecture & Decisions (v0.1 scaffold)

This maps the code skeleton to the requirements in `INITIAL_REQUIREMENTS.md` and
records the Phase-0 decisions that shaped the directory layout. Everything here is
a **skeleton**: interfaces, domain types, and the standard metric/stat functions are
real; the business logic is `NotImplementedError` stubs that name exactly what they
must do and which requirement section they satisfy.

## Phase-0 decisions (locked)

| Decision | Choice | Consequence |
|---|---|---|
| **Holding period** (§6.0) | **Swing + Position** (hours–days, days–weeks) | No L2 / latency infra. Bars 1h (swing) / 1d (position). `core.types.Horizon` has no SCALPING member. |
| **Venues** (§2.1) | **Hyperliquid + Kraken**, one active per run | `adapters/` has both behind a common boundary; `adapters.make_adapter()` picks one. |
| **Engine** (§3.1) | **Custom thin event loop first**, evaluate `nautilus_trader` later | `engine/loop.py` is the single shared decision path. Nautilus is a migration target once an edge justifies the dependency, not a Phase-0 bet. |
| **Storage** (§2.1) | Parquet + DuckDB (`storage` extra) | `data/store.py`. ClickHouse later. |
| **ML** (§8) | LightGBM / sklearn (`ml` extra), DL deferred | `strategy/meta_label.py`, `model/registry.py`. |

Open decisions still deferred (need data before they matter): concrete initial
universe beyond BTC, on-chain/sentiment feature sources, data granularity per
horizon.

## Layer → module map

| Requirement layer | Package | Key types |
|---|---|---|
| Data (§2.1) | `data/` | `DataSource`, `PointInTimeStore`, bar normalization |
| Feature & label (§2.2) | `features/` | `FeaturePipeline`, `fracdiff`, `triple_barrier_labels` |
| Strategy (§2.3, §6.2) | `strategy/` | `Strategy` protocol + one stub per tier |
| Arbitration / sizing (§2.4, §7) | `arbitration/` | `ForecastCombiner`, `RegimeGate`, `VolTargetSizer` |
| Risk (§2.5, §7.2) | `risk/` | `RiskGate` (kill → drawdown → stops → limits) |
| Execution (§2.6, §7.3) | `execution/` | `OrderManager` (idempotent current→target), `ExecutionAdapter` |
| Monitoring (§2.7) | `monitoring/` | `AuditLog`, `NavTracker`, `DriftMonitor`, `Deadman` |
| Engine (§3.1) | `engine/` | `TradingEngine` (shared), `Backtester`, `LiveRunner` |
| Friction & metrics (§3.2–3.3) | `backtest/` | `FillSimulator`, metric functions, `RunReport` |
| Validation (§4) | `validation/` | `PurgedKFold`, `CombinatorialPurgedCV`, `deflated_sharpe`, `ApproveForLiveGate` |
| Model lifecycle (FR10) | `model/` | `ModelRegistry`, champion-challenger, `RetrainScheduler` |
| Venues (§8) | `adapters/` | `HyperliquidAdapter`, `KrakenAdapter` |

## The one decision-path that goes live (NFR1)

`engine/loop.py::TradingEngine.handle` is **the** code that runs in production.
Backtest and live differ only in two injected objects:

- input: `data.source.HistoricalSource` (replay) vs `LiveSource` (venue feed)
- output: `backtest.friction.FillSimulator` vs a real `adapters.*` ExecutionAdapter

Per `MarketEvent`: `features → strategies (forecasts) → regime gate → combiner
(one target) → sizer → RiskGate (absolute) → OMS (idempotent) → adapter`.

## Two design tensions, resolved explicitly

**1. Stops vs. forecast netting (§5 vs §7).** §7 nets continuous forecasts into a
moving target with no discrete "positions", but §5 requires every position to carry
a hard, label-derived stop. v0.1 resolves this by mapping stops onto **net book
exposure per instrument**: `risk/stops.py` tracks a stop against the net position's
volume-weighted entry; a breach forces that instrument's target to flat (absolute
precedence, §7.2/§7.3) until the forecast re-establishes it. Per-entry stops are not
modeled — there are no "entries", only a net target.

**2. "Higher precedence" is weight, not override (§7.2).** Inside normal operation no
strategy hard-overrides another; they net by `validated_edge × live_confidence ×
risk_budget` (`arbitration/combiner.py`). Only the **risk layer** is a true override,
and it can only ever *reduce* risk (`risk/gate.py`). The regime gate sits between:
it can zero a forecast but never flip its sign.

## Anti-patterns the scaffold encodes against

- **No strategy issues orders** — the `Strategy` protocol returns `Forecast`, full stop.
- **No "ignore opposite signals for N minutes"** (§7.4) — the OMS deadband is sized in
  notional (cost hygiene), never in time; a genuine reversal always re-targets.
- **No tuning outside CV folds** (§4.4, NFR3) — feature selection / `min_ffd_order` /
  hyperparameters are documented to run inside `PurgedKFold` only.
- **No run without provenance** (§3.4) — `RunProvenance` (snapshot + commit + config)
  is part of every `RunReport`.

## Build order (follows §6.1 / §9)

1. `data/` ingest + store → `atb fetch`
2. `backtest/friction` + `metrics` → cheap, honest backtests
3. `strategy/baseline_trend` (the benchmark) → `atb backtest`
4. `features/` + `labeling` pipeline
5. `strategy/meta_label` (primary ML) — must beat #3 OOS after costs
6. `validation/` harness + `gate` → `atb validate`
7. `arbitration/` (build before strategy #2)
8. `engine/live` + `monitoring/` → `atb paper` → `atb live`
