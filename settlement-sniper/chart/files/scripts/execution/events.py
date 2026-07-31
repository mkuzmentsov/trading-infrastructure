"""Rotating JSONL event log — the shared event writer for all bots.

Same policy as the maker engine's writer (main.py): append one JSON object
per line; on the first write of a new UTC day, gzip the previous day's file
to `<path>.<YYYY-MM-DD>.gz` and start fresh; prune archives older than
EVENT_LOG_KEEP_DAYS (default 30). On a PVC this bounds the volume to a few
hundred MB while keeping a month of exact history for measurement snapshots.
"""
from __future__ import annotations

import glob
import gzip
import json
import os
import time

from config import log

KEEP_DAYS = int(os.getenv("EVENT_LOG_KEEP_DAYS", "30"))


class EventLog:
    def __init__(self, path: str, mirror_to_log: bool = True) -> None:
        self.path = path
        self.mirror = mirror_to_log
        self._day = time.strftime("%Y-%m-%d", time.gmtime())

    def _rotate_if_new_day(self) -> None:
        today = time.strftime("%Y-%m-%d", time.gmtime())
        if today == self._day:
            return
        prev, self._day = self._day, today
        try:
            if os.path.exists(self.path) and os.path.getsize(self.path) > 0:
                rotated = f"{self.path}.{prev}.gz"
                with open(self.path, "rb") as src, gzip.open(rotated, "wb") as dst:
                    dst.write(src.read())
                os.truncate(self.path, 0)
            cutoff = time.time() - KEEP_DAYS * 86400
            for f in glob.glob(f"{self.path}.*.gz"):
                if os.path.getmtime(f) < cutoff:
                    os.remove(f)
        except Exception as exc:
            log.warning("event log rotation failed: %s", exc)

    def write(self, ev: str, **kw) -> None:
        rec = {"ev": ev, "t": round(time.time(), 2), **kw}
        if self.mirror:
            log.info("%s  %s", ev, " ".join(f"{k}={v}" for k, v in kw.items()))
        if not self.path:
            return
        try:
            self._rotate_if_new_day()
            with open(self.path, "a") as f:
                f.write(json.dumps(rec) + "\n")
        except Exception:
            pass
