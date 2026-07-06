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
    fetch_usdc_balance, ensure_approvals, cancel_order,
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


def track_window(coin: str, window_ts: int):
    """Register a window for servicing (does not place yet)."""
    key = (coin, window_ts)
    if key in state:
        return
    toks = market_for(coin, window_ts)
    if not toks:
        return
    state[key] = {"tokens": toks, "end": window_ts + BAR, "ws": window_ts, "coin": coin,
                  "up": {"buy": None, "tp": None, "filled": 0.0, "tp_done": False},
                  "down": {"buy": None, "tp": None, "filled": 0.0, "tp_done": False}}


def maintain_entries(clob, now: float):
    """Ensure BOTH 0.50 legs are resting on every tracked window — RETRY every
    loop until each rests (a leg that would cross is post-only-rejected now but
    becomes placeable as the book oscillates around 0.50). Never gives up while
    the window is open."""
    for (coin, ws), rec in state.items():
        if now > rec["end"]:
            continue
        for side_name, tok in (("up", rec["tokens"][0]), ("down", rec["tokens"][1])):
            s = rec[side_name]
            if s["buy"] or s["filled"] >= SHARES:
                continue  # already resting or filled — leave it
            oid = place_limit_order(clob, tok, "BUY", SHARES, ENTRY)
            if oid:
                s["buy"] = oid
                log.info("PLACED %s %s BUY %.0f @ %.2f  slug=%s-updown-5m-%d  order=%s",
                         coin, side_name.upper(), SHARES, ENTRY, coin, ws, oid)
            # else: crossed/failed — retry next loop (no give-up)


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
                new = matched - s["filled"]
                s["filled"] = matched
                log.info("FILLED %s %s %.2f @ %.2f  (total %.2f)  slug=%s-updown-5m-%d",
                         coin, side_name.upper(), new, ENTRY, matched, coin, ws)
                try:
                    tg(f"✅ FILLED {coin.upper()} {side_name.upper()} {new:.0f} @ {ENTRY:.2f} · "
                       f"{coin}-updown-5m-{ws}")
                except Exception:
                    pass
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


def cancel_stale_entries(clob):
    """No persistent storage → on (re)start, cancel our open BUY entries so we
    don't accumulate DUPLICATE resting orders across restarts. SELL take-profits
    are left resting (they cover already-filled positions). Fresh entries are
    then placed by the normal loop."""
    try:
        from py_clob_client_v2.clob_types import OpenOrderParams
        oo = clob.get_open_orders(OpenOrderParams()) or []
        buys = [o for o in oo if str(o.get("side", "")).upper() == "BUY"]
        for o in buys:
            oid = o.get("id") or o.get("orderID")
            if oid:
                cancel_order(clob, oid)
        log.info("Startup: cancelled %d stale BUY entries (%d open orders total, TPs kept)",
                 len(buys), len(oo))
    except Exception as exc:
        log.warning("startup cancel failed (proceeding): %s", exc)


def main():
    log.info("### pm-rebates-farmer LIVE — 50/50 @ %.2f, TP %.2f, +%d bars, coins=%s, %.0f sh ###",
             ENTRY, TP, LEAD, COINS, SHARES)
    clob = build_clob_client()
    ensure_approvals(clob)
    bal = fetch_usdc_balance(clob)
    tg(f"🌾 rebates-farmer started · balance ${bal:.2f}")
    cancel_stale_entries(clob)
    last_bal = time.time()
    while True:
        try:
            now = time.time()
            cur = int(now // BAR) * BAR
            for coin in COINS:
                track_window(coin, cur + LEAD * BAR)
            maintain_entries(clob, now)   # place/retry both legs until they rest
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
