"""Live / paper runner (§9 Phase 6–7).

Runs the *same* TradingEngine as the backtest (NFR1); only the data source, the
execution adapter, and the operational shell differ. Adds: structured per-bar audit
logging (NFR6), NAV/position persistence with safe restart (NFR4), and a heartbeat.

Modes:
* **paper** — simulated fills against live marks (FillSimulator). No keys, no real
  orders. Safe to run anywhere; the default.
* **live** — real orders via a venue adapter. GUARDED: refuses to start unless a
  recorded approve-for-live gate pass exists and the operator passes ``confirm=True``.
  Nothing has cleared the gate yet, so this path intentionally stays shut.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from ..config import BotConfig
from ..core.events import MarketEvent
from ..core.types import Position, Symbol
from ..data.live_source import ccxt_poll_source, replay_source
from ..monitoring.audit_log import AuditLog
from .backtest import Backtester


class LiveRunner:
    def __init__(
        self,
        config: BotConfig,
        *,
        mode: str = "paper",
        source: str = "replay",
        speed: float = 20.0,
        max_bars: int | None = None,
        state_dir: str = "./state",
    ) -> None:
        self.config = config
        self.mode = mode
        self.source = source
        self.speed = speed
        self.max_bars = max_bars
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.state_dir / f"{config.name}_state.json"
        self.audit = AuditLog(self.state_dir / f"{config.name}_decisions.jsonl")

    # --- persistence (NFR4) ---
    def _restore(self, engine) -> int:
        if not self.state_path.exists():
            return 0
        st = json.loads(self.state_path.read_text())
        engine.portfolio.cash = st["cash"]
        for sym, p in st.get("positions", {}).items():
            engine.portfolio.positions[Symbol(sym)] = Position(
                symbol=Symbol(sym), quantity=p["quantity"],
                avg_price=p["avg_price"], realized_pnl=p["realized_pnl"],
            )
        return int(st.get("bars_processed", 0))

    def _persist(self, engine, bars_processed: int, last_ts) -> None:
        st = {
            "cash": engine.portfolio.cash,
            "positions": {
                str(s): {"quantity": p.quantity, "avg_price": p.avg_price,
                         "realized_pnl": p.realized_pnl}
                for s, p in engine.portfolio.positions.items()
            },
            "equity_last": engine.equity_val[-1] if engine.equity_val else engine.portfolio.cash,
            "bars_processed": bars_processed,
            "last_ts": str(last_ts),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self.state_path.write_text(json.dumps(st, indent=2))

    # --- sources ---
    def _make_source(self):
        if self.source == "replay":
            bars = Backtester(self.config).load_bars(
                datetime(2000, 1, 1, tzinfo=timezone.utc), datetime.now(timezone.utc)
            )
            if not bars:
                raise RuntimeError("no stored bars to replay — run `atb fetch` first")
            return replay_source(bars, speed=self.speed, max_bars=self.max_bars)
        if self.source == "live":
            return ccxt_poll_source(
                self.config.data_venue or self.config.venue.name,
                self.config.universe, self.config.bar_interval, max_bars=self.max_bars,
            )
        raise ValueError(f"unknown source {self.source!r} (replay|live)")

    # --- run ---
    def run(self) -> None:
        if self.mode == "live":
            self._guard_live()  # raises unless explicitly cleared

        engine = Backtester(self.config).build_engine()
        restored = self._restore(engine)
        print(f"[{self.config.name}] mode={self.mode} source={self.source} "
              f"restored_bars={restored} cash={engine.portfolio.cash:,.0f}")

        i = restored
        last_ts = None
        for bar in self._make_source():
            engine.handle(MarketEvent(bar))
            i += 1
            last_ts = bar.ts
            nav = engine.equity_val[-1]
            lev = engine.leverage_val[-1]
            pos = engine.portfolio.position(bar.symbol)
            self.audit.decision("bar", bar.ts, {
                "symbol": str(bar.symbol), "close": bar.close, "nav": round(nav, 2),
                "leverage": round(lev, 3), "position": round(pos.quantity, 6),
                "halted": engine.drawdown.halted,
            })
            if i % 20 == 0:
                print(f"[{bar.ts:%Y-%m-%d %H:%M}] nav={nav:,.0f} lev={lev:.2f} "
                      f"pos={pos.quantity:+.4f} halted={engine.drawdown.halted}")
                self._persist(engine, i, last_ts)
        self._persist(engine, i, last_ts)
        final = engine.equity_val[-1] if engine.equity_val else engine.portfolio.cash
        print(f"[{self.config.name}] done. bars={i} final_nav={final:,.0f} "
              f"(state -> {self.state_path})")

    def _guard_live(self) -> None:
        gate_pass = self.state_dir / f"{self.config.name}_gate_pass.json"
        if not gate_pass.exists():
            raise SystemExit(
                "REFUSING live (real-money) trading: no approve-for-live gate pass found at "
                f"{gate_pass}. No strategy has cleared the gate (§4). Use --mode paper."
            )
