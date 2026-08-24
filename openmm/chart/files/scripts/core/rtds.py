"""Polymarket RTDS — the Chainlink feed these markets actually settle on.

`crypto_prices_chainlink` carries the exact int192 (`full_accuracy_value`) that
resolution uses, at 1Hz. `crypto_prices_twap_thirty` carries the 30s TWAP that
becomes the settlement reference on 2026-08-07.

Two facts measured on the live feeds (8 symbols, ~230 ticks each, 2026-08-06):

  * the TWAP tick stamped at t is the mean of the point ticks over
    **[t-32, t-3]** — trailing, and excluding the last 3 seconds — to a median
    error of 0.0000 bps. The naive [t-29, t] window fits only to 0.04-0.28 bps.
  * relay latency payload->receive is p50 ~1.6s, so at wall-clock T we hold
    ticks up to roughly T-1.6s.

⚠ Subscribe WITHOUT a `filters` field. Passing filters silently suppresses the
stream — the topic connects and then never delivers anything.
"""
from __future__ import annotations

import asyncio
import json
import time

import websockets

from config import log

RTDS_URL = "wss://ws-live-data.polymarket.com"
KEEP_SECS = 900


class RTDSState:
    def __init__(self) -> None:
        self.point: dict[str, dict[int, float]] = {}
        self.twap: dict[str, dict[int, float]] = {}
        self.last_msg_at: float = 0.0
        self.lat_ewma: float = 0.0
        self.updates: int = 0
        self.session: int = 0

    # ── ingest ──────────────────────────────────────────────────────────────
    def _put(self, book: dict, sym: str, ts: int, v: float) -> None:
        d = book.setdefault(sym, {})
        d[ts] = v
        if len(d) > KEEP_SECS + 300:
            cut = ts - KEEP_SECS
            for k in [k for k in d if k < cut]:
                d.pop(k, None)

    def ingest(self, msg: dict, now: float) -> None:
        topic = msg.get("topic") or ""
        pl = msg.get("payload")
        if not isinstance(pl, dict):
            return
        sym_outer = pl.get("symbol")
        items = pl.get("data")
        if not isinstance(items, list):
            items = [pl]
        is_twap = "twap" in topic
        for it in items:
            if not isinstance(it, dict):
                continue
            sym = it.get("symbol") or sym_outer
            ts = it.get("timestamp") or it.get("ts")
            v = it.get("full_accuracy_value")
            if v is None:
                v = it.get("value")
            if sym is None or ts is None or v is None:
                continue
            try:
                v = float(v)
                ts = float(ts)
            except (TypeError, ValueError):
                continue
            if ts > 1e12:
                ts /= 1000.0
            # Every tick carries BOTH full_accuracy_value (the raw int192) and
            # value (the same number scaled down). Leads are ratios so either
            # works alone, but silently MIXING the two would be catastrophic —
            # normalise to the decimal scale so the series is always one unit.
            if v > 1e12:
                v /= 1e18
            self._put(self.twap if is_twap else self.point, sym, int(round(ts)), v)
            if not is_twap:
                lat = now - ts
                if 0 <= lat < 30:
                    self.lat_ewma = (0.98 * self.lat_ewma + 0.02 * lat
                                     if self.lat_ewma else lat)
                self.updates += 1
        self.last_msg_at = now

    # ── read ────────────────────────────────────────────────────────────────
    def age(self) -> float:
        return time.time() - self.last_msg_at if self.last_msg_at else 1e9

    def latest(self, sym: str) -> tuple[int, float] | None:
        d = self.point.get(sym)
        if not d:
            return None
        k = max(d)
        return k, d[k]

    def point_at(self, sym: str, ts: int, back: int = 5):
        """Value stamped at ts, or the most recent tick within `back` seconds."""
        d = self.point.get(sym)
        if not d:
            return None
        for k in range(int(ts), int(ts) - back - 1, -1):
            if k in d:
                return d[k]
        return None

    def twap_at(self, sym: str, ts: int):
        """TWAP-feed tick stamped exactly at ts (no fallback — the tick IS the
        settlement reference for the bar starting/ending at ts; a neighbouring
        tick is a different reference)."""
        return self.twap.get(sym, {}).get(int(ts))

    def window_mean(self, sym: str, lo: int, hi: int):
        """Mean of the point ticks over [lo, hi] inclusive.

        Seconds not yet published are filled forward from the last value at or
        before them — the same estimator the live bot must use before the bell.
        Returns (mean, observed, total) or None when nothing is available.
        """
        d = self.point.get(sym)
        if not d:
            return None
        total = hi - lo + 1
        vals = []
        obs = 0
        last = None
        for k in range(lo - 60, hi + 1):
            if k in d:
                last = d[k]
                if k >= lo:
                    obs += 1
            if k >= lo:
                if last is None:
                    return None
                vals.append(last)
        if not vals:
            return None
        return sum(vals) / len(vals), obs, total


rtds_state = RTDSState()


async def run_rtds(topics=("crypto_prices_chainlink", "crypto_prices_twap_thirty")):
    """Keep the RTDS subscription alive forever, reconnecting on any failure."""
    backoff = 1.0
    while True:
        try:
            async with websockets.connect(RTDS_URL, ping_interval=None,
                                          open_timeout=15,
                                          max_size=16 * 1024 * 1024) as ws:
                # NOTE: no "filters" key — it silently kills the stream.
                await ws.send(json.dumps({"action": "subscribe", "subscriptions": [
                    {"topic": t, "type": "update"} for t in topics]}))
                rtds_state.session += 1
                rtds_state.last_msg_at = time.time()
                backoff = 1.0
                log.info("rtds: subscribed %s", ",".join(topics))
                last_ping = time.time()
                while True:
                    try:
                        m = await asyncio.wait_for(ws.recv(), timeout=3.0)
                    except asyncio.TimeoutError:
                        m = None
                    now = time.time()
                    if now - last_ping > 5.0:
                        await ws.send("PING")
                        last_ping = now
                    if not m or m in ("PONG", "PING"):
                        if rtds_state.age() > 60:
                            raise RuntimeError("rtds stalled")
                        continue
                    try:
                        d = json.loads(m)
                    except Exception:
                        continue
                    for x in (d if isinstance(d, list) else [d]):
                        if isinstance(x, dict):
                            rtds_state.ingest(x, now)
        except Exception as exc:
            log.warning("rtds: %s (reconnect in %.0fs)", exc, backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)
