"""mintsalvage.py — MINT the pair, HOLD the winner, SALVAGE the loser at 1c
(user spec 2026-08-02, evening).

Per bar (cur+1, minted pre-open via the COLLATERAL ADAPTER — the user-found
correction: approve pUSD to CtfCollateralAdapter and call splitPosition ON
the adapter; it converts internally and mints the CANONICAL tradeable
tokens; docs.polymarket.com/trading/ctf/split):

  1. splitPosition($MINT_USD) -> MINT_USD UP + MINT_USD DOWN, tradeable.
  2. NEVER sell the winner (hold to redemption — keep the full $1.00).
  3. At tl <= SALV_ARM_TL (45s), if |Binance lead| >= LEAD_GATE_BPS (5bps,
     the vacuum's measured zero-flip threshold): post-only SELL the LOSING
     side at SALV_PX (0.01). Watchdog until close: cancel if the lead decays
     below LEAD_CANCEL_BPS or flips sign (VAC_PRE_ABORT pattern). Knife-edge
     bars sell nothing — hold both to redemption, breakeven by construction.
  4. Ask stays through the post-close grace (free option), dies with the
     market. Winner redeems $1.00/share (PM auto-claim + redeem loop).

Economics per $1 pair: winner 1.00 + loser salvage 0.01·P(fill) − 1.00 mint
= +1c·P(fill), downside ≈ gas, mislock capped by the gate+watchdog and the
$5 daily halt. ⚠ OPEN VENUE QUESTION the first bars answer: does a 5sh sell
at 0.01 ($0.05 notional) clear the venue minimum? Share-min is 5; the $1
notional rule rejected cheap BUYS (35b5398). PF_SALV_REJ logs the verdict.

Env: PM_MINT_USD(5) PM_SALV_PX(0.01) PM_SALV_ARM_TL(45) PM_LEAD_GATE_BPS(5)
     PM_LEAD_CANCEL_BPS(2) PM_MAX_DAILY_LOSS(5) PM_ADAPTER(0xAdA100Db...)
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
                    TRAINING_EVENT_LOG_PATH, USE_RELAYER, log)
from core.binance_ws import binance_state, run_binance_ws
from core.gamma import (fetch_market_for_window, get_up_down_tokens,
                        grid_window_start, window_slug)
from engine import redemptions
from engine.clob import (build_clob_client, cancel_order, ensure_approvals,
                         ensure_ctf_approval, fetch_usdc_balance,
                         get_order_filled_verified, place_limit_sell)
from engine.redemptions import _erc1155_balance, _rpc, redeem_resolved_positions
from execution.events import EventLog

COIN = os.getenv("COIN", "btc").lower()
LIVE_TRADING = os.getenv("LIVE_TRADING", "false").lower() in ("true", "1", "yes")
_real = LIVE_TRADING and not DRY_RUN

MINT_USD = float(os.getenv("PM_MINT_USD", "5"))
SIZE = float(int(MINT_USD))
SALV_PX = float(os.getenv("PM_SALV_PX", "0.01"))
# tiered arming: "tl_max:gate_bps,..." — the more decided the bar, the earlier
# the loser's 1c ask goes out (vacuum-measured btc ladder: >=8-10bps held from
# t-45s produced zero flips). The last tier is the late fallback.
SALV_TIERS = sorted(
    (tuple(float(x) for x in part.split(":"))
     for part in os.getenv("PM_SALV_TIERS", "60:10,30:6,10:3").split(",")),
    key=lambda t: -t[0])
SALV_ARM_TL = max(t[0] for t in SALV_TIERS)
LEAD_CANCEL_FLOOR = 2.0
LEAD_CANCEL_BPS = float(os.getenv("PM_LEAD_CANCEL_BPS", "2"))
MAX_DAILY_LOSS = float(os.getenv("PM_MAX_DAILY_LOSS", "5"))
COLLATERAL = os.getenv("PM_COLLATERAL", "0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB")
# user-found correction: split goes through the collateral adapter, which
# converts pUSD internally and mints the CANONICAL tradeable tokens
ADAPTER = os.getenv("PM_ADAPTER", "0xAdA100Db00Ca00073811820692005400218FcE1f")
STATE_PATH = os.getenv("PM_STATE_PATH", "/app/logs/mintsalvage-state.json")

_event_log = EventLog(TRAINING_EVENT_LOG_PATH)


def _event(ev: str, **kw):
    _event_log.write(ev, coin=COIN, **kw)


# ── on-chain: adapter split + pUSD allowance (Safe/relayer tx paths) ─────────

def _submit_tx(calldata: str, to: str) -> str:
    if USE_RELAYER:
        from engine.relayer import submit_and_wait
        return submit_and_wait(to, calldata)
    from eth_account import Account
    account = Account.from_key(POLYMARKET_PK)
    nonce = int(_rpc("eth_getTransactionCount", [account.address, "pending"]), 16)
    gas_price = int(int(_rpc("eth_gasPrice", []), 16) * 1.5)
    if SIGNATURE_TYPE == 2 and POLYMARKET_FUNDER:
        # the adapter path (pUSD burn -> USDC.e -> CTF split -> mints) needs
        # ~600-700k gas; redemptions' 300k default OOG'd at 291,753 (measured)
        return redemptions._send_tx_via_safe(calldata, to, nonce, gas_price,
                                             gas_limit=900_000)
    raise RuntimeError("mintsalvage requires the Safe or relayer path")


def _split_calldata(condition_id_hex: str, amount_6dp: int) -> str:
    from eth_utils import keccak, to_checksum_address
    selector = keccak(b"splitPosition(address,bytes32,bytes32,uint256[],uint256)")[:4]
    cond = bytes.fromhex(condition_id_hex.removeprefix("0x"))
    args = eth_abi.encode(
        ["address", "bytes32", "bytes32", "uint256[]", "uint256"],
        [to_checksum_address(COLLATERAL), b"\x00" * 32, cond, [1, 2], amount_6dp])
    return "0x" + (selector + args).hex()


def _onchain_owner() -> str:
    return POLYMARKET_FUNDER if (SIGNATURE_TYPE == 2 and POLYMARKET_FUNDER) else POLYMARKET_ADDRESS


def _pusd_allowance(spender: str) -> int:
    from eth_utils import keccak, to_checksum_address
    sel = keccak(b"allowance(address,address)")[:4]
    data = "0x" + (sel + eth_abi.encode(
        ["address", "address"],
        [to_checksum_address(_onchain_owner()), to_checksum_address(spender)])).hex()
    return int(_rpc("eth_call", [{"to": COLLATERAL, "data": data}, "latest"]), 16)


def _approve_pusd(spender: str) -> str:
    from eth_utils import keccak, to_checksum_address
    sel = keccak(b"approve(address,uint256)")[:4]
    data = "0x" + (sel + eth_abi.encode(
        ["address", "uint256"],
        [to_checksum_address(spender), 2 ** 256 - 1])).hex()
    return _submit_tx(data, to=COLLATERAL)


def _tx_status(tx: str):
    try:
        r = _rpc("eth_getTransactionReceipt", [tx])
    except Exception:
        return None
    return None if not r else int(r.get("status", "0x0"), 16)


def _outcome_up(ws: int):
    try:
        url = ("https://gamma-api.polymarket.com/markets?slug=" + window_slug(ws)
               + "&closed=true")
        req = urllib.request.Request(url, headers={"User-Agent": "mintsalvage"})
        d = json.loads(urllib.request.urlopen(req, timeout=10).read())
        if not d or not d[0].get("closed"):
            return None
        op = d[0]["outcomePrices"]
        op = json.loads(op) if isinstance(op, str) else op
        return str(op[0]) in ("1", "1.0")
    except Exception:
        return None


class Bar:
    FIELDS = ("ws", "cond", "slug", "tok", "minted", "salv_side", "salv_oid",
              "salv_sh", "aborted", "settled")

    def __init__(self, ws: int, cond: str, up: str, dn: str, slug: str):
        self.ws, self.cond, self.slug = ws, cond, slug
        self.tok = {"UP": up, "DOWN": dn}
        self.minted = False
        self.salv_side = None          # side we sold (the identified LOSER)
        self.salv_oid = None
        self.salv_sh = 0.0
        self.aborted = False           # watchdog cancelled the salvage ask
        self.settled = False

    def dump(self):
        return {k: getattr(self, k) for k in self.FIELDS}

    @classmethod
    def load(cls, d):
        b = cls(d["ws"], d["cond"], d["tok"]["UP"], d["tok"]["DOWN"], d["slug"])
        for k in cls.FIELDS[4:]:
            setattr(b, k, d[k])
        return b


class MintSalvage:
    def __init__(self):
        self.clob = None
        self.bars: dict[int, Bar] = {}
        self.day_pnl: dict[str, float] = {}
        self.halted = False
        self.mint_tries: dict[int, int] = {}

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
        _event("PF_RESUME", bars=len(self.bars), halted=self.halted)

    # ── mint the NEXT bar's outcomes during the current bar (user spec:
    # unconditional pre-open mint, 5 tokens each side) ───────────────────────
    async def mint_loop(self):
        while True:
            try:
                await self._mint_next()
            except Exception as exc:
                log.exception("mint: %s", exc)
                _event("PF_ERR", where="mint", err=str(exc)[:160])
            await asyncio.sleep(8.0)

    async def _mint_next(self):
        if self.halted:
            return
        now = time.time()
        target = grid_window_start(now) + BAR_SECONDS
        bar = self.bars.get(target)
        if bar is None:
            mk = await asyncio.to_thread(fetch_market_for_window, target)
            if not mk:
                return
            up, dn = get_up_down_tokens(mk)
            cond = mk.get("conditionId")
            if not (up and dn and cond):
                return
            bar = Bar(target, cond, up["token_id"], dn["token_id"], mk.get("slug", ""))
            _event("PF_DISCOVER", bar=target, slug=bar.slug,
                   tl_to_open=round(target - now, 1))
            self.bars[target] = bar
        if not bar.minted:
            await self._mint_now(bar)
            self._save()

    async def _mint_now(self, bar: Bar) -> bool:
        """Gate passed: mint the pair via the adapter, receipt-waited."""
        if not _real:
            bar.minted = True
            _event("PF_MINT", bar=bar.ws, usd=MINT_USD, dry=True)
            return True
        bal = await asyncio.to_thread(fetch_usdc_balance, self.clob)
        if bal is not None and bal < MINT_USD + 1.0:
            _event("PF_SKIP", bar=bar.ws, reason="low_usdc", bal=round(bal or 0, 2))
            return False
        if self.mint_tries.get(bar.ws, 0) >= 2:
            return False
        self.mint_tries[bar.ws] = self.mint_tries.get(bar.ws, 0) + 1
        calldata = _split_calldata(bar.cond, int(MINT_USD * 1e6))
        t0 = time.time()
        tx = await asyncio.to_thread(_submit_tx, calldata, ADAPTER)
        status = gas_used = None
        for _ in range(10):
            await asyncio.sleep(1.5)
            try:
                r = await asyncio.to_thread(_rpc, "eth_getTransactionReceipt", [tx])
            except Exception:
                r = None
            if r:
                status = int(r.get("status", "0x0"), 16)
                gas_used = int(r.get("gasUsed", "0x0"), 16)
                break
        _event("PF_MINT", bar=bar.ws, usd=MINT_USD, tx=tx, status=status,
               gas_used=gas_used, secs=round(time.time() - t0, 1), live=True)
        if status != 1:
            return False
        for _ in range(4):
            have = await asyncio.to_thread(_erc1155_balance, bar.tok["UP"], _onchain_owner())
            if have >= int(SIZE * 1e6) - 10:
                break
            await asyncio.sleep(1.0)
        else:
            _event("PF_ERR", where="mint_credit", bar=bar.ws)
            return False
        bar.minted = True
        self._save()
        for side in ("UP", "DOWN"):
            try:
                await asyncio.to_thread(ensure_ctf_approval, self.clob, bar.tok[side])
            except Exception:
                pass
        return True

    # ── salvage: gated 1c ask on the identified loser, with watchdog ────────
    async def salvage_loop(self):
        while True:
            await asyncio.sleep(0.5)
            now = time.time()
            for bar in list(self.bars.values()):
                if bar.settled:
                    continue
                try:
                    await self._salvage_bar(bar, now)
                except Exception as exc:
                    log.exception("salvage: %s", exc)
                    _event("PF_ERR", where="salvage", bar=bar.ws, err=str(exc)[:160])

    def _lead_bps(self, ws: int):
        if not binance_state.ready or binance_state.age() > 5.0:
            return None
        op = binance_state.bar_open_at(ws)
        if not op or binance_state.current_price <= 0:
            return None
        return (binance_state.current_price - op) / op * 1e4

    async def _salvage_bar(self, bar: Bar, now: float):
        tl = bar.ws + BAR_SECONDS - now
        if tl > SALV_ARM_TL or tl < -60:
            return
        lead = self._lead_bps(bar.ws)
        if bar.salv_oid and not bar.aborted and tl > 0:
            # watchdog: the outcome we sold against must STAY decided
            if lead is None or abs(lead) < LEAD_CANCEL_BPS or \
                    (lead < 0) != (bar.salv_side == "UP"):
                bar.aborted = True
                await asyncio.to_thread(cancel_order, self.clob, bar.salv_oid) if _real else None
                _event("PF_SALV_ABORT", bar=bar.ws, side=bar.salv_side,
                       lead_bps=None if lead is None else round(lead, 1),
                       tl=round(tl, 1))
                self._save()
            return
        if bar.salv_oid or bar.aborted or tl <= 0:
            return
        if lead is None or not bar.minted:
            return
        if not any(tl <= tl_max and abs(lead) >= gate
                   for tl_max, gate in SALV_TIERS):
            return
        loser = "DOWN" if lead > 0 else "UP"
        if not _real:
            bar.salv_side, bar.salv_oid, bar.salv_sh = loser, f"paper-{bar.ws}", SIZE
            _event("PF_SALV_PLACE", bar=bar.ws, side=loser, px=SALV_PX, sh=SIZE,
                   lead_bps=round(lead, 1), tl=round(tl, 1), dry=True)
            return
        try:
            oid, matched = await asyncio.to_thread(
                place_limit_sell, self.clob, bar.tok[loser], SIZE, SALV_PX)
        except Exception as exc:
            _event("PF_SALV_REJ", bar=bar.ws, side=loser, sh=SIZE,
                   err=str(exc)[:160])
            bar.aborted = True
            return
        if oid:
            bar.salv_side, bar.salv_oid, bar.salv_sh = loser, oid, SIZE
            _event("PF_SALV_PLACE", bar=bar.ws, side=loser, px=SALV_PX, sh=SIZE,
                   lead_bps=round(lead, 1), tl=round(tl, 1), order=oid,
                   matched=matched)
        else:
            bar.aborted = True
            _event("PF_SALV_REJ", bar=bar.ws, side=loser, sh=SIZE,
                   err="no order id (venue min? post-only cross?)")
        self._save()

    # ── settle on gamma resolution ───────────────────────────────────────────
    async def settle_loop(self):
        while True:
            await asyncio.sleep(15.0)
            now = time.time()
            for bar in list(self.bars.values()):
                if bar.settled or now < bar.ws + BAR_SECONDS + 10:
                    continue
                if not bar.minted:
                    bar.settled = True
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
                self._save()
            return
        wside = "UP" if oc else "DOWN"
        salv_fill = 0.0
        if bar.salv_oid and _real:
            await asyncio.to_thread(cancel_order, self.clob, bar.salv_oid)
            v = await asyncio.to_thread(get_order_filled_verified,
                                        self.clob, bar.salv_oid, bar.cond)
            salv_fill = v or 0.0
        sold_winner = bar.salv_side == wside and salv_fill > 0
        # winner shares held redeem at 1.00; sold loser shares got SALV_PX
        win_held = SIZE - (salv_fill if sold_winner else 0.0)
        pnl = win_held * 1.0 + salv_fill * SALV_PX - MINT_USD
        day = time.strftime("%Y-%m-%d", time.gmtime(bar.ws))
        self.day_pnl[day] = self.day_pnl.get(day, 0.0) + pnl
        bar.settled = True
        _event("PF_SETTLE", bar=bar.ws, outcome=wside, salv_side=bar.salv_side,
               salv_fill=round(salv_fill, 2), mislock=sold_winner,
               aborted=bar.aborted, pnl=round(pnl, 4),
               day_pnl=round(self.day_pnl[day], 3), live=_real)
        if self.day_pnl[day] <= -MAX_DAILY_LOSS and not self.halted:
            self.halted = True
            _event("PF_HALT", day=day, day_pnl=round(self.day_pnl[day], 2))
        for w in [w for w in self.bars if self.bars[w].settled and w < bar.ws - 7200]:
            self.bars.pop(w, None)
        self._save()

    async def redeem_loop(self):
        while True:
            await asyncio.sleep(900.0)
            if _real:
                try:
                    await asyncio.to_thread(redeem_resolved_positions, None)
                except Exception as exc:
                    log.warning("redeem: %s", exc)

    async def hb_loop(self):
        while True:
            await asyncio.sleep(60.0)
            day = time.strftime("%Y-%m-%d", time.gmtime())
            _event("PF_HB", bars=len([b for b in self.bars.values() if not b.settled]),
                   halted=self.halted, lead=self._lead_bps(grid_window_start(time.time())),
                   day_pnl=round(self.day_pnl.get(day, 0.0), 3))

    def _seed_history(self):
        sym = f"{COIN.upper()}USDT"
        for base in ("https://api.binance.com", "https://data-api.binance.vision"):
            try:
                req = urllib.request.Request(
                    f"{base}/api/v3/klines?symbol={sym}&interval=1m&limit=60",
                    headers={"User-Agent": "Mozilla/5.0"})
                raw = json.loads(urllib.request.urlopen(req, timeout=10).read())
                binance_state.seed_minute_bars(
                    [(int(k[0]) // 1000, float(k[1]), float(k[2]), float(k[3]), float(k[4]))
                     for k in raw])
                log.info("Seeded %d 1m bars from %s", len(raw), base)
                return
            except Exception as exc:
                log.warning("kline seed via %s failed: %s", base, exc)

    async def run(self):
        log.info("mintsalvage %s: mint=$%.0f salv=%.2f tiers=%s cancel=%.0fbps "
                 "maxDD=$%.0f adapter=%s", "LIVE" if _real else "PAPER",
                 MINT_USD, SALV_PX, SALV_TIERS, LEAD_CANCEL_BPS,
                 MAX_DAILY_LOSS, ADAPTER[:10])
        _event("PF_START", live=_real, mint=MINT_USD, salv=SALV_PX,
               tiers=os.getenv("PM_SALV_TIERS", "60:10,30:6,10:3"))
        self._seed_history()
        self._load()
        if _real:
            self.clob = await asyncio.to_thread(build_clob_client)
            await asyncio.to_thread(ensure_approvals, self.clob)
            alw = await asyncio.to_thread(_pusd_allowance, ADAPTER)
            if alw < int(MINT_USD * 1e6) * 100:
                tx = await asyncio.to_thread(_approve_pusd, ADAPTER)
                _event("PF_ALLOWANCE", spender=ADAPTER, tx=tx)
        await asyncio.gather(run_binance_ws(), self.mint_loop(),
                             self.salvage_loop(), self.settle_loop(),
                             self.redeem_loop(), self.hb_loop())


def main():
    asyncio.run(MintSalvage().run())


if __name__ == "__main__":
    main()
