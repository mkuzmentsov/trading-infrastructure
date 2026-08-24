"""userws.py — authenticated Polymarket USER-channel feed (real-time OUR fills).

Streams `order` events (size_matched updates for our resting orders) and
`trade` events for the wallet. Fill truth arrives the moment it happens —
no REST polling, immune to the culled-order size_matched fabrication
(2026-07-25 phantom-fill incident). Keyed by ORDER ID, so one wallet shared
by many bots stays unambiguous: each strategy only looks up its own orders.

Usage (wired by TakerRunner when live):
    feed = UserFeed(creds)          # creds = {"apiKey","secret","passphrase"}
    asyncio.create_task(feed.run())
    ...
    feed.matched(order_id)          # -> shares matched so far (0.0 if none seen)
    feed.healthy()                  # -> True if connected & fresh
"""
from __future__ import annotations

import asyncio
import json
import logging
import time

log = logging.getLogger("userws")

WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/user"
NOISE = {"book", "price_change", "tick_size_change", "last_trade_price"}


class UserFeed:
    def __init__(self, creds: dict) -> None:
        self._auth = {"apiKey": creds["apiKey"], "secret": creds["secret"],
                      "passphrase": creds["passphrase"]}
        self._matched: dict[str, float] = {}     # order_id -> shares matched
        self._last_msg = 0.0
        self._connected = False

    def matched(self, order_id: str) -> float:
        return self._matched.get(order_id, 0.0)

    def healthy(self, max_age: float = 60.0) -> bool:
        # PONGs refresh _last_msg, so a quiet-but-alive feed stays healthy
        return self._connected and (time.time() - self._last_msg) < max_age

    def _on_msg(self, it: dict) -> None:
        et = it.get("event_type") or it.get("type") or ""
        if et in NOISE:
            return
        if et == "order":
            oid = it.get("id")
            sm = it.get("size_matched")
            if oid and sm is not None:
                try:
                    v = float(sm)
                except (TypeError, ValueError):
                    return
                if v > self._matched.get(oid, 0.0):
                    self._matched[oid] = v
                    log.info("user_ws fill: order %s matched=%.4f px=%s",
                             oid[:16], v, it.get("price"))
        # cap memory: drop oldest entries past 2k orders
        if len(self._matched) > 2000:
            for k in list(self._matched)[:500]:
                self._matched.pop(k, None)

    async def run(self) -> None:
        import websockets
        while True:
            try:
                async with websockets.connect(WS_URL, ping_interval=None,
                                              close_timeout=3) as ws:
                    await ws.send(json.dumps(
                        {"auth": self._auth, "markets": [], "type": "user"}))
                    self._connected = True
                    self._last_msg = time.time()
                    log.info("user_ws connected")

                    async def pinger():
                        while True:
                            await asyncio.sleep(10)
                            await ws.send("PING")

                    pt = asyncio.create_task(pinger())
                    try:
                        async for msg in ws:
                            self._last_msg = time.time()
                            if msg == "PONG":
                                continue
                            try:
                                data = json.loads(msg)
                            except Exception:
                                continue
                            for it in (data if isinstance(data, list) else [data]):
                                if isinstance(it, dict):
                                    self._on_msg(it)
                    finally:
                        pt.cancel()
            except Exception as exc:
                log.warning("user_ws reconnect after: %s", exc)
            self._connected = False
            await asyncio.sleep(3.0)
