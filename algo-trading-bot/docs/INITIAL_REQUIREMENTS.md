# Crypto Trading Bot — Project Design & Requirements (v0.3)

> **Scope:** A *directional* crypto trading bot — pattern-based and ML-driven — that takes real market risk to speculate. Market-neutral carry/arb is explicitly **out of scope** (separate project). The existing `trading-mcp` server is kept **separate**; this system talks to it (if at all) only through a clean adapter boundary.

## 0. Purpose

Design foundation for a systematic directional crypto trading bot that is **profitable**, **robust to changing market regimes**, and **cheap and trustworthy to test on historical data**. Sections marked *(decide)* are open requirements.

---

## 1. Guiding principles (read this part twice)

Directional ML trading is the hardest category of systematic trading. These principles separate the few bots that survive from the many that look great in a notebook and die in production.

1. **The validation harness IS the product.** The model is a few lines of code. The machinery that stops a backtest from lying to you is the real engineering.
2. **Signal-to-noise is brutally low.** Assume any "edge" is an overfit artifact until proven otherwise out-of-sample.
3. **Separate side from size (meta-labeling).** A simple primary model decides *side* (long/short); an ML model decides only *whether to act and how big*.
4. **Beat a dumb baseline or don't ship.** A plain directional rule is the benchmark; ML earns its place only by beating it OOS, after costs.
5. **Survival before profit.** Risk management decides whether you're alive in two years; the model decides how much you make.
6. **Signals become forecasts, not orders.** Strategies emit a continuous forecast; the portfolio layer nets all forecasts into one target position; execution trades the gap. No strategy issues orders directly. (See §7.)
7. **Risk has absolute precedence.** Stops, drawdown breakers, and the kill switch override every strategy signal, always. (See §7.2.)
8. **Regime-awareness is survival.** A trend model bleeds in a range; a mean-reversion model dies in a trend. Detect regime and gate strategies accordingly.
9. **Backtest == live, same code.** No model goes live through different code than it was validated with.
10. **Models and edges decay fast.** Retraining cadence and live-vs-expected drift monitoring with auto-disable are first-class features.
11. **Prefer simple models.** Gradient-boosted trees on engineered tabular features beat deep learning on small, noisy financial data and overfit far less. DL is a later, deliberate choice.
12. **Favor positive skew.** Strategies that cut losers and ride winners (trend) survive; strategies with many small wins and rare large losses (mean reversion) blow up accounts. Allocate risk budget accordingly. (See §6.2.)

---

## 2. System architecture

Layered, swappable, independently testable. The **same engine drives backtest and live** — only the data source and execution adapter differ.

```
┌─────────────────────────────────────────────────────────┐
│  Monitoring / Ops: logging, alerting, NAV, drift detect  │
├─────────────────────────────────────────────────────────┤
│  Execution: order mgmt (current→target), routing, slippage│
├─────────────────────────────────────────────────────────┤
│  Risk: limits, stops, drawdown breaker, kill switch       │  ← absolute precedence
├─────────────────────────────────────────────────────────┤
│  Arbitration / Sizing: combine forecasts → target position│  ← §7
├─────────────────────────────────────────────────────────┤
│  Strategy: pluggable forecast generators (by risk tier)   │  ← §6.2
├─────────────────────────────────────────────────────────┤
│  Feature & Label: point-in-time features, triple-barrier  │
├─────────────────────────────────────────────────────────┤
│  Data: ingestion, point-in-time storage, normalization    │
└─────────────────────────────────────────────────────────┘
```

### 2.1 Data layer
- Ingest OHLCV (and order-book L2 if short-horizon), plus context series: volatility, funding/OI (as *features*, not as the strategy), BTC dominance / cross-asset.
- **Point-in-time correctness.** Every record stamped with when it was *knowable*. No lookahead.
- Storage: Parquet + DuckDB to start; scale to ClickHouse/Timescale if needed.
- Venues: Kraken, Binance, WhiteBIT, Hyperliquid via CCXT + native HL SDK. *(decide: primary venue(s) and instruments.)*
- *(decide: data granularity — driven by holding period, §6.0.)*

### 2.2 Feature & label layer
- **Point-in-time feature computation.** Features computable using only past data at each timestamp. Lookahead in feature calc is the most common, most fatal ML-trading bug.
- **Stationarity with memory:** fractional differentiation rather than naive differencing.
- **Triple-barrier labeling:** label each event by which barrier hits first — take-profit, stop-loss, or time limit — aligning training with how the bot actually exits.
- **Sample weighting** for overlapping labels.
- Feature families: price/volume & TA, realized/implied vol, order-flow/book imbalance (short-horizon only), cross-asset & dominance, funding/OI as context, calendar/seasonality; optionally on-chain & sentiment *(decide)*.

### 2.3 Strategy layer
- Each strategy implements `on_data(state) -> forecast` where **forecast is a continuous, scaled value** (e.g. −1…+1), not an order. Organized by risk tier (§6.2).

### 2.4 Arbitration / sizing layer
- Combines all strategy forecasts into a **single target position** via risk-weighted netting (§7).
- **Volatility targeting:** scale total exposure to a target portfolio vol; auto-shrink when realized vol spikes.
- **Regime gate:** enable/disable or reweight strategies by detected regime.
- **Sizing:** confidence-scaled, capped, fraction-of-Kelly (≤ half).

### 2.5 Risk layer
- Hard limits: per-instrument position, gross/net exposure, leverage ceiling, per-venue cap.
- **Stops** mapped from the triple-barrier exits used in training.
- **Drawdown circuit breaker:** tiered — de-risk at threshold 1, halt at threshold 2.
- Kill switch (manual + automatic). Pre-trade limit checks on every order. **Absolute precedence over all signals.**

### 2.6 Execution layer
- Idempotent order management that always works toward the **latest** target; cancels/replaces stale in-flight orders rather than completing them (§7.3).
- Slippage-aware placement; handle partial fills, rejects, disconnects, safe restart from persisted state.

### 2.7 Monitoring / ops layer
- Structured logging of every decision and order.
- **Live-vs-expected drift detection;** auto-disable a model on degradation.
- NAV tracking, anomaly alerting, heartbeat/deadman switch.

---

## 3. Backtesting engine (the "test easily" requirement)

### 3.1 Event-driven, shared with live
- **Event-driven** core processing one event at a time, exactly as live — this is what goes to production. Evaluate `nautilus_trader` for backtest/live parity.
- **Vectorized** (vectorbt) only as a fast first-pass screener — never the final word, watched for lookahead.

### 3.2 Realistic friction (non-optional)
- Maker/taker fees with tiers; funding at real settlement times; size/liquidity-scaled slippage; signal-to-fill latency; borrow/margin costs.

### 3.3 Deliverables per run
- Equity curve, returns series, trade-by-trade ledger.
- Metrics: CAGR, vol, **Sharpe + deflated Sharpe**, Sortino, max drawdown & duration, turnover, hit rate, profit factor, **skew/kurtosis**, exposure.
- Per-regime breakdown.

### 3.4 Reproducibility
- Every run pinned to data snapshot + code commit + config. No provenance → not trusted.

---

## 4. Validation & robustness methodology (the core)

For directional ML this is the thing that determines whether the bot is real. ML explores enormous hypothesis spaces, so the bar is higher than for rule-based systems.

1. **Purged & embargoed K-fold CV — mandatory.** Purge train samples overlapping the test window and embargo a gap, or labels leak and every metric is inflated.
2. **Combinatorial Purged Cross-Validation (CPCV)** for a *distribution* of OOS backtest paths and the **Probability of Backtest Overfitting (PBO)**.
3. **Deflated Sharpe ratio** — penalize for number of trials.
4. **All tuning inside CV folds.** Feature selection / hyperparameter search on the full set is leakage.
5. **Walk-forward with periodic retraining,** mirroring live model lifecycle.
6. **Feature importance with substitution awareness (MDA).**
7. **Regime segmentation** — acceptable everywhere, not spectacular in one regime.
8. **Stress / scenario replay** — flash crashes, outages, funding spikes, de-pegs; must behave *safely*.
9. **Paper-trading gate** before real capital.

"Approved for live" requires clearing all of the above. This gate is itself a deliverable.

---

## 5. Risk management framework

- **Sizing:** confidence-scaled, vol-targeted, fraction-of-Kelly, hard leverage ceiling.
- **Stops:** every position has predefined exits matching its training labels.
- **Per-strategy risk budget** (§6.2) that a strategy cannot exceed.
- **Drawdown governance:** tiered de-risk → halt.
- **Counterparty/venue risk:** capital per exchange capped; assume any venue can freeze or fail.
- **Operational risk:** reconciliation, deadman switch, safe restart.

---

## 6. Strategy approach — directional / ML

### 6.0 Holding period drives everything *(decide first)*
Dictates data granularity, feature sources, infra, and cost sensitivity:
- **Scalping / intraday (sec–min):** needs L2 data, low latency, cost/microstructure dominated. Hardest.
- **Swing (hours–days):** OHLCV + engineered features sufficient; sweet spot for ML meta-labeling. **Recommended start.**
- **Position (days–weeks):** trend-following; fewer trades, lower cost sensitivity, macro/regime-driven.

### 6.1 Build order
1. Dumb directional baseline (the benchmark). → 2. Feature + triple-barrier labeling pipeline. → 3. Meta-label ML layer. → 4. Regime gate + vol-targeted sizing. → 5. (later) additional uncorrelated strategies.

### 6.2 Strategy catalog by risk tier

Strategies are selected and budgeted by **foreseen risk**: skew, tail/blow-up risk, regime dependence, and overfit risk. Each tier gets a risk budget; the **regime gate** turns strategies on/off based on foreseen conditions; **vol-targeting** shrinks the whole book when forward volatility is high. Higher-tail strategies get smaller budgets, harder stops, and more aggressive gating.

| Tier | Strategy | What it does | Risk profile | Treatment |
|---|---|---|---|---|
| **1 — Foundation** | **Time-series (trend) momentum** | Trade in direction of an established trend; trail stops | Positive skew, lower blow-up risk, bleeds in chop | Largest risk budget; the §6.1 baseline; first to build |
| **1 — Foundation** | **Volatility breakout** | Enter on range breaks confirmed by vol expansion | Positive skew, trend-family | Core trend exposure; gated off in dead ranges |
| **2 — Core** | **Cross-sectional momentum** | Rank a universe, long strongest / short weakest | Moderate; diversifies single-asset trend | Needs an asset universe; moderate budget |
| **2 — Core** | **Meta-labeled momentum (main ML)** | ML overlay filters/sizes Tier-1 signals | Same skew as trend, higher precision | The primary ML strategy; budget grows as it beats baseline OOS |
| **2 — Core** | **Pattern-based (ML-learned setups)** | ML detects recurring setups; feeds meta-labeling | Moderate, higher overfit risk | Strictly validated; feeds the meta-label, not standalone orders |
| **3 — Tactical** | **Mean reversion / counter-trend** | Fade extremes back toward mean in ranges | **Negative skew, high tail risk** | Small budget, hard stops, **gated OFF in strong trends** |
| **3 — Tactical** | **Short-horizon ML pattern** | Fast intraday setups | High cost sensitivity + overfit risk | Smallest budget; only if scalping infra is justified |

**Out of scope:** carry/basis (separate project), market making, pure arbitrage.

**Risk-based selection mechanism (three layers):**
1. **Static budgets** — positive-skew/lower-tail strategies get the most risk; negative-skew ones are capped.
2. **Dynamic regime gate** — activates the strategies suited to the *foreseen* regime (e.g. momentum in trend, mean reversion only in confirmed range, everything shrunk in high-vol).
3. **Volatility targeting** — scales total exposure inversely to forward volatility.

---

## 7. Signal arbitration & precedence

The question "which signal wins if an opposite one fires mid-position?" is real and important. The design answers it by **not letting signals fight as discrete events.**

### 7.1 Principle: forecasts → one target position
Every strategy emits a continuous **forecast** (direction × strength), never an order. The arbitration layer combines them into a **single target position**; execution trades the gap between current and target. A new opposite signal does not "cancel" an open trade — it changes the combined forecast, hence the target, and the bot moves toward the new target. (Carver combined-forecast approach.)

### 7.2 Precedence hierarchy (top wins)
1. **Risk layer — absolute.** Stops, drawdown breaker, kill switch override everything, instantly.
2. **Regime gate.** Can zero out a strategy's forecast entirely.
3. **Combined weighted forecast → target.** Weight = *validated edge quality × live confidence × risk budget*. In normal operation **no single strategy hard-overrides another — they net.** "Higher precedence" = higher weight, not a priority rank.

### 7.3 The conflict scenario: long from A, opposite B fires
- B re-weights the combined forecast → new net target. Bot trades toward it.
- Net flips strongly negative → reduce/close long, possibly go short, smoothly.
- A ≈ B in strength → net target ≈ flat → move to near-neutral.
- **In-flight reconciliation:** if a buy is partially filled when the target flips, the OMS cancels the remainder and works toward the *latest* target; it never completes a now-stale order. Requires an idempotent current→target OMS.
- **Buffer / deadband (hysteresis):** ignore sub-threshold target changes to avoid whipsaw and fee bleed near a flip point.
- **If B is a risk/stop signal:** absolute precedence — flatten now.

### 7.4 Anti-pattern (do NOT do this)
Do **not** add a rule like *"ignore opposite signals for N minutes to protect the open position."* Buffering filters *noise*; suppressing genuine *reversals* to defend a thesis is the negative-skew behavior that turns a small loss into ruin. The buffer is transaction-cost hygiene, never a refusal to be wrong.

### 7.5 Practical guards
- **Signal staleness:** forecasts have validity windows; a stale forecast decays toward zero.
- **Min-trade threshold:** don't trade dust toward the target.
- **Cost-aware rebalancing:** only move toward target when expected benefit > expected cost.

---

## 8. Proposed tech stack

| Layer | Proposal | Notes |
|---|---|---|
| Language | Python | Ecosystem + tooling fit. |
| Connectivity | CCXT + native Hyperliquid SDK | `trading-mcp` kept separate, behind an adapter. |
| Backtest | nautilus_trader (evaluate) + vectorbt (screening) | Live parity vs. fast research. |
| ML | scikit-learn + LightGBM/XGBoost | Tabular GBTs first; DL deferred. |
| Fin-ML tooling | triple-barrier / purged-CV / DSR | Vetted implementation or build directly. |
| Storage | Parquet + DuckDB → ClickHouse later | Start simple. |
| State/orchestration | Persisted state; idempotent restart | Survive crashes. |
| Monitoring | Structured logs + metrics + drift alerts | Live-vs-expected tracking. |
| Deployment | *(decide: VPS vs. cloud)* | Latency matters only for scalping. |

---

## 9. Phased roadmap

- **Phase 0 — Requirements + decide holding period.** *(current)*
- **Phase 1 — Data infrastructure** (point-in-time, incl. context series).
- **Phase 2 — Backtest engine** with realistic friction + metrics suite.
- **Phase 3a — Tier-1 baseline** (trend/breakout). Establish the benchmark.
- **Phase 3b — Feature + triple-barrier labeling pipeline.**
- **Phase 3c — Meta-label ML model.** Must beat baseline OOS, after costs.
- **Phase 4 — Validation harness** (purged/embargoed CV, CPCV, PBO, deflated Sharpe, regime, stress). Approve-for-live gate.
- **Phase 5 — Arbitration + sizing layer** (forecast netting, regime gate, vol-targeting). *Build before adding strategy #2.*
- **Phase 6 — Paper trading.** Confirm backtest↔live parity.
- **Phase 7 — Live, small capital + monitoring + drift auto-disable.**
- **Phase 8 — Expansion:** add Tier-2/3 strategies into the arbitration layer, scale.

---

## 10. Initial requirements

**Functional**
- FR1: Ingest/store historical + live market and context data, point-in-time correct.
- FR2: Compute features with no lookahead; label via triple-barrier.
- FR3: Strategies emit continuous forecasts (not orders) via a common interface; tiered per §6.2.
- FR4: Arbitration layer nets forecasts into one target position with risk-weighted, regime-gated, vol-targeted sizing (§7).
- FR5: Idempotent execution that always works toward the latest target and reconciles in-flight orders.
- FR6: Risk layer with absolute precedence — limits, stops, drawdown breaker, kill switch.
- FR7: Reproducible, cost-realistic backtest reports with per-regime + skew metrics.
- FR8: Validation harness implementing §4 with an explicit approve-for-live gate.
- FR9: Live-vs-expected drift monitoring with automatic model disable.
- FR10: Model lifecycle — scheduled retraining, registry, champion-challenger.

**Non-functional**
- NFR1: Backtest and live share the same decision code path.
- NFR2: Every backtest reproducible (data snapshot + commit + config).
- NFR3: All tuning/feature-selection occurs inside CV folds.
- NFR4: System recovers to correct state after crash/restart.
- NFR5: Capital per exchange bounded and configurable.
- NFR6: All decisions and orders logged for audit.
- NFR7: Signal arbitration is deterministic and replayable from logged forecasts.

---

## 11. Honest caveats

- **No design guarantees profit, and directional ML is the hardest case.** Base rate for profitable retail directional ML bots is low; cause is almost always overfitting + underestimated costs. This design maximizes *survival probability* and *test trustworthiness* — it does not promise an edge.
- **Backtest overfitting is never eliminated, only reduced.** Live results are the only real test.
- **Directional = market risk by definition.** Risk sizing and stops are what keep being-wrong survivable.
- **Negative-skew strategies (Tier 3) are account-killers if mis-sized.** Keep their budgets small and their stops hard.
- **Edges decay.** Plan for models to stop working; build monitoring that catches it before the drawdown does.

---

*Next decision points: (1) **holding period / horizon** (§6.0 — drives everything); (2) primary venue & instruments; (3) nautilus_trader vs. custom engine; (4) data granularity; (5) feature sources (on-chain / sentiment?); (6) initial asset universe (needed for cross-sectional momentum).*