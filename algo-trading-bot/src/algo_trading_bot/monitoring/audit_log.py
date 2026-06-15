"""Structured logging of every decision and order (§2.7, NFR6, NFR7).

Every forecast, combined target, risk decision, and order is logged as a structured
record. This is not debug logging — it is the audit trail that makes signal
arbitration deterministic and *replayable from logged forecasts* (NFR7). The schema
is stable so logs can be re-fed through the engine to reproduce decisions.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any


class AuditLog:
    def __init__(self, sink: str | None = None) -> None:
        self.sink = sink  # file path / stream; JSON-lines

    def decision(self, kind: str, ts: datetime, payload: dict[str, Any]) -> None:
        """Record a decision event (forecast, target, risk action, order, fill)."""
        raise NotImplementedError("emit one JSON line: {ts, kind, **payload}")

    def replay(self):
        """Yield logged decision events in order (for NFR7 deterministic replay)."""
        raise NotImplementedError
