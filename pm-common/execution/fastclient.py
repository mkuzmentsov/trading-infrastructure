"""FastExec — the shared low-latency CLOB order path for all bots.

Wraps engine.clob with the four measured wins (latency/LATENCY_BASELINE.md):
  1. session keep-alive: py_clob_client_v2 already multiplexes one
     httpx.Client(http2); we ping /time every CLOB_KEEPALIVE_SECS so the edge
     never drops the connection (cold reconnect ≈ +180ms on the order path).
  2. per-market prewarm: the FIRST create_order on a token pays ~300ms of
     tick-size + neg-risk REST lookups; we pay it at bar start instead.
  3. presign: EIP-712 signing (~10ms warm) + order building happen at bar
     start; the trigger path is a single POST.
  4. everything CLOB-bound runs in a thread executor so the WS feeds and the
     eval loop never block.

Paper mode: no client, no signing; fire() resolves instantly. The timing
events (EXEC_*) are emitted in both modes so paper/live compare directly.
"""
from __future__ import annotations

import asyncio
import os
import time
from typing import Callable, Optional

from config import CLOB_KEEPALIVE_SECS, log


class FastExec:
    def __init__(self, live: bool, event_logger: Optional[Callable] = None) -> None:
        self.live = live
        self._clob = None
        self._presigned: dict[str, object] = {}    # key -> signed order
        self._prewarmed: set[str] = set()          # token_ids with warm caches
        self._log_event = event_logger or (lambda ev, **kw: None)
        # fak = immediate-or-kill; gtc = marketable GTC (remainder RESTS as
        # fee-free maker until resolution — never cancelled by design)
        self.order_type = os.getenv("FAV_ORDER_TYPE", "fak").lower()

    # ── lifecycle ────────────────────────────────────────────────────────────
    def start(self) -> None:
        if not self.live:
            log.info("FastExec PAPER: no CLOB client, instant fills")
            return
        from engine.clob import build_clob_client, ensure_approvals
        self._clob = build_clob_client()
        ensure_approvals(self._clob)
        log.info("FastExec LIVE: CLOB client ready")

    @property
    def clob(self):
        return self._clob

    async def keepalive_loop(self) -> None:
        """Ping the CLOB over the shared session so it stays warm."""
        if not self.live:
            return
        loop = asyncio.get_running_loop()
        while True:
            await asyncio.sleep(CLOB_KEEPALIVE_SECS)
            t0 = time.time()
            try:
                await loop.run_in_executor(None, self._clob.get_server_time)
                ms = (time.time() - t0) * 1000.0
                if ms > 200:
                    log.info("CLOB keepalive slow: %.0fms (session went cold?)", ms)
            except Exception as exc:
                log.warning("CLOB keepalive failed: %s", exc)

    # ── per-market prewarm + presign ─────────────────────────────────────────
    async def prewarm(self, token_ids: list[str]) -> float:
        """Warm tick-size/neg-risk caches for this bar's tokens. Returns ms."""
        if not self.live or not token_ids:
            return 0.0
        loop = asyncio.get_running_loop()
        t0 = time.time()

        def _warm() -> None:
            for tok in token_ids:
                if tok in self._prewarmed:
                    continue
                self._clob.get_tick_size(tok)
                self._clob.get_neg_risk(tok)
                self._prewarmed.add(tok)
                if len(self._prewarmed) > 64:
                    self._prewarmed.clear()      # old bars' tokens, let them go

        try:
            await loop.run_in_executor(None, _warm)
        except Exception as exc:
            log.warning("prewarm failed: %s", exc)
        ms = (time.time() - t0) * 1000.0
        self._log_event("EXEC_PREWARM", tokens=len(token_ids), ms=round(ms, 1))
        return ms

    async def presign_buy(self, key: str, token_id: str, price: float, size: float) -> bool:
        """Build+sign a FAK buy at bar start; fire_presigned(key) later just POSTs."""
        if not self.live:
            self._presigned[key] = ("paper", token_id, price, size)
            return True
        from engine.clob import sign_buy_order
        loop = asyncio.get_running_loop()
        t0 = time.time()
        try:
            signed = await loop.run_in_executor(
                None, lambda: sign_buy_order(self._clob, token_id, size, price))
        except Exception as exc:
            log.warning("presign %s failed: %s", key, exc)
            return False
        self._presigned[key] = signed
        self._log_event("EXEC_PRESIGN", key=key, price=price, size=size,
                        ms=round((time.time() - t0) * 1000.0, 1))
        return True

    def drop_presigned(self) -> None:
        self._presigned.clear()

    def has_presigned(self, key: str) -> bool:
        return key in self._presigned

    # ── the hot path ─────────────────────────────────────────────────────────
    async def fire_presigned(self, key: str) -> tuple[Optional[str], bool, float, Optional[float], Optional[float]]:
        """POST the presigned order.
        Returns (order_id, matched, post_ms, avg_fill_px, filled_shares)."""
        signed = self._presigned.pop(key, None)
        if signed is None:
            return None, False, 0.0, None, None
        if not self.live:
            return f"paper-{key}", True, 0.0, None, None
        from engine.clob import post_signed_buy
        loop = asyncio.get_running_loop()
        t0 = time.time()
        order_id, matched, avg_px, filled = await loop.run_in_executor(
            None, lambda: post_signed_buy(self._clob, signed, self.order_type))
        return order_id, matched, (time.time() - t0) * 1000.0, avg_px, filled

    async def fire_direct(self, token_id: str, price: float, size: float,
                          ) -> tuple[Optional[str], bool, float, float, Optional[float], Optional[float]]:
        """Sign+POST now (fallback when no presigned order matches).
        Returns (order_id, matched, sign_ms, post_ms, avg_fill_px, filled_shares)."""
        if not self.live:
            return f"paper-direct-{int(time.time())}", True, 0.0, 0.0, None, None
        from engine.clob import post_signed_buy, sign_buy_order
        loop = asyncio.get_running_loop()
        t0 = time.time()
        signed = await loop.run_in_executor(
            None, lambda: sign_buy_order(self._clob, token_id, size, price))
        t1 = time.time()
        order_id, matched, avg_px, filled = await loop.run_in_executor(
            None, lambda: post_signed_buy(self._clob, signed, self.order_type))
        return order_id, matched, (t1 - t0) * 1000.0, (time.time() - t1) * 1000.0, avg_px, filled

    async def poll_filled(self, order_id: str) -> Optional[float]:
        """Cumulative matched shares for a resting order (GTC snipe readback)."""
        if not self.live or not order_id:
            return None
        from engine.clob import get_order_filled
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: get_order_filled(self._clob, order_id))

    async def cancel(self, order_id: str) -> bool:
        """Cancel a resting order (unfilled snipe bid at window end)."""
        if not self.live or not order_id:
            return False
        from engine.clob import cancel_order
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: cancel_order(self._clob, order_id))
