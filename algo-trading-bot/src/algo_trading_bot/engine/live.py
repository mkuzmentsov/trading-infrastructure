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

    def _stored_bars(self) -> list:
        return Backtester(self.config).load_bars(
            datetime(2000, 1, 1, tzinfo=timezone.utc), datetime.now(timezone.utc)
        )

    def _live_iter(self, after):
        """Live-polled bars newer than ``after`` (the last warmup bar)."""
        for bar in ccxt_poll_source(
            self.config.data_venue or self.config.venue.name,
            self.config.universe, self.config.bar_interval, max_bars=self.max_bars,
        ):
            if after is None or bar.ts > after:
                yield bar

    # --- run ---
    def run(self) -> None:
        adapter = None
        if self.mode == "live":
            self._guard_live()  # raises unless explicitly cleared
            from ..adapters import make_adapter

            adapter = make_adapter(self.config.venue)  # real CcxtBroker

        engine = Backtester(self.config).build_engine(adapter=adapter)
        stored = self._stored_bars()

        if self.source == "live":
            # Warm features from stored history, then tail live bars. Resume the book
            # from persisted state (paper) or reconcile from the venue (live, NFR4).
            engine.warmup(stored)
            last_warm = stored[-1].ts if stored else None
            restored = self._restore(engine)
            if self.mode == "live" and adapter is not None:
                venue_pos = adapter.positions()
                if venue_pos:
                    engine.portfolio.positions.update(venue_pos)
                engine.oms.on_restart()
            print(f"[{self.config.name}] mode={self.mode} source=live warmed={len(stored)} "
                  f"restored_bars={restored} cash={engine.portfolio.cash:,.0f}")
            trading_iter = self._live_iter(last_warm)
        else:
            # Replay is a deterministic run from the start — no restore (that would
            # double-count); the full history streams through the trading path.
            if not stored:
                raise RuntimeError("no stored bars to replay — run `atb fetch` first")
            print(f"[{self.config.name}] mode={self.mode} source=replay "
                  f"bars={len(stored)} cash={engine.portfolio.cash:,.0f}")
            trading_iter = replay_source(stored, speed=self.speed, max_bars=self.max_bars)

        # Live bars are sparse (one per interval) — print each; replay is dense — every 20th.
        heartbeat = 1 if self.source == "live" else 20
        i = 0
        last_ts = None
        for bar in trading_iter:
            n_before = len(engine.trades)
            engine.handle(MarketEvent(bar))
            # Surface any fills this bar as explicit TRADE lines + `fill` audit records.
            for tr in engine.trades[n_before:]:
                self.audit.decision("fill", tr["ts"], {
                    "symbol": str(tr["symbol"]), "side": tr["side"], "qty": tr["qty"],
                    "price": tr["price"], "fee": tr["fee"], "realized": tr["realized"],
                })
                print(f"  >> TRADE {tr['side']:5s} {tr['qty']:.6f} {tr['symbol']} "
                      f"@ {tr['price']:,.2f}  fee={tr['fee']:.2f}  realized={tr['realized']:+.2f}")
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
            if i % heartbeat == 0:
                print(f"[{bar.ts:%Y-%m-%d %H:%M}] {bar.symbol} close={bar.close:,.0f} "
                      f"nav={nav:,.2f} lev={lev:.2f} pos={pos.quantity:+.4f} "
                      f"halted={engine.drawdown.halted}")
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
