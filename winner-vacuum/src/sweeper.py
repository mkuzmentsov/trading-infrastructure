"""sweeper.py — redemption + collateral converter for the mintsalvage fleet.

Two capital leaks this closes, both on a 15s cadence:

1. REDEEM through the pUSD adapter. Polymarket's auto-redeemer pays winners
   out in USDC.e, which cannot be minted from. `CtfCollateralAdapter.
   redeemPositions` pays out pUSD instead -- so whenever we win the race, the
   capital comes back tradable and never strands.

2. CONVERT whatever USDC.e did strand (auto-redeemer beat us, or the UI's
   "Activate Funds" was never clicked). Round trip with calls the fleet
   already uses: raw-CTF splitPosition with USDC.e collateral, then
   mergePositions through the pUSD adapter -- $220 was recovered this way by
   hand on 2026-08-03 for ~$0.02 of gas.

Runs as its own deployment so the trading bots stay single-purpose. It shares
the signing EOA with them, so it backs off on nonce collisions rather than
fighting for the nonce.

Env: PM_SWEEP_EVERY_SECS(15) PM_SWEEP_MIN_USD(5) PM_ADAPTER PM_COLLATERAL
"""
from __future__ import annotations

import asyncio
import json
import os
import time
import urllib.request

import eth_abi
import requests

from config import (CTF_CONTRACT, DATA_API, DRY_RUN, POLYMARKET_ADDRESS,
                    POLYMARKET_FUNDER, POLYMARKET_PK, SIGNATURE_TYPE,
                    TRAINING_EVENT_LOG_PATH, USE_RELAYER, log)
from engine import redemptions
from engine.redemptions import _rpc
from execution.events import EventLog

LIVE = os.getenv("LIVE_TRADING", "false").lower() in ("true", "1", "yes") and not DRY_RUN
EVERY = float(os.getenv("PM_SWEEP_EVERY_SECS", "15"))
MIN_USD = float(os.getenv("PM_SWEEP_MIN_USD", "5"))
PUSD = os.getenv("PM_COLLATERAL", "0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB")
USDCE = os.getenv("PM_USDCE", "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174")
ADAPTER = os.getenv("PM_ADAPTER", "0xAdA100Db00Ca00073811820692005400218FcE1f")
GAS_CAP_GWEI = float(os.getenv("PM_GAS_CAP_GWEI", "700"))
REDEEM_COOLDOWN = float(os.getenv("PM_REDEEM_COOLDOWN_SECS", "900"))

_event_log = EventLog(TRAINING_EVENT_LOG_PATH)


def _event(ev: str, **kw):
    _event_log.write(ev, coin="sweep", **kw)


def _owner() -> str:
    return POLYMARKET_FUNDER if (SIGNATURE_TYPE == 2 and POLYMARKET_FUNDER) else POLYMARKET_ADDRESS


def _submit(data: str, to: str, gas_limit: int = 900_000) -> str:
    if USE_RELAYER:
        from engine.relayer import submit_and_wait
        return submit_and_wait(to, data)
    from eth_account import Account
    acct = Account.from_key(POLYMARKET_PK)
    nonce = int(_rpc("eth_getTransactionCount", [acct.address, "pending"]), 16)
    gp = int(_rpc("eth_gasPrice", []), 16)
    try:
        base = int(_rpc("eth_getBlockByNumber", ["latest", False]).get("baseFeePerGas", "0x0"), 16)
    except Exception:
        base = 0
    gas = min(max(int(base * 1.4) + int(30e9), int(gp * 1.15)), int(GAS_CAP_GWEI * 1e9))
    return redemptions._send_tx_via_safe(data, to, nonce, gas, gas_limit=gas_limit)


def _wait(tx: str, tries: int = 20):
    for _ in range(tries):
        time.sleep(2.0)
        try:
            r = _rpc("eth_getTransactionReceipt", [tx])
        except Exception:
            r = None
        if r:
            return int(r.get("status", "0x0"), 16)
    return None


def _erc20(token: str) -> int:
    from eth_utils import keccak, to_checksum_address
    sel = keccak(b"balanceOf(address)")[:4]
    d = "0x" + (sel + eth_abi.encode(["address"], [to_checksum_address(_owner())])).hex()
    return int(_rpc("eth_call", [{"to": token, "data": d}, "latest"]), 16)


def _redeemable():
    """Conditions we hold that have resolved (Data API)."""
    try:
        r = requests.get(f"{DATA_API}/positions",
                         params={"user": _owner(), "redeemable": "true",
                                 "sizeThreshold": "0.5"}, timeout=10)
        r.raise_for_status()
        out = {}
        for p in r.json() or []:
            cid = p.get("conditionId")
            if cid:
                out[cid] = out.get(cid, 0.0) + float(p.get("size") or 0)
        return out
    except Exception as exc:
        log.warning("redeemable fetch: %s", exc)
        return {}


def _redeem_via_adapter(cond: str) -> int | None:
    """redeemPositions on the pUSD adapter -> proceeds arrive as pUSD."""
    from eth_utils import keccak, to_checksum_address
    sel = keccak(b"redeemPositions(address,bytes32,bytes32,uint256[])")[:4]
    cb = bytes.fromhex(cond[2:] if cond.startswith("0x") else cond)
    data = "0x" + (sel + eth_abi.encode(
        ["address", "bytes32", "bytes32", "uint256[]"],
        [to_checksum_address(PUSD), b"\x00" * 32, cb, [1, 2]])).hex()
    return _wait(_submit(data, ADAPTER))


def _daily_condition():
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    now = datetime.now(ZoneInfo("America/New_York"))
    end = now.date() if now.hour < 12 else (now.date() + timedelta(days=1))
    slug = f"bitcoin-up-or-down-on-{end.strftime('%B').lower()}-{end.day}-{end.year}"
    try:
        d = json.loads(urllib.request.urlopen(urllib.request.Request(
            f"https://gamma-api.polymarket.com/markets?slug={slug}",
            headers={"User-Agent": "sweeper"}), timeout=10).read())
        return d[0].get("conditionId") if d else None
    except Exception:
        return None


def _convert(amount: int) -> bool:
    """USDC.e -> pUSD: raw-CTF split, then merge through the pUSD adapter."""
    from eth_utils import keccak, to_checksum_address
    cond = _daily_condition()
    if not cond:
        _event("PF_SWEEP_ERR", stage="condition", err="daily market unavailable")
        return False
    cb = bytes.fromhex(cond[2:] if cond.startswith("0x") else cond)
    sel = keccak(b"splitPosition(address,bytes32,bytes32,uint256[],uint256)")[:4]
    data = "0x" + (sel + eth_abi.encode(
        ["address", "bytes32", "bytes32", "uint256[]", "uint256"],
        [to_checksum_address(USDCE), b"\x00" * 32, cb, [1, 2], amount])).hex()
    tx1 = _submit(data, CTF_CONTRACT)
    if _wait(tx1) != 1:
        _event("PF_SWEEP_ERR", stage="split", tx=tx1, usd=round(amount / 1e6, 2))
        return False
    sel = keccak(b"mergePositions(address,bytes32,bytes32,uint256[],uint256)")[:4]
    data = "0x" + (sel + eth_abi.encode(
        ["address", "bytes32", "bytes32", "uint256[]", "uint256"],
        [to_checksum_address(PUSD), b"\x00" * 32, cb, [1, 2], amount])).hex()
    tx2 = _submit(data, ADAPTER)
    st = _wait(tx2)
    _event("PF_SWEEP", usd=round(amount / 1e6, 2), split_tx=tx1, merge_tx=tx2, status=st)
    return st == 1


async def run():
    log.info("sweeper %s: every=%.0fs min=$%.0f adapter=%s",
             "LIVE" if LIVE else "DRY", EVERY, MIN_USD, ADAPTER[:10])
    _event("PF_SWEEP_START", live=LIVE, every=EVERY, min_usd=MIN_USD)
    seen_fail = {}
    done = {}          # cond -> ts of last successful redeem (Data API lags,
                       # and a dust/loser position can keep reporting
                       # redeemable=true; without this it re-redeems every
                       # cycle, ~$0.01 a time = tens of dollars a day)
    hb = 0.0
    while True:
        try:
            if LIVE:
                # 1. redeem resolved positions through the adapter (pays pUSD)
                now_ts = time.time()
                for cond, size in (await asyncio.to_thread(_redeemable)).items():
                    if seen_fail.get(cond, 0) >= 3:
                        continue
                    if now_ts - done.get(cond, 0) < REDEEM_COOLDOWN:
                        continue
                    st = await asyncio.to_thread(_redeem_via_adapter, cond)
                    _event("PF_REDEEM", cond=cond[:12], shares=round(size, 1), status=st)
                    done[cond] = now_ts
                    if st != 1:
                        seen_fail[cond] = seen_fail.get(cond, 0) + 1
                    if len(done) > 400:
                        cutoff = now_ts - REDEEM_COOLDOWN
                        done = {k: v for k, v in done.items() if v > cutoff}
                # 2. convert whatever stranded as USDC.e
                amt = await asyncio.to_thread(_erc20, USDCE)
                if amt >= int(MIN_USD * 1e6):
                    await asyncio.to_thread(_convert, amt)
            if time.time() - hb > 300:
                hb = time.time()
                p = await asyncio.to_thread(_erc20, PUSD) if LIVE else 0
                u = await asyncio.to_thread(_erc20, USDCE) if LIVE else 0
                _event("PF_SWEEP_HB", pusd=round(p / 1e6, 2), usdce=round(u / 1e6, 2))
        except Exception as exc:
            log.exception("sweeper: %s", exc)
            _event("PF_SWEEP_ERR", err=str(exc)[:160])
        await asyncio.sleep(EVERY)


def main():
    asyncio.run(run())


if __name__ == "__main__":
    main()
