"""pennymint.py — the 99c/2c harvest (user spec 2026-08-02), venue-native.

The literal mint frame is IMPOSSIBLE with this account's plumbing — measured
live 2026-08-02: the CLOB's tokens are USDC.e-collateral positionIds (gamma
clobTokenIds match USDC.e derivation exactly), balances are pUSD, and pUSD's
convert authority is the v2 exchange alone (burn() -> Unauthorized, no
withdraw/4626 path). Six $5 pUSD splits produced valid but UNTRADEABLE
tokens (txs 0x61cf../0xc124../0x6b9d../0xbdce../0x5fd1../0x85ce..), merged
back in full (0x9db9.., 0x5c9d..). The exchange mints inside complementary
matches — so the same strategy is expressed with the unified-book identity
(every recorded snapshot has ub == 1-da with equal sizes):

  mint + sell UP@0.99 + sell DOWN@0.99   ==   bid DOWN@0.01 + bid UP@0.01
  "n filled at 99c -> sell complement n at 2c"
       ==  our 1c bid on T fills n -> sell those n T at 0.02

Same fills, same queue, same counterparties, same PnL: +1c/pair when both
legs complete, worst case -1c/share/bar, +99c jackpot when a 99c-equivalent
fill later reverses. Backtest: rebate_arb/SLOW.md round 4.

Venue $1 minimum sets the sizes: 1c bids 100sh ($1.00 each -> $2/bar
outlay), 2c sells in >=50sh chunks (a sub-50sh remainder at bar end is
unplaceable and rides). Bids go on the cur+AHEAD bar pre-open (earliest
FIFO; never the in-progress bar).

Env: PM_AHEAD_BARS(2) PM_SIZE_SH(100) PM_BID_PX(0.01) PM_LO_PX(0.02)
     PM_MAX_DAILY_LOSS(5) + LIVE_TRADING/DRY_RUN.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
import urllib.request

from config import BAR_SECONDS, DRY_RUN, TRAINING_EVENT_LOG_PATH, log
from core.gamma import (fetch_market_for_window, get_up_down_tokens,
                        grid_window_start, window_slug)
from engine.clob import (build_clob_client, cancel_order, ensure_approvals,
                         fetch_usdc_balance, get_order_filled_verified,
                         place_limit_order, place_limit_sell)
from execution.events import EventLog

COIN = os.getenv("COIN", "btc").lower()
LIVE_TRADING = os.getenv("LIVE_TRADING", "false").lower() in ("true", "1", "yes")
_real = LIVE_TRADING and not DRY_RUN

AHEAD = int(os.getenv("PM_AHEAD_BARS", "2"))
SIZE = float(os.getenv("PM_SIZE_SH", "100"))
BID_PX = float(os.getenv("PM_BID_PX", "0.01"))
LO_PX = float(os.getenv("PM_LO_PX", "0.02"))
MAX_DAILY_LOSS = float(os.getenv("PM_MAX_DAILY_LOSS", "5"))
MIN_NOTIONAL = 1.0                     # venue minimum per order (35b5398)

_event_log = EventLog(TRAINING_EVENT_LOG_PATH)


def _event(ev: str, **kw):
    _event_log.write(ev, coin=COIN, **kw)


def _outcome_up(ws: int):
    try:
        url = ("https://gamma-api.polymarket.com/markets?slug=" + window_slug(ws)
               + "&closed=true")
        req = urllib.request.Request(url, headers={"User-Agent": "pennymint"})
        d = json.loads(urllib.request.urlopen(req, timeout=10).read())
        if not d or not d[0].get("closed"):
            return None
        op = d[0]["outcomePrices"]
        op = json.loads(op) if isinstance(op, str) else op
        return str(op[0]) in ("1", "1.0")
    except Exception:
        return None


STATE_PATH = os.getenv("PM_STATE_PATH", "/app/logs/pennymint-state.json")


class Bar:
    def __init__(self, ws: int, cond: str, up: str, dn: str, slug: str):
        self.ws, self.cond, self.slug = ws, cond, slug
        self.tok = {"UP": up, "DOWN": dn}
        self.bid_oid = {"UP": None, "DOWN": None}
        self.bid_fill = {"UP": 0.0, "DOWN": 0.0}    # observed 1c-bid fills
        self.lo_oid = {"UP": [], "DOWN": []}        # 2c sells of the SAME token
        self.lo_sh = {"UP": 0.0, "DOWN": 0.0}       # 2c size placed
        self.settled = False

    def dump(self) -> dict:
        return {k: getattr(self, k) for k in
                ("ws", "cond", "slug", "tok", "bid_oid", "bid_fill",
                 "lo_oid", "lo_sh", "settled")}

    @classmethod
    def load(cls, d: dict) -> "Bar":
        b = cls(d["ws"], d["cond"], d["tok"]["UP"], d["tok"]["DOWN"], d["slug"])
        for k in ("bid_oid", "bid_fill", "lo_oid", "lo_sh", "settled"):
            setattr(b, k, d[k])
        return b


class PennyMint:
    def __init__(self):
        self.clob = None
        self.user_feed = None
        self.bars: dict[int, Bar] = {}
        self.day_pnl: dict[str, float] = {}
        self.halted = False

    # ── restart safety: resting GTC orders outlive the process ──────────────
    def _save(self):
        try:
            tmp = STATE_PATH + ".tmp"
            with open(tmp, "w") as fh:
                json.dump({"bars": {str(w): b.dump() for w, b in self.bars.items()},
                           "day_pnl": self.day_pnl, "halted": self.halted}, fh)
            os.replace(tmp, STATE_PATH)
        except Exception as exc:
            log.warning("state save failed: %s", exc)

    def _load(self):
        try:
            with open(STATE_PATH) as fh:
                d = json.load(fh)
        except Exception:
            return
        cutoff = time.time() - 3600
        for w, bd in d.get("bars", {}).items():
            if bd["ws"] >= cutoff:
                self.bars[int(w)] = Bar.load(bd)
        self.day_pnl = d.get("day_pnl", {})
        self.halted = bool(d.get("halted", False))
        _event("PF_RESUME", bars=len(self.bars),
               open=[w for w, b in self.bars.items() if not b.settled],
               halted=self.halted)

    # ── place the two 1c bids on the cur+AHEAD bar, pre-open ─────────────────
    async def place_loop(self):
        while True:
            try:
                await self._place_once()
            except Exception as exc:
                log.exception("place: %s", exc)
                _event("PF_ERR", where="place", err=str(exc)[:160])
            await asyncio.sleep(10.0)

    async def _place_once(self):
        if self.halted:
            return
        now = time.time()
        target = grid_window_start(now) + AHEAD * BAR_SECONDS
        if target in self.bars or now >= target:      # never enter a started bar
            return
        mk = await asyncio.to_thread(fetch_market_for_window, target)
        if not mk:
            return
        up, dn = get_up_down_tokens(mk)
        cond = mk.get("conditionId")
        if not (up and dn and cond):
            _event("PF_ERR", where="discover", err="tokens/cond missing", ws=target)
            return
        bar = Bar(target, cond, up["token_id"], dn["token_id"], mk.get("slug", ""))
        _event("PF_DISCOVER", bar=target, slug=bar.slug,
               tl_to_open=round(target - now, 1))
        if _real:
            bal = await asyncio.to_thread(fetch_usdc_balance, self.clob)
            if bal is not None and bal < 2 * SIZE * BID_PX + 1.0:
                _event("PF_SKIP", bar=target, reason="low_usdc",
                       bal=round(bal or 0, 2))
                return
        for side in ("UP", "DOWN"):
            if _real:
                oid = await asyncio.to_thread(
                    place_limit_order, self.clob, bar.tok[side], "BUY", SIZE, BID_PX)
            else:
                oid = f"paper-{side}-{target}"
            bar.bid_oid[side] = oid
            _event("PF_BID_PLACE", bar=target, side=side, px=BID_PX, sh=SIZE,
                   order=oid or "REJECTED", live=_real)
        self.bars[target] = bar
        self._save()

    # ── fills -> matched 2c sell of the same token ───────────────────────────
    async def fills_flip_loop(self):
        n = 0
        while True:
            await asyncio.sleep(1.0)
            n += 1
            for bar in list(self.bars.values()):
                if bar.settled:
                    continue
                try:
                    await self._check_bar(bar, poll=(n % 5 == 0))
                except Exception as exc:
                    log.exception("fills: %s", exc)
                    _event("PF_ERR", where="fills", bar=bar.ws, err=str(exc)[:160])

    def _ws_matched(self, oid):
        f = self.user_feed
        if not _real or not f or not f.healthy():
            return None
        return f.matched(oid)

    async def _check_bar(self, bar: Bar, poll: bool):
        for side in ("UP", "DOWN"):
            oid = bar.bid_oid[side]
            if not oid:
                continue
            got = self._ws_matched(oid)
            if got is None and poll and _real:
                got = await asyncio.to_thread(
                    get_order_filled_verified, self.clob, oid, bar.cond)
            if got is None or got <= bar.bid_fill[side] + 1e-9:
                continue
            new = got - bar.bid_fill[side]
            bar.bid_fill[side] = got
            _event("PF_BID_FILL", bar=bar.ws, side=side, filled=round(got, 2),
                   new=round(new, 2))
            await self._flip(bar, side)
            self._save()

    async def _flip(self, bar: Bar, side: str):
        """Sell the tokens the 1c bid just delivered, at 2c, in chunks that
        clear the venue minimum."""
        unflipped = bar.bid_fill[side] - bar.lo_sh[side]
        full = bar.bid_fill[side] >= SIZE - 0.5
        if unflipped * LO_PX < MIN_NOTIONAL and not full:
            return                               # wait for a >=50sh chunk
        qty = unflipped
        if qty < 0.5:
            return
        if not _real:
            bar.lo_sh[side] += qty
            _event("PF_LO_PLACE", bar=bar.ws, side=side, px=LO_PX, sh=qty, dry=True)
            return
        # tokens from a just-matched fill credit on-chain a few seconds later;
        # retry at 1s — a late-bar fill's flip window is seconds wide (the
        # 8:15 bar's fill at tl=0 lost its flip to the 3s cadence)
        oid = None
        for attempt in range(1, 7):
            try:
                oid, matched = await asyncio.to_thread(
                    place_limit_sell, self.clob, bar.tok[side], qty, LO_PX)
                break
            except Exception as exc:
                if "not enough balance" in str(exc).lower() and attempt < 6:
                    await asyncio.sleep(1.0)
                    continue
                _event("PF_LO_REJ", bar=bar.ws, side=side, sh=qty,
                       err=str(exc)[:160])
                return
        if oid:
            bar.lo_oid[side].append(oid)
            bar.lo_sh[side] += qty
            _event("PF_LO_PLACE", bar=bar.ws, side=side, px=LO_PX, sh=qty,
                   order=oid, matched=matched)
        else:
            _event("PF_LO_REJ", bar=bar.ws, side=side, sh=qty,
                   err="no order id (venue rejected)")

    # ── settle on gamma resolution, verified fills only ──────────────────────
    async def settle_loop(self):
        while True:
            await asyncio.sleep(15.0)
            now = time.time()
            for bar in list(self.bars.values()):
                if bar.settled or now < bar.ws + BAR_SECONDS + 10:
                    continue
                try:
                    await self._settle_bar(bar, now)
                except Exception as exc:
                    log.exception("settle: %s", exc)
                    _event("PF_ERR", where="settle", bar=bar.ws, err=str(exc)[:160])

    async def _settle_bar(self, bar: Bar, now: float):
        oc = await asyncio.to_thread(_outcome_up, bar.ws)
        if oc is None:
            if now - (bar.ws + BAR_SECONDS) > 900:
                bar.settled = True
                _event("PF_SETTLE_TIMEOUT", bar=bar.ws)
            return
        bid_v, lo_v = {}, {}
        for side in ("UP", "DOWN"):
            if not _real:
                bid_v[side], lo_v[side] = bar.bid_fill[side], bar.lo_sh[side]
                continue
            bv = bar.bid_fill[side]
            if bar.bid_oid[side]:
                await asyncio.to_thread(cancel_order, self.clob, bar.bid_oid[side])
                v = await asyncio.to_thread(get_order_filled_verified,
                                            self.clob, bar.bid_oid[side], bar.cond)
                if v is not None:
                    bv = max(bv, v)
            lv = 0.0
            for oid in bar.lo_oid[side]:
                await asyncio.to_thread(cancel_order, self.clob, oid)
                v = await asyncio.to_thread(get_order_filled_verified,
                                            self.clob, oid, bar.cond)
                lv += v or 0.0
            bid_v[side], lo_v[side] = bv, lv
        wside = "UP" if oc else "DOWN"
        pnl = 0.0
        for side in ("UP", "DOWN"):
            leftover = max(0.0, bid_v[side] - lo_v[side])
            pnl += (lo_v[side] * LO_PX - bid_v[side] * BID_PX
                    + leftover * (1.0 if side == wside else 0.0))
        day = time.strftime("%Y-%m-%d", time.gmtime(bar.ws))
        self.day_pnl[day] = self.day_pnl.get(day, 0.0) + pnl
        bar.settled = True
        _event("PF_SETTLE", bar=bar.ws, outcome=wside,
               bid_up=round(bid_v["UP"], 2), bid_dn=round(bid_v["DOWN"], 2),
               lo_up=round(lo_v["UP"], 2), lo_dn=round(lo_v["DOWN"], 2),
               jack=bid_v[wside] > 0.4,
               pnl=round(pnl, 4), day_pnl=round(self.day_pnl[day], 3), live=_real)
        if self.day_pnl[day] <= -MAX_DAILY_LOSS and not self.halted:
            self.halted = True
            _event("PF_HALT", day=day, day_pnl=round(self.day_pnl[day], 2))
        for w in [w for w in self.bars if self.bars[w].settled and w < bar.ws - 7200]:
            self.bars.pop(w, None)
        self._save()

    async def hb_loop(self):
        while True:
            await asyncio.sleep(60.0)
            day = time.strftime("%Y-%m-%d", time.gmtime())
            _event("PF_HB",
                   bars_open=sum(1 for b in self.bars.values() if not b.settled),
                   halted=self.halted,
                   day_pnl=round(self.day_pnl.get(day, 0.0), 3))

    async def run(self):
        log.info("pennymint %s: coin=%s ahead=%d size=%dsh bid=%.2f lo=%.2f "
                 "maxDD=$%.0f", "LIVE" if _real else "PAPER", COIN, AHEAD,
                 int(SIZE), BID_PX, LO_PX, MAX_DAILY_LOSS)
        _event("PF_START", live=_real, ahead=AHEAD, size=SIZE, bid=BID_PX,
               lo=LO_PX)
        self._load()
        if _real:
            self.clob = await asyncio.to_thread(build_clob_client)
            await asyncio.to_thread(ensure_approvals, self.clob)
            try:
                from execution.userws import UserFeed
                c = getattr(self.clob, "creds", None)
                if c:
                    self.user_feed = UserFeed({"apiKey": c.api_key,
                                               "secret": c.api_secret,
                                               "passphrase": c.api_passphrase})
            except Exception as exc:
                log.warning("user feed unavailable: %s", exc)
        tasks = [self.place_loop(), self.fills_flip_loop(),
                 self.settle_loop(), self.hb_loop()]
        if self.user_feed:
            tasks.append(self.user_feed.run())
        await asyncio.gather(*tasks)


def main():
    asyncio.run(PennyMint().run())


if __name__ == "__main__":
    main()
