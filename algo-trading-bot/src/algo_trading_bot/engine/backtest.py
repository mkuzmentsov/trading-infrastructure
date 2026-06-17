"""Backtest harness (§3) — wires the shared engine to historical data + a fill
simulator. NOT a separate strategy code path: only the source and adapter differ
(NFR1). A run is pinned to (data snapshot id + git commit + config) for provenance;
no provenance -> not trusted (§3.4, NFR2).
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from ..arbitration.combiner import ForecastCombiner
from ..arbitration.regime import RegimeGate, TrendRangeDetector
from ..arbitration.sizing import VolTargetSizer
from ..backtest import metrics as M
from ..backtest.friction import FillSimulator
from ..config import BotConfig
from ..core.clock import SimClock
from ..core.events import MarketEvent
from ..core.types import StrategyId, Symbol, VenueId
from ..data.bars import PERIODS_PER_YEAR
from ..data.source import HistoricalSource
from ..data.store import PointInTimeStore
from ..execution.oms import OrderManager
from ..features.pipeline import RollingFeaturePipeline
from ..risk.drawdown import DrawdownBreaker
from ..risk.gate import RiskGate
from ..risk.kill_switch import KillSwitch
from ..risk.limits import LimitChecker
from ..strategy.baseline_trend import TrendMomentum
from .loop import TradingEngine
from .portfolio import Portfolio


@dataclass
class RunProvenance:
    """Stamped onto every backtest result (§3.4, NFR2)."""

    data_snapshot_id: str
    git_commit: str
    config_hash: str
    started_at: datetime


@dataclass
class BacktestResult:
    provenance: RunProvenance
    equity: pd.Series
    returns: pd.Series
    trades: pd.DataFrame
    metrics: M.MetricsReport


class Backtester:
    def __init__(self, config: BotConfig) -> None:
        self.config = config
        self.store = PointInTimeStore(config.data_dir)

    def build_engine(self, strategies: list | None = None) -> TradingEngine:
        """Assemble the same TradingEngine used live, but with a SimClock + FillSimulator.

        ``strategies`` overrides the default trend baseline (used by the meta-label
        economic test). The clock start is set at run() time once the first bar is known.
        """
        cfg = self.config
        ppy = PERIODS_PER_YEAR[cfg.bar_interval]

        features = RollingFeaturePipeline(cfg.trend.ema_fast, cfg.trend.ema_slow, cfg.trend.vol_window)
        if strategies is None:
            strategies = [TrendMomentum(interval=cfg.bar_interval, scale=cfg.trend.scale)]
        regime_gate = RegimeGate(TrendRangeDetector())
        combiner = ForecastCombiner({s.id: 1.0 for s in strategies})
        sizer = VolTargetSizer(cfg.risk, cfg.starting_cash, ppy)

        kill = KillSwitch()
        drawdown = DrawdownBreaker(cfg.risk)
        limits = LimitChecker(cfg.risk, cfg.starting_cash, {VenueId(cfg.venue.name): cfg.venue.max_capital_quote})
        risk_gate = RiskGate(kill, drawdown, limits)

        sim = FillSimulator(cfg.friction)
        oms = OrderManager(sim, cfg.risk)
        portfolio = Portfolio(cfg.starting_cash)

        return TradingEngine(
            clock=SimClock(datetime(1970, 1, 1, tzinfo=timezone.utc)),
            features=features,
            strategies=strategies,
            regime_gate=regime_gate,
            combiner=combiner,
            sizer=sizer,
            risk_gate=risk_gate,
            oms=oms,
            portfolio=portfolio,
            drawdown=drawdown,
            venue=VenueId(cfg.venue.name),
        )

    def load_bars(self, start: datetime, end: datetime, venue: str | None = None) -> list:
        """Read the bar slice once so callers (e.g. a parameter grid) can reuse it
        without re-hitting Parquet per trial."""
        symbols = [Symbol(s) for s in self.config.universe]
        venue = venue or self.config.data_venue
        return list(HistoricalSource(self.store, symbols, start, end, venue=venue).stream())

    def run(
        self,
        start: datetime,
        end: datetime,
        venue: str | None = None,
        bars: list | None = None,
        strategies: list | None = None,
    ) -> BacktestResult:
        """Run the backtest and return equity curve, ledger, metrics, and provenance.

        ``bars`` may be a preloaded slice (from :meth:`load_bars`) to skip the read;
        ``strategies`` overrides the default trend baseline.
        """
        cfg = self.config
        symbols = [Symbol(s) for s in cfg.universe]
        venue = venue or cfg.data_venue  # None -> read any venue in the store

        if bars is None:
            bars = self.load_bars(start, end, venue)
        engine = self.build_engine(strategies)
        engine.run(MarketEvent(bar) for bar in bars)

        if not engine.equity_val:
            raise RuntimeError(
                f"no bars for {symbols} on {venue} in [{start:%Y-%m-%d}, {end:%Y-%m-%d}]. "
                f"Run `atb fetch` first."
            )

        equity = pd.Series(engine.equity_val, index=pd.to_datetime(engine.equity_ts), name="equity")
        returns = equity.pct_change().dropna()
        trades = pd.DataFrame(engine.trades)

        ppy = PERIODS_PER_YEAR[cfg.bar_interval]
        trade_pnls = trades["realized"].to_numpy() if not trades.empty else np.array([])
        turnover = float(trades["qty"].mul(trades["price"]).abs().sum() / cfg.starting_cash) if not trades.empty else 0.0
        report = M.compute(
            equity.to_numpy(), returns.to_numpy(), trade_pnls,
            periods_per_year=ppy, turnover=turnover,
        )
        return BacktestResult(self._provenance(symbols, start, end, venue), equity, returns, trades, report)

    # --- reproducibility (§3.4) ---
    def _provenance(self, symbols, start, end, venue) -> RunProvenance:
        cfg_hash = hashlib.sha256(self.config.model_dump_json().encode()).hexdigest()[:16]
        try:
            commit = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
        except Exception:
            commit = "unknown"
        return RunProvenance(
            data_snapshot_id=self.store.snapshot_id(symbols, start, end, venue),
            git_commit=commit,
            config_hash=cfg_hash,
            started_at=datetime.now(timezone.utc),
        )
