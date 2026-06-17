"""The shared decision loop (§3.1, NFR1) — THE code that goes to production.

One event at a time, in timestamp order. Backtest and live instantiate the *same*
``TradingEngine`` with different data sources and execution adapters; the decision
path below is identical, which is the whole point (principle #9, NFR1).

Per MarketEvent, the pipeline is exactly the layer stack, top precedence last:

    bar -> features.update
        -> strategies.on_data        (forecasts, never orders)        §2.3
        -> regime gate               (zero ineligible forecasts)      §2.4/§7.2
        -> combiner                  (net -> one combined forecast)   §7.1
        -> sizer                     (vol-target, Kelly cap -> target)§2.4
        -> RiskGate.approve          (ABSOLUTE: kill/dd/stops/limits) §2.5/§7.2
        -> OMS.reconcile             (idempotent current->target)     §2.6/§7.3
        -> adapter.place
    fills -> portfolio, NAV, drawdown breaker, ledger.
"""

from __future__ import annotations

from ..arbitration.combiner import ForecastCombiner
from ..arbitration.regime import RegimeGate
from ..arbitration.sizing import VolTargetSizer
from ..core.clock import SimClock
from ..core.events import Event, FillEvent, MarketEvent, TimerEvent
from ..core.types import Symbol, VenueId
from ..execution.oms import OrderManager
from ..features.pipeline import FeaturePipeline
from ..risk.drawdown import DrawdownBreaker
from ..risk.gate import RiskGate
from ..strategy.base import MarketState
from .portfolio import Portfolio


class TradingEngine:
    def __init__(
        self,
        clock,
        features: FeaturePipeline,
        strategies: list,
        regime_gate: RegimeGate,
        combiner: ForecastCombiner,
        sizer: VolTargetSizer,
        risk_gate: RiskGate,
        oms: OrderManager,
        portfolio: Portfolio,
        drawdown: DrawdownBreaker,
        venue: VenueId = VenueId(""),
    ) -> None:
        self.clock = clock
        self.features = features
        self.strategies = strategies
        self.regime_gate = regime_gate
        self.combiner = combiner
        self.sizer = sizer
        self.risk_gate = risk_gate
        self.oms = oms
        self.portfolio = portfolio
        self.drawdown = drawdown
        self.venue = venue
        self._marks: dict[Symbol, float] = {}
        # backtest collectors (a live monitor would stream these instead of buffering)
        self.equity_ts: list = []
        self.equity_val: list[float] = []
        self.leverage_val: list[float] = []      # gross exposure / equity per bar (§2.7 / stress)
        self.orders_per_bar: list[int] = []
        self.trades: list[dict] = []

    def run(self, events) -> None:
        """Consume an ordered event iterator to exhaustion (backtest) or forever (live)."""
        for event in events:
            self.handle(event)

    def handle(self, event: Event) -> None:
        if isinstance(event, MarketEvent):
            self._on_market(event)
        elif isinstance(event, FillEvent):
            self.portfolio.apply_fill(event.fill)
        elif isinstance(event, TimerEvent):
            pass  # heartbeat/retrain/drift hooks land with the monitoring slice

    def _on_market(self, event: MarketEvent) -> None:
        bar = event.bar
        sym = bar.symbol
        if isinstance(self.clock, SimClock):
            self.clock.advance_to(bar.known_at())
        self._marks[sym] = bar.close

        feats = self.features.update(bar)

        # Let the fill simulator mark this symbol so any orders fill at this price.
        if hasattr(self.oms.adapter, "update_market"):
            self.oms.adapter.update_market(sym, bar.close, bar.ts)

        if feats.get("ready", 0.0) >= 1.0:
            state = MarketState(clock=self.clock, latest_bar=bar, features=feats)
            forecasts = []
            for strat in self.strategies:
                fc = strat.on_data(state)
                if fc is None:
                    continue
                regime = self.regime_gate.detector.detect(feats)
                forecasts.append(self.regime_gate.apply(fc, strat.tier, regime))

            combined = self.combiner.combine(forecasts, self.clock.now())
            cf = combined.get(sym)
            if cf is not None:
                target = self.sizer.size(sym, cf, feats["ret_vol"], bar.ts)
                approved = self.risk_gate.approve(
                    target, self.portfolio.positions, bar.close, self.venue
                )
                self.oms.reconcile(approved, self.portfolio.position(sym), bar.close)

        # Settle fills, then mark NAV and update the drawdown breaker for the next bar.
        n_fills = 0
        for fill in self.oms.adapter.poll_fills():
            n_fills += 1
            realized = self.portfolio.apply_fill(fill)
            self.trades.append(
                {"ts": fill.ts, "symbol": fill.symbol, "side": fill.side.name,
                 "qty": fill.quantity, "price": fill.price, "fee": fill.fee, "realized": realized}
            )

        nav = self.portfolio.equity(self._marks)
        self.drawdown.update(nav)
        gross = sum(abs(p.quantity * self._marks.get(s, p.avg_price))
                    for s, p in self.portfolio.positions.items())
        self.equity_ts.append(bar.ts)
        self.equity_val.append(nav)
        self.leverage_val.append(gross / nav if nav > 0 else float("inf"))
        self.orders_per_bar.append(n_fills)
