"""Kill switch — manual + automatic (§2.5).

The last line of defense. When tripped, the system cancels all working orders,
flattens all positions, and refuses new orders until manually re-armed. Automatic
triggers: drawdown-halt, drift auto-disable (§2.7), heartbeat/deadman timeout,
repeated venue rejects/disconnects.
"""

from __future__ import annotations


class KillSwitch:
    def __init__(self) -> None:
        self.tripped: bool = False
        self.reason: str = ""

    def trip(self, reason: str) -> None:
        self.tripped = True
        self.reason = reason

    def rearm(self) -> None:
        """Manual only — operator acknowledges and resets."""
        self.tripped = False
        self.reason = ""

    def allows_trading(self) -> bool:
        return not self.tripped
