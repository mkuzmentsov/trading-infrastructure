"""The shared decision loop (§3.1, NFR1) — THE code that goes to production.

One event at a time, in timestamp order. Backtest and live instantiate the *same*
``TradingEngine`` with different data sources and execution adapters; the decision
path below is byte-identical, which is the whole point (principle #9, NFR1). Because
every decision is derived only from logged events + forecasts, a run is fully
replayable (NFR7).

Per MarketEvent, the pipeline is exactly the layer stack, top precedence last:

    bar -> features.update
        -> strategies.on_data        (forecasts, never orders)        §2.3
        -> regime gate               (zero ineligible forecasts)      §2.4/§7.2
        -> combiner                  (net -> one combined forecast)   §7.1
        -> sizer                     (vol-target, Kelly cap -> target)§2.4
        -> RiskGate.approve          (ABSOLUTE: kill/dd/stops/limits) §2.5/§7.2
        -> OMS.reconcile             (idempotent current->target)     §2.6/§7.3
        -> adapter.place / cancel
    FillEvent -> positions, NAV, stops, drift, ledger.
"""

from __future__ import annotations

from ..arbitration.combiner import ForecastCombiner
from ..arbitration.regime import RegimeGate
from ..arbitration.sizing import VolTargetSizer
from ..core.clock import Clock
from ..core.events import Event, FillEvent, MarketEvent, TimerEvent
from ..execution.oms import OrderManager
from ..features.pipeline import FeaturePipeline
from ..risk.gate import RiskGate


class TradingEngine:
    def __init__(
        self,
        clock: Clock,
        features: FeaturePipeline,
        strategies: list,
        regime_gate: RegimeGate,
        combiner: ForecastCombiner,
        sizer: VolTargetSizer,
        risk_gate: RiskGate,
        oms: OrderManager,
        monitor=None,
    ) -> None:
        self.clock = clock
        self.features = features
        self.strategies = strategies
        self.regime_gate = regime_gate
        self.combiner = combiner
        self.sizer = sizer
        self.risk_gate = risk_gate
        self.oms = oms
        self.monitor = monitor

    def run(self, events) -> None:
        """Consume an ordered event iterator to exhaustion (backtest) or forever (live)."""
        for event in events:
            self.handle(event)

    def handle(self, event: Event) -> None:
        if isinstance(event, MarketEvent):
            self._on_market(event)
        elif isinstance(event, FillEvent):
            self._on_fill(event)
        elif isinstance(event, TimerEvent):
            self._on_timer(event)
        # OrderEvent/FundingEvent handled within the above flows.

    def _on_market(self, event: MarketEvent) -> None:
        raise NotImplementedError(
            "advance clock to bar.known_at(); update features; collect forecasts; "
            "gate -> combine -> size -> risk.approve -> oms.reconcile -> adapter."
        )

    def _on_fill(self, event: FillEvent) -> None:
        raise NotImplementedError("update positions, NAV, stop levels; log to ledger (NFR6)")

    def _on_timer(self, event: TimerEvent) -> None:
        raise NotImplementedError("heartbeat/deadman, retrain check, drift check (§2.7)")
