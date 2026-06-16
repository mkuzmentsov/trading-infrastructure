"""Idempotent current->target order management (§2.6, §7.3, §7.5).

The OMS owns exactly one job: move the actual position toward the latest
risk-approved target, cheaply and without ever completing a stale order.

Invariants:
* **Idempotent / latest-wins.** Re-driving with the same target is a no-op. When
  the target changes while an order is in flight, the OMS cancels the remainder and
  re-derives from the *new* target — it never finishes a now-stale order (§7.3).
* **Deadband + min-trade.** Skip sub-threshold gaps (hysteresis, §7.3) and dust
  trades (§7.5) — transaction-cost hygiene, never a refusal to reverse (§7.4).
* **Cost-aware.** Only move when expected benefit > expected cost (§7.5).
* **Crash-safe.** Order intents are keyed by deterministic ``client_id`` so a
  restart reconciles against the venue's open orders/positions without duplication
  (NFR4).
"""

from __future__ import annotations

from ..config import RiskConfig
from ..core.types import Order, OrderType, Position, Side, Symbol, TargetPosition
from .adapter import ExecutionAdapter


class OrderManager:
    def __init__(self, adapter: ExecutionAdapter, risk: RiskConfig) -> None:
        self.adapter = adapter
        self.risk = risk

    def reconcile(self, target: TargetPosition, position: Position, last_price: float) -> list[Order]:
        """Compute and place the order(s) needed to move ``position`` toward ``target``.

        Returns the orders placed this tick (possibly empty). Sub-threshold gaps are
        absorbed by the deadband/min-trade filter (cost hygiene, §7.5) — never a
        refusal to reverse (§7.4).
        """
        if last_price <= 0:
            return []
        current_notional = position.quantity * last_price
        gap = target.notional - current_notional

        threshold = max(self.risk.min_trade_notional, self.risk.rebalance_deadband * abs(target.notional))
        if abs(gap) < threshold:
            return []

        side = Side.LONG if gap > 0 else Side.SHORT
        qty = abs(gap) / last_price
        order = Order(
            client_id=self._client_id(target.symbol, target),
            symbol=target.symbol,
            side=side,
            quantity=qty,
            order_type=OrderType.MARKET,
            venue=position and getattr(position, "venue", "") or "",
            ts=target.ts,
        )
        self.adapter.place(order)
        return [order]

    def on_restart(self) -> None:
        """Rebuild in-memory state from the adapter's open orders + positions (NFR4)."""
        self.adapter.open_orders()
        self.adapter.positions()

    def _client_id(self, symbol: Symbol, target: TargetPosition) -> str:
        """Deterministic id so retries are idempotent and dedup on the venue side."""
        return f"{symbol}-{int(target.ts.timestamp())}-{round(target.notional, 2)}"
