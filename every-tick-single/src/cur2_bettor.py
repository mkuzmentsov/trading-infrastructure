"""cur+2 50c bettor — a focused LIVE (capped) experiment, separate from the maker
fleet. Every 5m boundary it predicts the cur+2 bar's direction with the frozen
model and rests a 0.50 limit BUY on the predicted side of the cur+2 market, then
tracks whether it FILLS (pre-open) and whether it WINS. Answers the open question:
does the ~52% cur+2 edge convert to money at a 50c fill, or does adverse-selection
/ no-pre-open-volume kill it.

Gates (env): LIVE_TRADING=true AND DRY_RUN=false to place real orders; otherwise
it predicts + targets + logs but places nothing. Hard caps: LIVE_MAX_ORDER_USD,
LIVE_MAX_DAILY_LOSS_USD. One bet per target market. Events -> TRAINING_EVENT_LOG_PATH.
"""
from __future__ import annotations

import json
import math
import os
import time
import urllib.request

from config import DATA_API, DRY_RUN, TRAINING_EVENT_LOG_PATH, log

COIN = os.getenv("COIN", "sol").lower()
LIVE_TRADING = os.getenv("LIVE_TRADING", "false").lower() in ("true", "1", "yes")
HORIZON = int(os.getenv("CUR2_HORIZON", "2"))
BET_PRICE = float(os.getenv("CUR2_BET_PRICE", "0.50"))
NOTIONAL = min(float(os.getenv("QUOTE_NOTIONAL_USD", "5")), float(os.getenv("LIVE_MAX_ORDER_USD", "5")))
MAX_DAILY_LOSS = float(os.getenv("LIVE_MAX_DAILY_LOSS_USD", "50"))
MIN_SHARES = int(os.getenv("CUR2_MIN_SHARES", "5"))
SETTLE_BUFFER = 90          # secs after bar end before reading the outcome
POLL_SECS = 5

_real = LIVE_TRADING and not DRY_RUN     # place real orders only when both gates align


def _event(ev: str, **kw):
    rec = {"ev": ev, "t": round(time.time(), 2), "coin": COIN, **kw}
    log.info("%s  %s", ev, " ".join(f"{k}={v}" for k, v in kw.items()))
    if TRAINING_EVENT_LOG_PATH:
        try:
            with open(TRAINING_EVENT_LOG_PATH, "a") as f:
                f.write(json.dumps(rec) + "\n")
        except Exception:
            pass


def _gamma(params: dict):
    url = "https://gamma-api.polymarket.com/markets?" + "&".join(f"{k}={v}" for k, v in params.items())
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return json.loads(urllib.request.urlopen(req, timeout=10).read())


def market_tokens(ws: int):
    """(condition_id, up_token, down_token) for the cur+2 market, or None if not up yet."""
    try:
        d = _gamma({"slug": f"{COIN}-updown-5m-{ws}"})
        if not d:
            return None
        m = d[0]
        if m.get("closed"):
            return None
        toks = json.loads(m["clobTokenIds"])           # [UP, DOWN]
        return m.get("conditionId", ""), toks[0], toks[1]
    except Exception as exc:
        log.debug("market_tokens %s failed: %s", ws, exc)
        return None


def outcome_up(ws: int):
    """True/False once the market has resolved, else None."""
    try:
        d = _gamma({"slug": f"{COIN}-updown-5m-{ws}", "closed": "true"})
        if not d or not d[0].get("closed"):
            return None
        op = d[0]["outcomePrices"]
        op = json.loads(op) if isinstance(op, str) else op
        return str(op[0]) in ("1", "1.0")              # outcomes=[Up,Down]
    except Exception:
        return None


def main():
    clob = None
    if _real:
        from engine.clob import build_clob_client, ensure_approvals
        clob = build_clob_client()
        ensure_approvals(clob)
        log.info("cur2_bettor LIVE: coin=%s price=%.2f notional=$%.2f dailyLossCap=$%.2f",
                 COIN, BET_PRICE, NOTIONAL, MAX_DAILY_LOSS)
    else:
        log.info("cur2_bettor DRY (no real orders): coin=%s price=%.2f notional=$%.2f",
                 COIN, BET_PRICE, NOTIONAL)

    shares = max(MIN_SHARES, math.floor(NOTIONAL / BET_PRICE))
    open_bets: dict[int, dict] = {}     # target_ws -> bet
    settled: set[int] = set()
    day_pnl: dict[str, float] = {}
    halted = False

    from strategy import cur2_predictor

    while True:
        now = time.time()
        cur = int(now // 300) * 300
        target = cur + HORIZON * 300
        today = time.strftime("%Y-%m-%d", time.gmtime(now))

        # ---- 1. place a bet on the cur+2 target, once ----
        if not halted and target not in open_bets and target not in settled:
            info = market_tokens(target)
            p_up = cur2_predictor.predict(COIN)
            if info and p_up is not None:
                cond, up_tok, dn_tok = info
                side = "UP" if p_up >= 0.5 else "DOWN"
                token = up_tok if side == "UP" else dn_tok
                order_id, err = None, ""
                if _real:
                    try:
                        from engine.clob import place_bet
                        order_id = place_bet(clob, token, float(shares), BET_PRICE, cond)
                    except Exception as exc:
                        err = str(exc)[:200]
                else:
                    order_id = f"dry-{target}"
                open_bets[target] = {"side": side, "token": token, "cond": cond,
                                     "order_id": order_id, "p_up": round(p_up, 4),
                                     "shares": shares, "opened_secs_left": round(target - now, 0)}
                _event("CUR2_BET_PLACED", target=target, side=side, p_up=round(p_up, 4),
                       price=BET_PRICE, shares=shares, order=order_id or "FAILED",
                       secs_to_open=round(target - now), live=_real, err=err)

        # ---- 2. settle matured bets ----
        for t in list(open_bets):
            if now < t + 300 + SETTLE_BUFFER:
                continue
            bet = open_bets[t]
            oc = outcome_up(t)
            if oc is None:
                continue                        # not resolved yet, retry later
            filled = 0.0
            if _real and bet["order_id"]:
                try:
                    from engine.clob import fetch_order_status, cancel_order
                    st = fetch_order_status(clob, bet["order_id"]) or {}
                    filled = float(st.get("size_matched", st.get("matched", 0)) or 0)
                    cancel_order(clob, bet["order_id"])     # pull any unfilled remainder
                except Exception as exc:
                    log.debug("settle status/cancel failed: %s", exc)
            won = (oc and bet["side"] == "UP") or ((not oc) and bet["side"] == "DOWN")
            pnl = filled * ((1.0 if won else 0.0) - BET_PRICE)
            day_pnl[today] = day_pnl.get(today, 0.0) + pnl
            _event("CUR2_BET_SETTLE", target=t, side=bet["side"], p_up=bet["p_up"],
                   outcome="UP" if oc else "DOWN", filled=round(filled, 2), shares=bet["shares"],
                   won=won, pnl=round(pnl, 4), day_pnl=round(day_pnl[today], 4), live=_real)
            settled.add(t); open_bets.pop(t, None)

        # ---- 3. daily loss cap ----
        if not halted and -day_pnl.get(today, 0.0) >= MAX_DAILY_LOSS:
            halted = True
            _event("CUR2_HALT", reason="daily_loss_cap", day_pnl=round(day_pnl[today], 4))
            if _real:
                from engine.clob import cancel_order
                for b in open_bets.values():
                    if b["order_id"]:
                        try: cancel_order(clob, b["order_id"])
                        except Exception: pass

        time.sleep(POLL_SECS)


if __name__ == "__main__":
    main()
