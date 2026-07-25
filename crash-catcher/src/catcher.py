"""catcher.py — both-side 1c crash-catcher (early-queue GTC catch-bids).

Edge (validated 2026-07-25): late panic-dumps on a "dead" side overshoot —
tokens swept down to $0.01 still win ~4-5% of bars, so a 1c fill has
EV ≈ 0.04·$0.99 − 0.96·$0.01 ≈ +3c/share. Live proof: wallet 0xCd9bf7F6…
runs exactly this — 115 days, 1,492 bars filled at median $0.01, 5% winners,
+$22k (~$190/day). Our tape: 1c-zone fills win 3.4-4.1%, best on near-ties.

Mechanics: at bar OPEN place presigned GTC bids at CATCH_PRICE on BOTH tokens
(queue position is the moat — the 1c level is FIFO; early placement eats the
dump first). Most bars nothing fills. CANCEL both strictly BEFORE close
(CATCH_CANCEL_TL, default 0.7s): post-close the losing token goes to 0 and a
lingering 1c bid is a guaranteed donation. Hold fills to settlement.

PAPER mode: FastExec paper fills are meaningless for resting bids, so paper
sim here watches the live trade prints and counts prints at <= CATCH_PRICE
while our bid would be active (FRONT-OF-QUEUE OPTIMISTIC — real fills depend
on queue share; paper numbers are an upper bound).

Env: CATCH_PRICE(0.01) CATCH_SHARES(5) CATCH_CANCEL_TL(0.7)
     CATCH_MAX_DAILY_LOSS(50). FAV_ORDER_TYPE must be 'gtc'.
     No post-close grace needed (we're flat at close by design).
"""
from __future__ import annotations

import asyncio
import json
import os
import time

from config import DRY_RUN, TRAINING_EVENT_LOG_PATH, log
from core.pm_ws import pm_state
from execution.events import EventLog

COIN = os.getenv("COIN", "btc").lower()
LIVE_TRADING = os.getenv("LIVE_TRADING", "false").lower() in ("true", "1", "yes")
_real = LIVE_TRADING and not DRY_RUN

PRICE = float(os.getenv("CATCH_PRICE", "0.01"))
SHARES = float(os.getenv("CATCH_SHARES", "5"))
CANCEL_TL = float(os.getenv("CATCH_CANCEL_TL", "0.7"))
MAX_DAILY_LOSS = float(os.getenv("CATCH_MAX_DAILY_LOSS", "50"))

_event_log = EventLog(TRAINING_EVENT_LOG_PATH)


def _event(ev: str, **kw):
    _event_log.write(ev, coin=COIN, **kw)


def outcome_up(ws: int):
    """Gamma resolution: True=UP won, False=DOWN, None=unresolved."""
    import json, urllib.request
    from core.gamma import window_slug
    try:
        url = ("https://gamma-api.polymarket.com/markets?slug=" + window_slug(ws)
               + "&closed=true")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        d = json.loads(urllib.request.urlopen(req, timeout=10).read())
        if not d or not d[0].get("closed"):
            return None
        op = d[0]["outcomePrices"]
        op = json.loads(op) if isinstance(op, str) else op
        return str(op[0]) in ("1", "1.0")
    except Exception:
        return None


class CatcherStrategy:
    def __init__(self) -> None:
        self.runner = None
        self.open_bets: dict[tuple[int, str], dict] = {}   # (ws, side) -> bet
        self.day_pnl: dict[str, float] = {}
        self.halted = False
        self._placed: dict[int, dict] = {}     # ws -> {"UP": oid, "DOWN": oid}
        self._cancelled: set[int] = set()
        self._paper_fill: dict[tuple[int, str], float] = {}
        self._trade_seq: int = 0               # paper-sim print cursor
        self.settled: set[tuple[int, str]] = set()

    def bind(self, runner) -> None:
        self.runner = runner
        _event("CATCH_START", live=_real, price=PRICE, shares=SHARES,
               cancel_tl=CANCEL_TL, max_dd=MAX_DAILY_LOSS)

    def presign_requests(self, ctx):
        reqs = []
        if ctx.up_token:
            reqs.append(("catch-UP", ctx.up_token, PRICE, SHARES))
        if ctx.down_token:
            reqs.append(("catch-DOWN", ctx.down_token, PRICE, SHARES))
        return reqs

    def _prune(self, ws: int) -> None:
        for k in [k for k in self._placed if k < ws - 3600]:
            self._placed.pop(k, None)
        self._cancelled = {k for k in self._cancelled if k >= ws - 3600}
        for k in [k for k in self._paper_fill if k[0] < ws - 3600]:
            self._paper_fill.pop(k, None)

    # ── paper fill sim: prints at <= PRICE while our bid is active ──────────
    def _paper_scan(self, ws: int) -> None:
        for tr in pm_state.recent_trades:
            if tr["seq"] <= self._trade_seq:
                continue
            self._trade_seq = tr["seq"]
            px = float(tr["price"])
            if px > PRICE + 1e-9:
                continue
            side = ("UP" if tr["token_id"] == pm_state.token_id_up else
                    "DOWN" if tr["token_id"] == pm_state.token_id_down else None)
            if side is None:
                continue
            k = (ws, side)
            got = self._paper_fill.get(k, 0.0)
            if got >= SHARES:
                continue
            add = min(float(tr["size"]), SHARES - got)
            self._paper_fill[k] = got + add
            _event("CATCH_PAPER_PRINT", bar=ws, side=side, px=px,
                   size=round(add, 1), cum=round(self._paper_fill[k], 1))

    async def on_tick(self, ctx) -> None:
        ws = ctx.ws
        tl = ctx.t_left
        if self.halted or tl < 0:
            return

        # place both catch-bids at bar start; RETRY failed sides (a 1c bid is
        # rejected as "marketable, min $1" while a side's ask is still <=1c at
        # open — the book normalizes within seconds once MMs quote)
        if tl > CANCEL_TL + 2:
            st = self._placed.setdefault(ws, {"orders": {}, "tries": 0, "last": 0.0})
            missing = [(s, t) for s, t in (("UP", ctx.up_token), ("DOWN", ctx.down_token))
                       if t and s not in st["orders"]]
            now = time.time()
            if missing and st["tries"] < 6 and now - st["last"] >= 3.0:
                st["tries"] += 1
                st["last"] = now
                for side, token in missing:
                    key = f"catch-{side}"
                    try:
                        if self.runner.exec.has_presigned(key):
                            oid, matched, post_ms, avg_px, filled = \
                                await self.runner.exec.fire_presigned(key)
                        else:
                            oid, matched, _s, post_ms, avg_px, filled = \
                                await self.runner.exec.fire_direct(token, PRICE, SHARES)
                    except Exception as exc:
                        _event("CATCH_ERR", bar=ws, side=side, attempt=st["tries"],
                               err=str(exc)[:160])
                        continue
                    if oid:
                        st["orders"][side] = oid
                    if _real and filled:
                        _event("CATCH_IMM_FILL", bar=ws, side=side,
                               filled=round(filled, 1),
                               px=None if avg_px is None else round(avg_px, 4))
                if not missing or all(s in st["orders"] for s, _ in missing) \
                        or st["tries"] >= 6:
                    _event("CATCH_PLACED", bar=ws, tl=round(tl, 1),
                           tries=st["tries"], orders=st["orders"] or {"both": "FAILED"},
                           live=_real)
            if missing:
                return

        if not _real:
            self._paper_scan(ws)

        # cancel strictly before close
        if tl <= CANCEL_TL and ws not in self._cancelled:
            self._cancelled.add(ws)
            await self._teardown(ws)

    async def _teardown(self, ws: int) -> None:
        orders = (self._placed.get(ws) or {}).get("orders") or {}
        for side, oid in orders.items():
            filled = 0.0
            if _real and oid:
                # user-WS is fill truth (0.0 = healthy feed, genuinely unfilled);
                # poll_filled only as fallback when the feed is stale — its lies
                # are then caught by settle-time verification
                wsv = self.runner.exec.ws_filled(oid)
                if wsv is not None:
                    filled = wsv
                else:
                    pf = await self.runner.exec.poll_filled(oid)
                    filled = pf or 0.0
                await self.runner.exec.cancel(oid)
            elif not _real:
                filled = self._paper_fill.get((ws, side), 0.0)
            if filled > 0:
                self.open_bets[(ws, side)] = {
                    "fill_px": PRICE, "fill_qty": filled, "order_id": oid}
                _event("CATCH_FILL", bar=ws, side=side, filled=round(filled, 1),
                       px=PRICE, live=_real)
        if not any(self.open_bets.get((ws, s)) for s in ("UP", "DOWN")):
            _event("CATCH_FLAT", bar=ws)
        self._prune(ws)

    def _verified_size(self, ws: int, side: str) -> float:
        """Ground truth from the public trade record: sum of our BUY fills on
        this bar+token. poll_filled/size_matched LIES for orders the venue
        culled at market close (2026-07-25 phantom-fill incident) — only the
        on-chain trade record counts."""
        import urllib.request, urllib.parse
        from core.gamma import window_slug
        me = (os.getenv("POLYMARKET_FUNDER") or os.getenv("POLYMARKET_ADDRESS") or "").lower()
        if not me:
            return -1.0
        slug = window_slug(ws)
        want_oc = "Up" if side == "UP" else "Down"
        try:
            u = ("https://data-api.polymarket.com/activity?" + urllib.parse.urlencode(
                {"user": me, "limit": 300}))
            req = urllib.request.Request(u, headers={"User-Agent": "catcher"})
            rows = json.loads(urllib.request.urlopen(req, timeout=10).read())
        except Exception:
            return -1.0
        tot = 0.0
        for r in rows:
            if (r.get("type") == "TRADE" and r.get("side") == "BUY"
                    and r.get("slug") == slug and r.get("outcome") == want_oc):
                tot += float(r.get("size") or 0)
        return tot

    async def settle_loop(self) -> None:
        while True:
            await asyncio.sleep(5.0)
            now = time.time()
            for key in [k for k in self.open_bets
                        if k[0] + 300 < now - 8 and k not in self.settled]:
                ws, side = key
                bet = self.open_bets[key]
                if _real and not bet.get("verified"):
                    v = await asyncio.to_thread(self._verified_size, ws, side)
                    if v < 0:
                        if now - (ws + 300) < 120:
                            continue          # data-api hiccup — retry
                        v = 0.0
                    if v <= 0:
                        self.settled.add(key)
                        _event("CATCH_PHANTOM", bar=ws, side=side,
                               polled=round(bet["fill_qty"], 1))
                        continue
                    bet["fill_qty"] = min(bet["fill_qty"], v)
                    bet["verified"] = True
                oc = await asyncio.to_thread(outcome_up, ws)
                if oc is None:
                    if now - (ws + 300) > 600:
                        self.settled.add(key)
                        _event("CATCH_SETTLE_TIMEOUT", bar=ws, side=side)
                    continue
                won = (side == "UP") == oc
                q = bet["fill_qty"] or 0.0
                pnl = q * ((1.0 if won else 0.0) - bet["fill_px"])
                day = time.strftime("%Y-%m-%d", time.gmtime(ws))
                self.day_pnl[day] = self.day_pnl.get(day, 0.0) + pnl
                self.settled.add(key)
                _event("CATCH_SETTLE", bar=ws, side=side,
                       outcome="UP" if oc else "DOWN", won=won,
                       qty=round(q, 1), pnl=round(pnl, 3),
                       day_pnl=round(self.day_pnl[day], 2), live=_real)
                if self.day_pnl[day] <= -MAX_DAILY_LOSS and not self.halted:
                    self.halted = True
                    _event("CATCH_HALT", day=day,
                           day_pnl=round(self.day_pnl[day], 2), max_dd=MAX_DAILY_LOSS)


def main():
    from execution.runner import TakerRunner
    log.info("catcher %s: coin=%s price=%.2f shares=%.0f cancel_tl=%.1fs maxDD=$%.0f",
             "LIVE" if _real else "PAPER(front-queue bound)", COIN, PRICE, SHARES,
             CANCEL_TL, MAX_DAILY_LOSS)
    runner = TakerRunner(CatcherStrategy(), live=_real, event_logger=_event)
    asyncio.run(runner.run())


if __name__ == "__main__":
    main()
