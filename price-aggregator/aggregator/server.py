"""WS broadcast server + HTTP health.

Clients connect over WS and receive normalized ticks. On connect they get a
snapshot of every symbol; thereafter a throttled tick per symbol (BROADCAST_MS).
A client may send {"op":"subscribe","symbols":[...]} to filter; default = all.

`GET /healthz` (plain HTTP, handled via process_request) returns 200 when at
least one venue is fresh, else 503 — used by k8s liveness/readiness probes.
"""
from __future__ import annotations

import asyncio
import json
import logging
from http import HTTPStatus
from typing import Callable

import websockets

log = logging.getLogger("agg.server")


class Server:
    def __init__(self, host: str, port: int, symbols: list[str],
                 get_snapshot: Callable[[str], dict | None],
                 broadcast_ms: int = 100) -> None:
        self.host, self.port = host, port
        self.symbols = symbols
        self.get_snapshot = get_snapshot
        self.broadcast_ms = broadcast_ms
        self.clients: dict = {}  # ws -> set(symbols)

    # ---- health (plain HTTP) ----
    async def _process_request(self, path, request_headers):
        if path.rstrip("/") in ("/healthz", "/health", "/ready"):
            fresh = any(self.get_snapshot(s) for s in self.symbols)
            status = HTTPStatus.OK if fresh else HTTPStatus.SERVICE_UNAVAILABLE
            body = (b"ok\n" if fresh else b"no fresh feed\n")
            return status, [("Content-Type", "text/plain")], body
        return None  # proceed with WS upgrade

    # ---- per-client ----
    async def _handler(self, ws):
        self.clients[ws] = set(self.symbols)
        peer = getattr(ws, "remote_address", None)
        log.info("client connected %s (%d total)", peer, len(self.clients))
        try:
            for s in self.symbols:  # initial snapshots
                snap = self.get_snapshot(s)
                if snap:
                    await ws.send(json.dumps(snap))
            async for raw in ws:  # client control messages
                try:
                    msg = json.loads(raw)
                except Exception:
                    continue
                if msg.get("op") == "subscribe":
                    want = msg.get("symbols") or self.symbols
                    self.clients[ws] = {s for s in want if s in self.symbols}
        except websockets.ConnectionClosed:
            pass
        finally:
            self.clients.pop(ws, None)
            log.info("client disconnected %s (%d total)", peer, len(self.clients))

    # ---- broadcast loop ----
    async def _broadcaster(self):
        while True:
            await asyncio.sleep(self.broadcast_ms / 1000)
            if not self.clients:
                continue
            snaps = {s: self.get_snapshot(s) for s in self.symbols}
            dead = []
            for ws, subs in list(self.clients.items()):
                for s in subs:
                    snap = snaps.get(s)
                    if not snap:
                        continue
                    try:
                        await ws.send(json.dumps(snap))
                    except Exception:
                        dead.append(ws)
                        break
            for ws in dead:
                self.clients.pop(ws, None)

    async def serve(self):
        log.info("WS server on ws://%s:%d  symbols=%s  broadcast=%dms",
                 self.host, self.port, ",".join(self.symbols), self.broadcast_ms)
        async with websockets.serve(self._handler, self.host, self.port,
                                    process_request=self._process_request,
                                    ping_interval=20, ping_timeout=20):
            await self._broadcaster()
