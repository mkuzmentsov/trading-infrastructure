"""ws_recorder — full-state 100ms snapshot recorder for the UpDown markets.

Reuses the bots' OWN feed stack (core.binance_ws + core.pm_ws) so it records
EXACTLY the state a bot sees: both-side CLOB book (BBO + tail-zone ask ladders),
Binance spot/futures price, new trade prints, and the derived diffusion signals
(lead, z, fav_true, mom_z, sigma, t_left). One row per coin every SNAPSHOT_MS
while a bar is live.

Purpose: a universal replay dataset for ANY strat backtest (maker fills, taker
entries, exit paths) without re-running live paper — snapshot the state instead
of the WS firehose, so file size is cadence-bounded not message-bounded.

Output: NDJSON to RAW_LOG_DIR/<coin>-YYYYMMDD-HH.jsonl (UTC hour buckets),
gzip-rotated when the hour rolls, pruned after RETENTION_DAYS. A compact BAR row
(condition_id/tokens/question) is written once per bar; the 100ms SNAP rows stay
small (no token ids). Size at 100ms ≈ 0.5 GB/day/coin raw, ~50 MB/day/coin gz.

Env: COIN, SNAPSHOT_MS (100), RAW_LOG_DIR (/app/logs/raw), RETENTION_DAYS (7),
BAR_SECONDS (300). Shares BINANCE_WS_URL / POLYMARKET_* with the bots.
"""
from __future__ import annotations

import asyncio
import glob
import gzip
import json
import math
import os
import time
import urllib.request

from config import BAR_SECONDS, COIN, log
from core.binance_ws import binance_state, run_binance_ws
from core.pm_ws import (
    apply_prefetched_market_now,
    enable_external_market_apply,
    pm_state,
    prefetch_next_market,
    run_pm_ws,
)

SNAPSHOT_MS = max(20, int(float(os.getenv("SNAPSHOT_MS", "100"))))
SNAPSHOT_SECS = SNAPSHOT_MS / 1000.0
RAW_LOG_DIR = os.getenv("RAW_LOG_DIR", "/app/logs/raw")
RETENTION_DAYS = float(os.getenv("RETENTION_DAYS", "7"))
PREFETCH_LEAD_SECS = 30.0
LADDER_LEVELS = 15                 # tail-zone ask levels to keep per token
SIGMA_CACHE_SECS = 20.0


def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


# ── rotating gzip writer ──────────────────────────────────────────────────────
class RotatingWriter:
    """Append NDJSON to an hourly file; gzip the previous hour on roll; prune old."""

    def __init__(self, out_dir: str, coin: str) -> None:
        self.out_dir = out_dir
        self.coin = coin
        self._hour = ""
        self._fh = None
        os.makedirs(out_dir, exist_ok=True)

    def _path(self, hour: str) -> str:
        return os.path.join(self.out_dir, f"{self.coin}-{hour}.jsonl")

    async def write(self, row: dict) -> None:
        hour = time.strftime("%Y%m%d-%H", time.gmtime())
        if hour != self._hour:
            await self._roll(hour)
        line = json.dumps(row, separators=(",", ":"))
        self._fh.write(line + "\n")
        self._fh.flush()

    async def _roll(self, hour: str) -> None:
        old = self._hour
        if self._fh is not None:
            self._fh.close()
            self._fh = None
        self._hour = hour
        self._fh = open(self._path(hour), "a")
        if old:
            await asyncio.to_thread(self._gzip_and_prune, self._path(old))

    def _gzip_and_prune(self, old_path: str) -> None:
        try:
            if os.path.exists(old_path) and os.path.getsize(old_path) > 0:
                with open(old_path, "rb") as src, gzip.open(old_path + ".gz", "wb") as dst:
                    while True:
                        chunk = src.read(1 << 20)
                        if not chunk:
                            break
                        dst.write(chunk)
                os.remove(old_path)
        except Exception as exc:
            log.warning("gzip rotate %s: %s", old_path, exc)
        # prune anything older than the retention window
        cutoff = time.time() - RETENTION_DAYS * 86400
        for f in glob.glob(os.path.join(self.out_dir, f"{self.coin}-*.jsonl*")):
            try:
                if os.path.getmtime(f) < cutoff:
                    os.remove(f)
            except OSError:
                pass


# ── signals (same math as fav_taker / runner) ────────────────────────────────
_sigma_cache: list = [0.0, None]


def sigma_ps(now: float) -> float | None:
    t, v = _sigma_cache
    if now - t < SIGMA_CACHE_SECS:
        return v
    rows = binance_state.completed_bars(limit=40)
    v = None
    if len(rows) >= 10:
        rets = []
        for i in range(1, len(rows)):
            p0, p1 = rows[i - 1]["close"], rows[i]["close"]
            if p0 > 0 and p1 > 0:
                rets.append(math.log(p1 / p0))
        if len(rets) >= 8:
            m = sum(rets) / len(rets)
            var = sum((r - m) ** 2 for r in rets) / (len(rets) - 1)
            v = math.sqrt(var) / math.sqrt(60.0)
    _sigma_cache[0], _sigma_cache[1] = now, v
    return v


def _ladder(token_id: str) -> list:
    """Tail-zone ask ladder [[price, size], ...] for a token, cheapest first."""
    d = pm_state.ask_depth.get(token_id, {})
    return [[round(px, 4), round(sz, 1)] for px, sz in sorted(d.items())[:LADDER_LEVELS]]


def build_snap(now: float, trade_cursor: list) -> dict | None:
    """One full-state snapshot row, or None if a bar/feed isn't live yet."""
    ws = pm_state.market_start_ts
    end = pm_state.market_end_ts
    if ws <= 0 or end <= 0 or now >= end:
        return None
    if not (binance_state.ready and pm_state.ready):
        return None
    t_left = end - now
    spot = binance_state.current_price
    bar_open = binance_state.bar_open_at(ws)
    sig = sigma_ps(now)
    lead = z = ftrue = None
    fav_up = None
    if bar_open and spot > 0:
        lead = (spot - bar_open) / bar_open
        if sig and t_left > 0:
            z = lead / (sig * math.sqrt(t_left))
            tu = norm_cdf(z)
            fav_up = tu >= 0.5
            ftrue = tu if fav_up else 1 - tu
    ret30 = binance_state.ret_windowed(30.0)
    momz = ret30 / (sig * math.sqrt(30.0)) if (ret30 is not None and sig) else None

    # new trade prints since last row (cursor = last seq emitted)
    trades = []
    last_seq = trade_cursor[0]
    for tr in pm_state.recent_trades:
        if tr["seq"] <= last_seq:
            continue
        tok = "U" if tr["token_id"] == pm_state.token_id_up else (
            "D" if tr["token_id"] == pm_state.token_id_down else "?")
        trades.append([round(tr["ts"], 3), tok, tr["price"], round(tr["size"], 2), tr.get("side", "")])
        trade_cursor[0] = tr["seq"]

    return {
        "t": round(now, 3), "coin": COIN, "ws": ws, "tl": round(t_left, 2), "ev": "SNAP",
        "spot": spot, "spot_age": round(binance_state.age(), 3),
        "open": bar_open, "sig": None if sig is None else round(sig, 8),
        "lead_bps": None if lead is None else round(lead * 1e4, 2),
        "z": None if z is None else round(z, 4),
        "ftrue": None if ftrue is None else round(ftrue, 4),
        "fup": fav_up,
        "momz": None if momz is None else round(momz, 3),
        "ub": pm_state.up_bid, "ua": pm_state.up_ask,
        "ubs": round(pm_state.up_bid_size, 1), "uas": round(pm_state.up_ask_size, 1),
        "db": pm_state.down_bid, "da": pm_state.down_ask,
        "dbs": round(pm_state.down_bid_size, 1), "das": round(pm_state.down_ask_size, 1),
        "uL": _ladder(pm_state.token_id_up), "dL": _ladder(pm_state.token_id_down),
        "trd": trades or None,
    }


# ── market roll (compact copy of runner._roll_watcher) ────────────────────────
async def _roll_watcher() -> None:
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
                log.info("Bar roll: next market applied")
            else:
                await asyncio.sleep(0.5)
        except Exception as exc:
            log.exception("roll watcher: %s", exc)
            await asyncio.sleep(1.0)


def _seed_history() -> None:
    sym = f"{COIN.upper()}USDT"
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


async def _snapshot_loop(writer: RotatingWriter) -> None:
    trade_cursor = [0]          # last emitted trade seq
    cur_bar = 0
    rows = 0
    last_hb = 0.0
    while True:
        try:
            now = time.time()
            # BAR meta row once per bar (token ids / question) — keeps SNAP rows small
            ws = pm_state.market_start_ts
            if ws and ws != cur_bar and pm_state.ready and pm_state.condition_id:
                cur_bar = ws
                trade_cursor[0] = pm_state.trade_seq   # don't backfill old trades onto a new bar
                await writer.write({
                    "t": round(now, 3), "coin": COIN, "ws": ws, "ev": "BAR",
                    "cid": pm_state.condition_id, "q": pm_state.question,
                    "up": pm_state.token_id_up, "down": pm_state.token_id_down,
                    "end": pm_state.market_end_ts})
            row = build_snap(now, trade_cursor)
            if row is not None:
                await writer.write(row)
                rows += 1
            if now - last_hb >= 60.0:
                last_hb = now
                log.info("REC_HB rows=%d bar=%s pm_ready=%s bnc_ready=%s",
                         rows, cur_bar, pm_state.ready, binance_state.ready)
                rows = 0
        except Exception as exc:
            log.exception("snapshot loop: %s", exc)
        await asyncio.sleep(SNAPSHOT_SECS)


async def run() -> None:
    log.info("ws_recorder start  coin=%s bar=%ds snap=%dms dir=%s retain=%.0fd",
             COIN, BAR_SECONDS, SNAPSHOT_MS, RAW_LOG_DIR, RETENTION_DAYS)
    _seed_history()
    enable_external_market_apply()
    writer = RotatingWriter(RAW_LOG_DIR, COIN)
    tasks = [
        asyncio.create_task(run_binance_ws(), name="binance_ws"),
        asyncio.create_task(run_pm_ws(), name="pm_ws"),
        asyncio.create_task(_roll_watcher(), name="roll"),
        asyncio.create_task(_snapshot_loop(writer), name="snap"),
    ]
    await asyncio.gather(*tasks)


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
