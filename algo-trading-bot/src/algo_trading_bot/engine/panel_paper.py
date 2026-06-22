"""Panel paper-trading book — daily-rebalanced, multi-asset, simulated fills.

The sleeved multi-window TSM is cross-sectional (cluster sizing needs the whole universe's
covariance each bar), so it doesn't fit the single-symbol event engine. This is its paper
analogue: each step it rebalances a simulated book toward the target weights produced by the
SAME `sleeved_target_weights` the backtest uses (NFR1: one weight path, backtest == paper).

State is JSON-persistable so a daily cron can step it forward and accumulate genuine forward
evidence. Accounting: fills at the bar close, taker fee on traded notional; shorts credit cash;
equity = cash + Σ qty·price. Marked-to-close, no leverage financing (the risk layer already caps
gross at `leverage` inside the weights).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class PanelPaperBook:
    cash: float
    positions: dict[str, float] = field(default_factory=dict)   # symbol -> signed qty
    last_ts: str | None = None
    fee_bps: float = 4.5
    history: list[dict] = field(default_factory=list)           # per-step equity marks

    @classmethod
    def new(cls, starting_cash: float, fee_bps: float) -> "PanelPaperBook":
        return cls(cash=float(starting_cash), fee_bps=fee_bps)

    def equity(self, prices: dict[str, float]) -> float:
        return self.cash + sum(q * prices[s] for s, q in self.positions.items() if s in prices)

    def rebalance_to(self, target_weights: dict[str, float], prices: dict[str, float], ts: str) -> dict:
        """Rebalance to ``target_weights`` (signed fraction of equity per symbol) at ``prices``.
        Mutates state; returns a step record (equity, gross, turnover, fees, n_trades)."""
        eq = self.equity(prices)
        fee_rate = self.fee_bps / 1e4
        traded_notional = 0.0
        fees = 0.0
        n_trades = 0
        for sym, price in prices.items():
            if price <= 0:
                continue
            desired_qty = target_weights.get(sym, 0.0) * eq / price
            delta = desired_qty - self.positions.get(sym, 0.0)
            if abs(delta * price) < 1e-9:
                continue
            notional = abs(delta * price)
            fee = notional * fee_rate
            self.cash -= delta * price + fee          # buy: cash down; sell/short: cash up; fee always down
            self.positions[sym] = desired_qty
            traded_notional += notional
            fees += fee
            n_trades += 1
        # drop dust
        self.positions = {s: q for s, q in self.positions.items() if abs(q) > 1e-12}
        self.last_ts = ts
        new_eq = self.equity(prices)
        gross = sum(abs(q * prices[s]) for s, q in self.positions.items() if s in prices)
        rec = {"ts": ts, "equity": round(new_eq, 2), "gross_lev": round(gross / new_eq, 3) if new_eq else 0.0,
               "turnover": round(traded_notional / eq, 4) if eq else 0.0,
               "fees": round(fees, 4), "n_trades": n_trades}
        self.history.append(rec)
        return rec

    # --- persistence ---
    def to_dict(self) -> dict:
        return {"cash": self.cash, "positions": self.positions, "last_ts": self.last_ts,
                "fee_bps": self.fee_bps, "history": self.history}

    @classmethod
    def from_dict(cls, d: dict) -> "PanelPaperBook":
        return cls(cash=d["cash"], positions=dict(d.get("positions", {})), last_ts=d.get("last_ts"),
                   fee_bps=d.get("fee_bps", 4.5), history=list(d.get("history", [])))

    def save(self, path: str) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2))

    @classmethod
    def load(cls, path: str) -> "PanelPaperBook":
        return cls.from_dict(json.loads(Path(path).read_text()))
