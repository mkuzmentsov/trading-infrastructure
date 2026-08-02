"""pennymint.py — MINT + dual 99c asks + matched 2c flip (user spec 2026-08-02).

Per bar (always the bar AHEAD_BARS ahead — never the in-progress one):
  1. splitPosition $MINT_USD via the Safe/relayer (same path redemptions use)
     -> MINT_USD UP + MINT_USD DOWN shares held by the funder.
  2. Rest GTC SELLs at HI_PX(0.99) on BOTH tokens, pre-open (earliest FIFO).
  3. Listen to fills (user-WS, poll fallback). When n shares fill at HI on
     token X: sell n of the complement Y at LO_PX(0.02) — cancel Y's 99c ask
     first (all Y shares are reserved by it), re-rest the remainder at 99c
     when it still clears the venue's $1 minimum.
  4. At resolution: cancel leftovers, book PnL (verified fills only), leftover
     winner shares redeem to $1 via redeem_resolved_positions.

Economics per matched pair: 0.99 + 0.02 = 1.01 vs $1.00 minted; worst case
-1c/share/bar (unflipped loser). Backtest: rebate_arb/SLOW.md round 4.
⚠ At $5 the LO leg is $0.10 notional — if the venue's $1 minimum applies to
sells, the flip is rejected; the bot logs the exact venue error (that
rejection is itself a probe measurement) and rides instead.

Env: PM_AHEAD_BARS(2) PM_MINT_USD(5) PM_HI_PX(0.99) PM_LO_PX(0.02)
     PM_MAX_DAILY_LOSS(5) + LIVE_TRADING/DRY_RUN.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
import urllib.request

import eth_abi

from config import (BAR_SECONDS, CTF_CONTRACT, DRY_RUN, POLYMARKET_ADDRESS,
                    POLYMARKET_FUNDER, POLYMARKET_PK, SIGNATURE_TYPE,
                    TRAINING_EVENT_LOG_PATH, USDC_ADDRESS, USE_RELAYER, log)
from core.gamma import fetch_market_for_window, get_up_down_tokens, grid_window_start, window_slug
from engine import redemptions
from engine.clob import (build_clob_client, cancel_order, ensure_approvals,
                         ensure_ctf_approval, fetch_usdc_balance,
                         get_order_filled_verified, place_limit_sell)
from engine.redemptions import _erc1155_balance, _rpc, redeem_resolved_positions
from execution.events import EventLog

COIN = os.getenv("COIN", "btc").lower()
LIVE_TRADING = os.getenv("LIVE_TRADING", "false").lower() in ("true", "1", "yes")
_real = LIVE_TRADING and not DRY_RUN

AHEAD = int(os.getenv("PM_AHEAD_BARS", "2"))
MINT_USD = float(os.getenv("PM_MINT_USD", "5"))
HI_PX = float(os.getenv("PM_HI_PX", "0.99"))
LO_PX = float(os.getenv("PM_LO_PX", "0.02"))
MAX_DAILY_LOSS = float(os.getenv("PM_MAX_DAILY_LOSS", "5"))
SIZE = float(int(MINT_USD))            # shares per side (pairs = $1 each)
MIN_NOTIONAL = 1.0                     # venue minimum per order (35b5398)

_event_log = EventLog(TRAINING_EVENT_LOG_PATH)


def _event(ev: str, **kw):
    _event_log.write(ev, coin=COIN, **kw)


# ── on-chain: splitPosition + USDC allowance via the redemptions tx paths ────

def _submit_ctf(calldata: str, to: str) -> str:
    if USE_RELAYER:
        from engine.relayer import submit_and_wait
        return submit_and_wait(to, calldata)
    from eth_account import Account
    account = Account.from_key(POLYMARKET_PK)
    nonce = int(_rpc("eth_getTransactionCount", [account.address, "pending"]), 16)
    gas_price = int(int(_rpc("eth_gasPrice", []), 16) * 1.5)
    if SIGNATURE_TYPE == 2 and POLYMARKET_FUNDER:
        return redemptions._send_tx_via_safe(calldata, to, nonce, gas_price)
    if to != CTF_CONTRACT:
        raise RuntimeError("EOA path only supports CTF calls here")
    return redemptions._send_tx(calldata, nonce, gas_price)


def _split_calldata(condition_id_hex: str, amount_6dp: int) -> str:
    from eth_utils import keccak, to_checksum_address
    selector = keccak(b"splitPosition(address,bytes32,bytes32,uint256[],uint256)")[:4]
    cond = bytes.fromhex(condition_id_hex.removeprefix("0x"))
    args = eth_abi.encode(
        ["address", "bytes32", "bytes32", "uint256[]", "uint256"],
        [to_checksum_address(USDC_ADDRESS), b"\x00" * 32, cond, [1, 2], amount_6dp])
    return "0x" + (selector + args).hex()


def _onchain_owner() -> str:
    return POLYMARKET_FUNDER if (SIGNATURE_TYPE == 2 and POLYMARKET_FUNDER) else POLYMARKET_ADDRESS


def _usdc_ctf_allowance() -> int:
    from eth_utils import keccak, to_checksum_address
    sel = keccak(b"allowance(address,address)")[:4]
    data = "0x" + (sel + eth_abi.encode(
        ["address", "address"],
        [to_checksum_address(_onchain_owner()), to_checksum_address(CTF_CONTRACT)])).hex()
    return int(_rpc("eth_call", [{"to": USDC_ADDRESS, "data": data}, "latest"]), 16)


def _approve_usdc_ctf() -> str:
    from eth_utils import keccak, to_checksum_address
    sel = keccak(b"approve(address,uint256)")[:4]
    data = "0x" + (sel + eth_abi.encode(
        ["address", "uint256"],
        [to_checksum_address(CTF_CONTRACT), 2 ** 256 - 1])).hex()
    return _submit_ctf(data, to=USDC_ADDRESS)


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


class Bar:
    def __init__(self, ws: int, cond: str, up: str, dn: str, slug: str):
        self.ws, self.cond, self.slug = ws, cond, slug
        self.tok = {"UP": up, "DOWN": dn}
        self.minted = False
        self.hi_oid = {"UP": None, "DOWN": None}    # open 99c sell per side
        self.hi_sh = {"UP": 0.0, "DOWN": 0.0}       # size currently resting at HI
        self.hi_fill = {"UP": 0.0, "DOWN": 0.0}     # observed HI fills (running)
        self.lo_oid = {"UP": [], "DOWN": []}        # 2c sell orders per side
        self.lo_sh = {"UP": 0.0, "DOWN": 0.0}       # 2c size placed per side
        self.lo_rej = {"UP": False, "DOWN": False}  # venue-min rejection latched
        self.settled = False


class PennyMint:
    def __init__(self):
        self.clob = None
        self.user_feed = None
        self.bars: dict[int, Bar] = {}
        self.day_pnl: dict[str, float] = {}
        self.halted = False
        self.allowance_ok = False

    # ── mint + place, one bar ahead of the crowd ─────────────────────────────
    async def mint_place_loop(self):
        while True:
            try:
                await self._mint_place_once()
            except Exception as exc:
                log.exception("mint_place: %s", exc)
                _event("PF_ERR", where="mint_place", err=str(exc)[:160])
            await asyncio.sleep(10.0)

    async def _mint_place_once(self):
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
        _event("PF_DISCOVER", bar=target, slug=bar.slug, tl_to_open=round(target - now, 1))

        if not _real:
            _event("PF_MINT", bar=target, usd=MINT_USD, live=False, dry=True)
            bar.minted = True
            for side in ("UP", "DOWN"):
                bar.hi_oid[side] = f"paper-{side}-{target}"
                bar.hi_sh[side] = SIZE
            _event("PF_HI_PLACE", bar=target, live=False, dry=True, px=HI_PX, sh=SIZE)
            self.bars[target] = bar
            return

        # funds check: the vacuum's resting $600 can starve the account
        bal = await asyncio.to_thread(fetch_usdc_balance, self.clob)
        if bal is not None and bal < MINT_USD + 1.0:
            _event("PF_SKIP", bar=target, reason="low_usdc", bal=round(bal or 0, 2))
            return

        if not self.allowance_ok:
            alw = await asyncio.to_thread(_usdc_ctf_allowance)
            if alw < int(MINT_USD * 1e6):
                tx = await asyncio.to_thread(_approve_usdc_ctf)
                _event("PF_ALLOWANCE", tx=tx)
            self.allowance_ok = True

        # idempotency: a crashed run may have minted already
        have = await asyncio.to_thread(_erc1155_balance, bar.tok["UP"], _onchain_owner())
        if have < int(SIZE * 1e6):
            calldata = _split_calldata(cond, int(MINT_USD * 1e6))
            tx = await asyncio.to_thread(_submit_ctf, calldata, CTF_CONTRACT)
            _event("PF_MINT", bar=target, usd=MINT_USD, tx=tx, live=True)
            for _ in range(10):                      # wait for the ERC1155 credit
                await asyncio.sleep(3.0)
                have = await asyncio.to_thread(_erc1155_balance, bar.tok["UP"], _onchain_owner())
                if have >= int(SIZE * 1e6):
                    break
            else:
                _event("PF_ERR", where="mint_credit", bar=target, have=have)
                return
        bar.minted = True

        for side in ("UP", "DOWN"):
            try:
                await asyncio.to_thread(ensure_ctf_approval, self.clob, bar.tok[side])
            except Exception:
                pass
            oid, matched = await asyncio.to_thread(
                place_limit_sell, self.clob, bar.tok[side], SIZE, HI_PX)
            bar.hi_oid[side] = oid
            bar.hi_sh[side] = SIZE if oid else 0.0
            _event("PF_HI_PLACE", bar=target, side=side, px=HI_PX, sh=SIZE,
                   order=oid or "FAILED", matched=matched, live=True)
        self.bars[target] = bar

    # ── fills -> matched 2c flip ─────────────────────────────────────────────
    async def fills_flip_loop(self):
        n = 0
        while True:
            await asyncio.sleep(1.0)
            n += 1
            for bar in list(self.bars.values()):
                if bar.settled:
                    continue
                try:
                    await self._check_bar_fills(bar, poll=(n % 5 == 0))
                except Exception as exc:
                    log.exception("fills_flip: %s", exc)
                    _event("PF_ERR", where="fills_flip", bar=bar.ws, err=str(exc)[:160])

    def _ws_matched(self, oid):
        f = self.user_feed
        if not _real or not f or not f.healthy():
            return None
        return f.matched(oid)

    async def _check_bar_fills(self, bar: Bar, poll: bool):
        for side in ("UP", "DOWN"):
            oid = bar.hi_oid[side]
            if not oid:
                continue
            got = self._ws_matched(oid)
            if got is None and poll and _real:
                got = await asyncio.to_thread(
                    get_order_filled_verified, self.clob, oid, bar.cond)
            if got is None or got <= bar.hi_fill[side] + 1e-9:
                continue
            new = got - bar.hi_fill[side]
            bar.hi_fill[side] = got
            _event("PF_HI_FILL", bar=bar.ws, side=side, filled=round(got, 2),
                   new=round(new, 2))
            await self._flip(bar, filled_side=side)

    async def _flip(self, bar: Bar, filled_side: str):
        """Sell the complement at LO_PX, matched to the filled quantity."""
        other = "DOWN" if filled_side == "UP" else "UP"
        want = min(bar.hi_fill[filled_side],
                   SIZE - bar.hi_fill[other] - bar.lo_sh[other])
        qty = want - bar.lo_sh[other]
        if qty < 0.5 or bar.lo_rej[other]:
            return
        if not _real:
            bar.lo_sh[other] += qty
            _event("PF_LO_PLACE", bar=bar.ws, side=other, px=LO_PX, sh=qty, dry=True)
            return
        # free the complement's shares: its 99c ask reserves all of them
        if bar.hi_oid[other]:
            await asyncio.to_thread(cancel_order, self.clob, bar.hi_oid[other])
            bar.hi_fill[other] = max(
                bar.hi_fill[other],
                (await asyncio.to_thread(get_order_filled_verified, self.clob,
                                         bar.hi_oid[other], bar.cond)) or 0.0)
            bar.hi_oid[other] = None
            bar.hi_sh[other] = 0.0
        if qty * LO_PX < MIN_NOTIONAL:
            _event("PF_LO_MIN", bar=bar.ws, side=other, px=LO_PX, sh=qty,
                   notional=round(qty * LO_PX, 2),
                   note="under venue $1 min — attempting anyway (probe)")
        try:
            oid, matched = await asyncio.to_thread(
                place_limit_sell, self.clob, bar.tok[other], qty, LO_PX)
        except Exception as exc:
            oid, matched = None, False
            _event("PF_LO_REJ", bar=bar.ws, side=other, sh=qty, err=str(exc)[:160])
        if oid:
            bar.lo_oid[other].append(oid)
            bar.lo_sh[other] += qty
            _event("PF_LO_PLACE", bar=bar.ws, side=other, px=LO_PX, sh=qty,
                   order=oid, matched=matched)
        else:
            bar.lo_rej[other] = True
            _event("PF_LO_REJ", bar=bar.ws, side=other, sh=qty,
                   err="no order id (venue rejected — riding instead)")
        # re-rest the complement's remainder at 99c if it still clears $1
        rem = SIZE - bar.hi_fill[other] - bar.lo_sh[other]
        if rem * HI_PX >= MIN_NOTIONAL:
            roid, _m = await asyncio.to_thread(
                place_limit_sell, self.clob, bar.tok[other], rem, HI_PX)
            if roid:
                bar.hi_oid[other] = roid
                bar.hi_sh[other] = rem
                _event("PF_HI_REPLACE", bar=bar.ws, side=other, sh=rem, order=roid)

    # ── settle: verified fills + leftover redemption value ───────────────────
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
        hi_v, lo_v = {}, {}
        for side in ("UP", "DOWN"):
            if not _real:
                hi_v[side], lo_v[side] = bar.hi_fill[side], 0.0
                continue
            hv = bar.hi_fill[side]
            if bar.hi_oid[side]:
                await asyncio.to_thread(cancel_order, self.clob, bar.hi_oid[side])
                v = await asyncio.to_thread(get_order_filled_verified,
                                            self.clob, bar.hi_oid[side], bar.cond)
                if v is not None:
                    hv = max(hv, v)
            lv = 0.0
            for oid in bar.lo_oid[side]:
                await asyncio.to_thread(cancel_order, self.clob, oid)
                v = await asyncio.to_thread(get_order_filled_verified,
                                            self.clob, oid, bar.cond)
                lv += v or 0.0
            hi_v[side], lo_v[side] = hv, lv
        wside = "UP" if oc else "DOWN"
        lside = "DOWN" if oc else "UP"
        leftover_w = max(0.0, SIZE - hi_v[wside] - lo_v[wside])
        proceeds = sum(hi_v.values()) * HI_PX + sum(lo_v.values()) * LO_PX
        pnl = proceeds + leftover_w * 1.0 - MINT_USD
        day = time.strftime("%Y-%m-%d", time.gmtime(bar.ws))
        self.day_pnl[day] = self.day_pnl.get(day, 0.0) + pnl
        bar.settled = True
        _event("PF_SETTLE", bar=bar.ws, outcome=wside,
               hi_up=round(hi_v["UP"], 2), hi_dn=round(hi_v["DOWN"], 2),
               lo_up=round(lo_v["UP"], 2), lo_dn=round(lo_v["DOWN"], 2),
               jack=hi_v[lside] > 0.4, leftover_w=round(leftover_w, 2),
               pnl=round(pnl, 4), day_pnl=round(self.day_pnl[day], 3), live=_real)
        if self.day_pnl[day] <= -MAX_DAILY_LOSS and not self.halted:
            self.halted = True
            _event("PF_HALT", day=day, day_pnl=round(self.day_pnl[day], 2))
        for w in [w for w in self.bars if self.bars[w].settled and w < bar.ws - 7200]:
            self.bars.pop(w, None)

    # ── leftover winner shares -> USDC ───────────────────────────────────────
    async def redeem_loop(self):
        while True:
            await asyncio.sleep(600.0)
            if not _real:
                continue
            try:
                await asyncio.to_thread(redeem_resolved_positions, None)
            except Exception as exc:
                log.warning("redeem: %s", exc)

    async def hb_loop(self):
        while True:
            await asyncio.sleep(60.0)
            day = time.strftime("%Y-%m-%d", time.gmtime())
            open_bars = [w for w, b in self.bars.items() if not b.settled]
            _event("PF_HB", bars_open=len(open_bars), halted=self.halted,
                   day_pnl=round(self.day_pnl.get(day, 0.0), 3))

    async def run(self):
        log.info("pennymint %s: coin=%s ahead=%d mint=$%.0f hi=%.2f lo=%.2f "
                 "maxDD=$%.0f", "LIVE" if _real else "PAPER", COIN, AHEAD,
                 MINT_USD, HI_PX, LO_PX, MAX_DAILY_LOSS)
        _event("PF_START", live=_real, ahead=AHEAD, mint_usd=MINT_USD,
               hi=HI_PX, lo=LO_PX, size=SIZE)
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
        tasks = [self.mint_place_loop(), self.fills_flip_loop(),
                 self.settle_loop(), self.redeem_loop(), self.hb_loop()]
        if self.user_feed:
            tasks.append(self.user_feed.run())
        await asyncio.gather(*tasks)


def main():
    asyncio.run(PennyMint().run())


if __name__ == "__main__":
    main()
