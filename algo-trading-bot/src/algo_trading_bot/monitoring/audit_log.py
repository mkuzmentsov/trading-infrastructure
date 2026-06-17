"""Structured logging of every decision and order (§2.7, NFR6, NFR7).

Every forecast, combined target, risk decision, and order is logged as a structured
record. This is not debug logging — it is the audit trail that makes signal
arbitration deterministic and *replayable from logged forecasts* (NFR7). The schema
is stable so logs can be re-fed through the engine to reproduce decisions.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator


class AuditLog:
    """Append-only JSON-lines audit log. One line per decision/order/fill, with a
    stable schema so logs can be re-fed to reproduce decisions (NFR7)."""

    def __init__(self, sink: str | Path | None = None) -> None:
        self.sink = Path(sink) if sink else None
        if self.sink is not None:
            self.sink.parent.mkdir(parents=True, exist_ok=True)

    def decision(self, kind: str, ts: datetime, payload: dict[str, Any]) -> None:
        """Record a decision event (bar, forecast, target, risk action, order, fill)."""
        record = {"ts": ts.isoformat() if hasattr(ts, "isoformat") else ts, "kind": kind, **payload}
        line = json.dumps(record, default=str)
        if self.sink is None:
            print(line)
            return
        with self.sink.open("a") as fh:
            fh.write(line + "\n")

    def replay(self) -> Iterator[dict]:
        """Yield logged decision events in order (for NFR7 deterministic replay)."""
        if self.sink is None or not self.sink.exists():
            return
        with self.sink.open() as fh:
            for line in fh:
                line = line.strip()
                if line:
                    yield json.loads(line)
