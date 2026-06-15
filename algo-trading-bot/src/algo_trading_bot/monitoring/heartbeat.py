"""Heartbeat / deadman switch (§2.7, §5 operational risk).

The engine emits a heartbeat each tick. If the heartbeat stops (process hung, feed
dead, clock stalled) past a timeout, the deadman trips the kill switch so a wedged
bot does not sit on open risk it can no longer manage.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from ..risk.kill_switch import KillSwitch


class Deadman:
    def __init__(self, kill: KillSwitch, timeout: timedelta) -> None:
        self.kill = kill
        self.timeout = timeout
        self._last: datetime | None = None

    def beat(self, now: datetime) -> None:
        self._last = now

    def check(self, now: datetime) -> None:
        """Trip the kill switch if no heartbeat within the timeout."""
        if self._last is not None and now - self._last > self.timeout:
            self.kill.trip(f"deadman: no heartbeat since {self._last.isoformat()}")
