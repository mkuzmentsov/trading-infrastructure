"""algo_trading_bot — systematic directional crypto trading bot.

Layered, swappable, independently testable. The *same engine drives backtest and
live*; only the data source and execution adapter differ (requirements §2, NFR1).

Layer map (top = highest precedence at runtime):

    monitoring/   logging, NAV, drift detection, deadman          §2.7
    execution/    idempotent current->target OMS, routing         §2.6
    risk/         limits, stops, drawdown breaker, kill switch     §2.5  (absolute precedence)
    arbitration/  combine forecasts -> one target position         §2.4 / §7
    strategy/     pluggable forecast generators, by risk tier      §2.3 / §6.2
    features/     point-in-time features, triple-barrier labels    §2.2
    data/         ingestion, point-in-time storage, normalization  §2.1
    ---
    engine/       event-driven core shared by backtest + live      §3.1
    validation/   purged CV, CPCV, PBO, deflated Sharpe, gate      §4
    adapters/     concrete venues (Hyperliquid, Kraken)            §2.1 / §8

Nothing here promises an edge. The design maximizes *survival probability* and
*test trustworthiness* (§11). The validation harness is the product (principle #1).
"""

__version__ = "0.1.0"
