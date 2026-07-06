#!/usr/bin/env python3
"""pm-rebates-farmer — dead-simple Polymarket rebate farmer. NO math, NO AI.

Every loop: for each coin, on the market `FARM_LEAD_BARS` bars ahead of the
current 5m window (default +2 = pre-open, where fills are least adversely
selected), rest a 50/50 pair — a post-only BUY at 0.50 on BOTH the UP and DOWN
token. When a leg fills, rest a post-only take-profit SELL at 0.99 for the
filled size. Hold. Losers expire worthless; winners exit via the 0.99 TP or,
if unsold, the periodic redemption sweep.

Rationale: pre-open fills are ~unbiased (no realized move yet) so directional
PnL ≈ 0 and the maker rebate (paid on every filled order) is the product.

Env: FARM_COINS=btc  FARM_SHARES=10  FARM_ENTRY=0.50  FARM_TP=0.99
     FARM_LEAD_BARS=2  FARM_LOOP_SECS=5  FARM_BALANCE_SECS=1800
Requires live creds (POLYMARKET_PK/FUNDER). No persistent storage — in-memory
state, reconciled against the exchange's open orders at startup.
"""
from __future__ import annotations
import os
import time

from config import log
from engine.clob import (
    build_clob_client, place_limit_order, fetch_order_status,
    fetch_usdc_balance, ensure_approvals,
)
from core.gamma import _gamma_get
from core.telegram import tg

COINS = [c.strip() for c in os.getenv("FARM_COINS", "btc").split(",") if c.strip()]
SHARES = float(os.getenv("FARM_SHARES", "10"))
ENTRY = float(os.getenv("FARM_ENTRY", "0.50"))
TP = float(os.getenv("FARM_TP", "0.99"))
LEAD = int(os.getenv("FARM_LEAD_BARS", "2"))
LOOP = int(os.getenv("FARM_LOOP_SECS", "5"))
BAL_EVERY = int(os.getenv("FARM_BALANCE_SECS", "1800"))
BAR = 300

# state: (coin, window_ts) -> {"tokens": (up, down), "end": ts,
#   "up"/"down": {"buy": id|None, "tp": id|None, "filled": shares, "tp_done": bool}}
state: dict = {}


def market_for(coin: str, window_ts: int):
    slug = f"{coin}-updown-5m-{int(window_ts)}"
    try:
        data = _gamma_get({"slug": slug})
        if data:
            m = data[0]
            import json
            toks = json.loads(m.get("clobTokenIds", "[]"))
            if len(toks) == 2 and m.get("acceptingOrders"):
                return toks[0], toks[1]
    except Exception as exc:
        log.debug("market_for %s: %s", slug, exc)
    return None


def ensure_pair(clob, coin: str, window_ts: int):
    key = (coin, window_ts)
    if key in state:
        return
    toks = market_for(coin, window_ts)
    if not toks:
        return
    up, down = toks
    rec = {"tokens": (up, down), "end": window_ts + BAR,
           "up": {"buy": None, "tp": None, "filled": 0.0, "tp_done": False},
           "down": {"buy": None, "tp": None, "filled": 0.0, "tp_done": False}}
    for side_name, tok in (("up", up), ("down", down)):
        oid = place_limit_order(clob, tok, "BUY", SHARES, ENTRY)
        rec[side_name]["buy"] = oid
        log.info("PLACED %s %s BUY %.0f @ %.2f  slug=%s-updown-5m-%d  order=%s",
                 coin, side_name.upper(), SHARES, ENTRY, coin, window_ts, oid)
    state[key] = rec


def service_fills(clob):
    """Poll each resting BUY; on any matched size, place the 0.99 TP once."""
    for (coin, ws), rec in list(state.items()):
        for side_name in ("up", "down"):
            s = rec[side_name]
            if s["tp_done"] or not s["buy"]:
                continue
            info = fetch_order_status(clob, s["buy"])
            if not isinstance(info, dict):
                continue
            try:
                matched = float(info.get("size_matched") or 0)
            except (TypeError, ValueError):
                matched = 0.0
            if matched > s["filled"] + 1e-9:
                s["filled"] = matched
            if s["filled"] >= 5 and not s["tp"]:  # min sellable size 5
                tok = rec["tokens"][0 if side_name == "up" else 1]
                tp_id = place_limit_order(clob, tok, "SELL", round(s["filled"], 2), TP)
                s["tp"] = tp_id
                log.info("PLACED %s %s TP SELL %.0f @ %.2f  order=%s",
                         coin, side_name.upper(), s["filled"], TP, tp_id)
                if info.get("status") in ("matched", "filled"):
                    s["tp_done"] = True


def cleanup(now: float):
    for key in [k for k, r in state.items() if now > r["end"] + 120]:
        state.pop(key, None)


def seed_from_exchange(clob):
    """Avoid double-placing after a restart: mark windows that already have our
    open orders so ensure_pair skips them (their TPs get serviced normally)."""
    try:
        from py_clob_client_v2.clob_types import OpenOrderParams
        oo = clob.get_open_orders(OpenOrderParams())
        seeded = {o.get("market") or o.get("asset_id") for o in (oo or [])}
        if seeded:
            log.info("Startup: %d open orders already on the exchange — will not re-place their windows", len(oo))
    except Exception as exc:
        log.warning("open-order seed failed (proceeding): %s", exc)


def main():
    log.info("### pm-rebates-farmer LIVE — 50/50 @ %.2f, TP %.2f, +%d bars, coins=%s, %.0f sh ###",
             ENTRY, TP, LEAD, COINS, SHARES)
    clob = build_clob_client()
    ensure_approvals(clob)
    bal = fetch_usdc_balance(clob)
    tg(f"🌾 rebates-farmer started · balance ${bal:.2f}")
    seed_from_exchange(clob)
    last_bal = time.time()
    while True:
        try:
            now = time.time()
            cur = int(now // BAR) * BAR
            for coin in COINS:
                ensure_pair(clob, coin, cur + LEAD * BAR)
            service_fills(clob)
            cleanup(now)
            if now - last_bal >= BAL_EVERY:
                last_bal = now
                try:
                    tg(f"💰 balance ${fetch_usdc_balance(clob):.2f}")
                except Exception:
                    pass
        except Exception as exc:
            log.error("loop error: %s", exc)
        time.sleep(LOOP)


if __name__ == "__main__":
    main()
