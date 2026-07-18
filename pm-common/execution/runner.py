"""TakerRunner — generic event-driven bot harness for the UpDown markets.

One runner for every taker bot we build; only the market changes
(COIN + BAR_SECONDS env). It owns all plumbing:

  feeds      Binance aggTrade WS (signal) + CLOB market WS (book), both
             updating shared state and firing the tick bus on arrival
  markets    deterministic-slug pre-discovery at T−30s, instant apply at the
             bar roll (pm_ws cache; zero gamma calls on the boundary)
  execution  FastExec: warm session + per-bar prewarm + presigned orders
  evaluation strategy.on_tick(ctx) runs the moment data arrives — ctx is
             built purely from in-memory state, no I/O on the hot path

Strategy protocol (duck-typed):
  presign_requests(ctx)  -> [(key, token_id, price, size)]  at each new bar
  on_tick(ctx)           -> None                            every wake-up
  settle_loop()          -> coroutine                       own cadence
"""
from __future__ import annotations

import asyncio
import json
import time
import urllib.request
from dataclasses import dataclass, field

from config import BAR_SECONDS, COIN, log
from core.binance_ws import binance_state, run_binance_ws
from core.pm_ws import (
    apply_prefetched_market_now,
    enable_external_market_apply,
    pm_state,
    prefetch_next_market,
    run_pm_ws,
)
from execution.fastclient import FastExec
from execution.tickbus import tick_bus

PREFETCH_LEAD_SECS = 30.0
IDLE_WAKE_SECS = 0.5          # eval cadence when feeds are quiet
SIGMA_CACHE_SECS = 20.0


@dataclass
class TakerCtx:
    now: float
    ws: int                    # window (bar) start ts
    t_left: float
    spot: float
    spot_age: float
    bar_open: float | None
    sigma_ps: float | None     # per-second stdev of log returns
    ret_30s: float | None      # log-return over the last ~30s (None: sparse)
    up_token: str = ""
    down_token: str = ""
    condition_id: str = ""
    up_ask: float = 1.0
    up_ask_size: float = 0.0
    down_ask: float = 1.0
    down_ask_size: float = 0.0
    up_bid: float = 0.0            # best BID (what we could SELL into) — TP path
    down_bid: float = 0.0
    up_depth: dict = field(default_factory=dict)     # {ask_price: size}, <=0.25
    down_depth: dict = field(default_factory=dict)
    book_ready: bool = False
    # timing provenance (for EXEC_* events)
    signal_ts: float = 0.0     # exchange event time of the wake-up signal
    arrival_ts: float = 0.0    # local arrival of that signal
    wake_source: str = ""


class TakerRunner:
    def __init__(self, strategy, live: bool, event_logger) -> None:
        self.strategy = strategy
        self.exec = FastExec(live=live, event_logger=event_logger)
        self._log_event = event_logger
        self._sigma_cache: tuple[float, float | None] = (0.0, None)
        self._presigned_bar: int = 0
        self._stats = {"wakes": 0, "evals": 0, "last_hb": 0.0}

    # ── data helpers (all in-memory) ─────────────────────────────────────────
    def _sigma_ps(self, now: float) -> float | None:
        t, v = self._sigma_cache
        if now - t < SIGMA_CACHE_SECS:
            return v
        rows = binance_state.completed_bars(limit=40)
        v = None
        if len(rows) >= 10:
            import math
            rets = []
            for i in range(1, len(rows)):
                p0, p1 = rows[i - 1]["close"], rows[i]["close"]
                if p0 > 0 and p1 > 0:
                    rets.append(math.log(p1 / p0))
            if len(rets) >= 8:
                m = sum(rets) / len(rets)
                var = sum((r - m) ** 2 for r in rets) / (len(rets) - 1)
                v = math.sqrt(var) / math.sqrt(60.0)
        self._sigma_cache = (now, v)
        return v

    def build_ctx(self, now: float) -> TakerCtx | None:
        ws = pm_state.market_start_ts
        end = pm_state.market_end_ts
        if ws <= 0 or end <= 0 or now >= end:
            return None
        if not binance_state.ready:
            return None
        return TakerCtx(
            now=now,
            ws=ws,
            t_left=end - now,
            spot=binance_state.current_price,
            spot_age=binance_state.age(),
            bar_open=binance_state.bar_open_at(ws),
            sigma_ps=self._sigma_ps(now),
            ret_30s=binance_state.ret_windowed(30.0),
            up_token=pm_state.token_id_up,
            down_token=pm_state.token_id_down,
            condition_id=pm_state.condition_id,
            up_ask=pm_state.up_ask,
            up_ask_size=pm_state.up_ask_size,
            down_ask=pm_state.down_ask,
            down_ask_size=pm_state.down_ask_size,
            up_bid=pm_state.up_bid,
            down_bid=pm_state.down_bid,
            up_depth=pm_state.ask_depth.get(pm_state.token_id_up, {}),
            down_depth=pm_state.ask_depth.get(pm_state.token_id_down, {}),
            book_ready=pm_state.ready,
            signal_ts=tick_bus.last_signal_ts,
            arrival_ts=tick_bus.last_arrival_ts,
            wake_source=tick_bus.last_source,
        )

    # ── startup seed (one REST call, off the hot path) ───────────────────────
    def _seed_history(self) -> None:
        sym = f"{COIN.upper()}USDT"
        # futures feed (fstream bookTicker mid) → seed from futures klines so
        # bar_open/sigma share the feed's basis; spot seed would shift lead by
        # the perp premium (a few bps — enough to matter vs the 4bps floor)
        from config import BINANCE_WS_URL
        if "fstream" in BINANCE_WS_URL:
            paths = [("https://fapi.binance.com", "/fapi/v1/klines")]
        else:
            paths = [("https://api.binance.com", "/api/v3/klines"),
                     ("https://data-api.binance.vision", "/api/v3/klines")]
        for base, kpath in paths:
            try:
                req = urllib.request.Request(
                    f"{base}{kpath}?symbol={sym}&interval=1m&limit=60",
                    headers={"User-Agent": "Mozilla/5.0"})
                raw = json.loads(urllib.request.urlopen(req, timeout=10).read())
                binance_state.seed_minute_bars(
                    [(int(k[0]) // 1000, float(k[1]), float(k[2]), float(k[3]), float(k[4]))
                     for k in raw])
                log.info("Seeded %d 1m bars from %s", len(raw), base)
                return
            except Exception as exc:
                log.warning("kline seed via %s failed: %s", base, exc)

    # ── market roll: prefetch → apply → prewarm+presign ─────────────────────
    async def _roll_watcher(self) -> None:
        prefetched_for = 0
        while True:
            try:
                end_ts = pm_state.market_end_ts
                now = time.time()
                if end_ts <= 0:
                    await asyncio.sleep(1.0)
                    continue
                if now < end_ts - PREFETCH_LEAD_SECS:
                    await asyncio.sleep(min(1.0, end_ts - PREFETCH_LEAD_SECS - now))
                    continue
                if prefetched_for != end_ts and now < end_ts:
                    if await asyncio.to_thread(prefetch_next_market):
                        prefetched_for = end_ts
                    else:
                        await asyncio.sleep(3.0)
                    continue
                if now < end_ts:
                    await asyncio.sleep(max(0.01, min(0.05, end_ts - now)))
                    continue
                if apply_prefetched_market_now():
                    log.info("Bar roll: next market applied instantly")
                else:
                    await asyncio.sleep(0.5)   # run_pm_ws rotation fallback
            except Exception as exc:
                log.exception("roll watcher: %s", exc)
                await asyncio.sleep(1.0)

    async def _prewarm_new_bar(self) -> None:
        """Runs when a new bar's market shows up: warm caches + presign.
        Retries until the presigns are actually placed (feeds may not be
        ready in the first 200ms slices of a bar)."""
        warmed_cond = ""
        signed_cond = ""
        while True:
            await asyncio.sleep(0.2)
            try:
                cond = pm_state.condition_id
                if not cond or cond == signed_cond:
                    continue
                if cond != warmed_cond:
                    warmed_cond = cond
                    self.exec.drop_presigned()
                    tokens = [t for t in (pm_state.token_id_up, pm_state.token_id_down) if t]
                    await self.exec.prewarm(tokens)
                ctx = self.build_ctx(time.time())
                if ctx is None:
                    continue                      # feeds not ready yet — retry
                for key, token, price, size in self.strategy.presign_requests(ctx):
                    await self.exec.presign_buy(key, token, price, size)
                signed_cond = cond
                self._presigned_bar = ctx.ws
            except Exception as exc:
                log.exception("prewarm: %s", exc)

    # ── the eval loop (event-driven) ─────────────────────────────────────────
    async def _eval_loop(self) -> None:
        while True:
            try:
                woke = await tick_bus.wait(IDLE_WAKE_SECS)
                now = time.time()
                self._stats["wakes"] += 1
                ctx = self.build_ctx(now)
                if ctx is not None:
                    self._stats["evals"] += 1
                    await self.strategy.on_tick(ctx)
                if now - self._stats["last_hb"] >= 60.0:
                    self._stats["last_hb"] = now
                    self._log_event(
                        "EXEC_HB", wakes=self._stats["wakes"], evals=self._stats["evals"],
                        binance_delay_ewma_ms=round(binance_state.delay_ewma_ms, 1),
                        bus_signals=tick_bus.signals, book_ready=pm_state.ready)
                    self._stats["wakes"] = self._stats["evals"] = 0
            except Exception as exc:
                log.exception("eval loop: %s", exc)
                await asyncio.sleep(0.5)

    # ── entry ────────────────────────────────────────────────────────────────
    async def run(self) -> None:
        log.info("TakerRunner start  coin=%s bar=%ds live=%s",
                 COIN, BAR_SECONDS, self.exec.live)
        self._seed_history()
        enable_external_market_apply()
        self.exec.start()
        self.strategy.bind(self)
        tasks = [
            asyncio.create_task(run_binance_ws(), name="binance_ws"),
            asyncio.create_task(run_pm_ws(), name="pm_ws"),
            asyncio.create_task(self._roll_watcher(), name="roll"),
            asyncio.create_task(self._prewarm_new_bar(), name="prewarm"),
            asyncio.create_task(self.exec.keepalive_loop(), name="keepalive"),
            asyncio.create_task(self._eval_loop(), name="eval"),
            asyncio.create_task(self.strategy.settle_loop(), name="settle"),
        ]
        await asyncio.gather(*tasks)
