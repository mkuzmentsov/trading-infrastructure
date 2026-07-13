"""fav_taker — near-locked-favorite TAKER for the crypto 5m UpDown markets.

Rationale (measured, see LEADERBOARD_THIERRAX1_ANALYSIS.md): the cheap-tail
"overshoot" edge does NOT exist — these markets are well-calibrated. The one real
static edge is the mirror image: the FAVORITE side is slightly underpriced, and a
skilled taker (@thierrax1) makes money buying the *near-locked* winner when the
orderbook ask still lags its true (near-1) probability.

This bot does exactly that. DURING the live 5m bar it:
  1. estimates true P(favorite wins) from the underlying's intra-bar move vs the
     volatility of the move still to come:  z = lead / (sigma * sqrt(t_left)),
     true_up = Phi(z);  fav_true = max(true_up, 1-true_up).
  2. reads the favorite token's best ASK from the CLOB.
  3. taker-buys (FAK) the favorite iff it is underpriced by >= FAV_MIN_EDGE and
     inside the price/time gates. One buy per bar; holds to resolution (auto-redeems).

This is the OPPOSITE design to cur2_bettor (which passively rests at 0.50). It is a
liquidity-TAKER reacting inside the bar.

Gates (env): LIVE_TRADING=true AND DRY_RUN=false to place real orders; otherwise it
evaluates + logs (paper) and places nothing. Caps: LIVE_MAX_ORDER_USD,
LIVE_MAX_DAILY_LOSS_USD. Events -> TRAINING_EVENT_LOG_PATH.
"""
from __future__ import annotations

import json
import math
import os
import time
import urllib.request

from config import DRY_RUN, TRAINING_EVENT_LOG_PATH, log

COIN = os.getenv("COIN", "sol").lower()
LIVE_TRADING = os.getenv("LIVE_TRADING", "false").lower() in ("true", "1", "yes")
NOTIONAL = min(float(os.getenv("QUOTE_NOTIONAL_USD", "5")), float(os.getenv("LIVE_MAX_ORDER_USD", "5")))
MAX_DAILY_LOSS = float(os.getenv("LIVE_MAX_DAILY_LOSS_USD", "50"))

# ── decision gates (all tunable) ─────────────────────────────────────────────
MIN_PRICE = float(os.getenv("FAV_MIN_PRICE", "0.80"))   # don't buy coin-flips
MAX_PRICE = float(os.getenv("FAV_MAX_PRICE", "0.97"))   # thin edge above this; also the FAK price cap
MIN_TRUE = float(os.getenv("FAV_MIN_TRUE", "0.90"))     # only near-locked favorites
MIN_EDGE = float(os.getenv("FAV_MIN_EDGE", "0.03"))     # fav_true - ask must clear this (covers fee/slip)
MIN_TLEFT = int(os.getenv("FAV_MIN_TLEFT", "15"))       # secs left: not too late (settle-buffer safety)
MAX_TLEFT = int(os.getenv("FAV_MAX_TLEFT", "180"))      # secs left: not too early (move not yet decisive)
# Polymarket taker fee on 5m crypto markets: fee = shares * rate * p * (1-p), USDC at match
# (live CLOB reports taker_base_fee=1000bps on these markets; makers pay nothing).
FEE_RATE = float(os.getenv("FAV_TAKER_FEE_RATE", "0.10"))


def taker_fee_ps(price: float) -> float:
    """taker fee per share at `price`."""
    return FEE_RATE * price * (1.0 - price)

SETTLE_BUFFER = 90
POLL_SECS = 3
_BINANCE = ["https://api.binance.com", "https://data-api.binance.vision"]
_real = LIVE_TRADING and not DRY_RUN


def _event(ev: str, **kw):
    rec = {"ev": ev, "t": round(time.time(), 2), "coin": COIN, **kw}
    log.info("%s  %s", ev, " ".join(f"{k}={v}" for k, v in kw.items()))
    if TRAINING_EVENT_LOG_PATH:
        try:
            with open(TRAINING_EVENT_LOG_PATH, "a") as f:
                f.write(json.dumps(rec) + "\n")
        except Exception:
            pass


def _http(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return json.loads(urllib.request.urlopen(req, timeout=10).read())


def _gamma(params: dict):
    return _http("https://gamma-api.polymarket.com/markets?" + "&".join(f"{k}={v}" for k, v in params.items()))


def market_tokens(ws: int):
    """(condition_id, up_token, down_token) for the live bar market, or None."""
    try:
        d = _gamma({"slug": f"{COIN}-updown-5m-{ws}"})
        if not d or d[0].get("closed"):
            return None
        toks = json.loads(d[0]["clobTokenIds"])         # [UP, DOWN]
        return d[0].get("conditionId", ""), toks[0], toks[1]
    except Exception as exc:
        log.debug("market_tokens %s: %s", ws, exc)
        return None


def outcome_up(ws: int):
    try:
        d = _gamma({"slug": f"{COIN}-updown-5m-{ws}", "closed": "true"})
        if not d or not d[0].get("closed"):
            return None
        op = d[0]["outcomePrices"]
        op = json.loads(op) if isinstance(op, str) else op
        return str(op[0]) in ("1", "1.0")
    except Exception:
        return None


def best_ask(token_id: str):
    """CLOB best ask (what we'd pay to BUY), or None."""
    for _ in range(2):
        try:
            r = _http(f"https://clob.polymarket.com/price?token_id={token_id}&side=BUY")
            return float(r.get("price"))
        except Exception:
            time.sleep(0.3)
    return None


_kl_cache = {"t": 0, "rows": None}


def klines1m(limit: int = 40):
    """recent 1m klines (openTime, open, close); cached ~20s."""
    now = time.time()
    if _kl_cache["rows"] and now - _kl_cache["t"] < 20:
        return _kl_cache["rows"]
    sym = f"{COIN.upper()}USDT"
    for base in _BINANCE:
        try:
            raw = _http(f"{base}/api/v3/klines?symbol={sym}&interval=1m&limit={limit}")
            rows = [(int(k[0]) // 1000, float(k[1]), float(k[4])) for k in raw]
            _kl_cache.update(t=now, rows=rows)
            return rows
        except Exception:
            continue
    return _kl_cache["rows"]


def spot_price():
    sym = f"{COIN.upper()}USDT"
    for base in _BINANCE:
        try:
            return float(_http(f"{base}/api/v3/ticker/price?symbol={sym}")["price"])
        except Exception:
            continue
    return None


def sigma_per_sec(rows):
    """per-second stdev of log returns, estimated from 1m closes."""
    if not rows or len(rows) < 10:
        return None
    rets = []
    for i in range(1, len(rows)):
        p0, p1 = rows[i - 1][2], rows[i][2]
        if p0 > 0 and p1 > 0:
            rets.append(math.log(p1 / p0))
    if len(rets) < 8:
        return None
    m = sum(rets) / len(rets)
    var = sum((r - m) ** 2 for r in rets) / (len(rets) - 1)
    sigma_1m = math.sqrt(var)
    return sigma_1m / math.sqrt(60.0)          # per-second


def norm_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def evaluate(ws: int):
    """Return (fav_side, fav_token, fav_true, ask, edge, lead_bps, t_left) or None."""
    rows = klines1m()
    if not rows:
        return None
    bar_open = next((o for (t, o, c) in rows if t == ws), None)
    if bar_open is None:                          # bar's 1m open not available yet
        return None
    cur = spot_price()
    sig = sigma_per_sec(rows)
    if cur is None or not sig:
        return None
    t_left = ws + 300 - time.time()
    if t_left <= 0:
        return None
    lead = (cur - bar_open) / bar_open
    z = lead / (sig * math.sqrt(t_left)) if t_left > 0 else 0.0
    true_up = norm_cdf(z)
    fav_up = true_up >= 0.5
    fav_true = true_up if fav_up else 1 - true_up
    info = market_tokens(ws)
    if not info:
        return None
    _, up_tok, dn_tok = info
    fav_side = "UP" if fav_up else "DOWN"
    fav_token = up_tok if fav_up else dn_tok
    ask = best_ask(fav_token)
    if ask is None:
        return None
    edge = fav_true - ask - taker_fee_ps(ask)      # net of taker fee
    return fav_side, fav_token, info[0], round(fav_true, 4), round(ask, 4), round(edge, 4), round(lead * 1e4, 1), int(t_left)


def main():
    clob = None
    if _real:
        from engine.clob import build_clob_client, ensure_approvals
        clob = build_clob_client()
        ensure_approvals(clob)
    log.info("fav_taker %s: coin=%s notional=$%.2f gates[price %.2f-%.2f true>=%.2f edge>=%.2f tleft %d-%ds] dailyCap=$%.2f",
             "LIVE" if _real else "PAPER", COIN, NOTIONAL, MIN_PRICE, MAX_PRICE, MIN_TRUE, MIN_EDGE, MIN_TLEFT, MAX_TLEFT, MAX_DAILY_LOSS)

    open_bets: dict[int, dict] = {}     # bar_ws -> bet
    acted: set[int] = set()             # bars we've already decided (bought or gave up)
    settled: set[int] = set()
    best_seen: dict[int, float] = {}    # bar_ws -> best edge seen (for FAV_NOBET telemetry)
    day_pnl: dict[str, float] = {}
    halted = False

    while True:
        now = time.time()
        cur = int(now // 300) * 300         # the live bar opens at `cur`
        today = time.strftime("%Y-%m-%d", time.gmtime(now))

        # ---- 1. evaluate the live bar, act at most once ----
        if not halted and cur not in acted and cur not in settled:
            ev = evaluate(cur)
            if ev:
                fav_side, fav_token, cond, fav_true, ask, edge, lead_bps, t_left = ev
                best_seen[cur] = max(best_seen.get(cur, -1), edge)
                fire = (ask <= MAX_PRICE and ask >= MIN_PRICE and fav_true >= MIN_TRUE
                        and edge >= MIN_EDGE and MIN_TLEFT <= t_left <= MAX_TLEFT)
                if fire:
                    shares = max(5.0, math.floor(NOTIONAL / ask))
                    order_id, matched, err = None, False, ""
                    entry = ask
                    if _real:
                        try:
                            from engine.clob import place_market_buy
                            order_id, matched = place_market_buy(clob, fav_token, float(shares), MAX_PRICE, cond)
                        except Exception as exc:
                            err = str(exc)[:200]
                    else:
                        order_id, matched = f"paper-{cur}", True
                    open_bets[cur] = {"side": fav_side, "token": fav_token, "entry": entry,
                                      "fav_true": fav_true, "shares": shares, "order_id": order_id}
                    acted.add(cur)
                    _event("FAV_BET_PLACED", bar=cur, side=fav_side, entry=entry, fav_true=fav_true,
                           edge=edge, lead_bps=lead_bps, t_left=t_left, shares=shares,
                           order=order_id or "FAILED", matched=matched, live=_real, err=err)
                # give up on this bar once it's too late to act
                elif t_left < MIN_TLEFT:
                    acted.add(cur)
                    _event("FAV_NOBET", bar=cur, best_edge=round(best_seen.get(cur, -1), 4),
                           last_true=fav_true, last_ask=ask, lead_bps=lead_bps, live=_real)

        # ---- 2. settle matured bets ----
        for t in list(open_bets):
            if now < t + 300 + SETTLE_BUFFER:
                continue
            bet = open_bets[t]
            oc = outcome_up(t)
            if oc is None:
                continue
            filled = bet["shares"]
            if _real and bet["order_id"]:
                try:
                    from engine.clob import fetch_order_status
                    st = fetch_order_status(clob, bet["order_id"]) or {}
                    filled = float(st.get("size_matched", st.get("matched", bet["shares"])) or 0)
                except Exception as exc:
                    log.debug("settle status: %s", exc)
            won = (oc and bet["side"] == "UP") or ((not oc) and bet["side"] == "DOWN")
            pnl = filled * ((1.0 if won else 0.0) - bet["entry"] - taker_fee_ps(bet["entry"]))
            day_pnl[today] = day_pnl.get(today, 0.0) + pnl
            _event("FAV_BET_SETTLE", bar=t, side=bet["side"], entry=bet["entry"], fav_true=bet["fav_true"],
                   outcome="UP" if oc else "DOWN", filled=round(filled, 2), won=won,
                   pnl=round(pnl, 4), day_pnl=round(day_pnl[today], 4), live=_real)
            settled.add(t); open_bets.pop(t, None)

        # ---- 3. daily loss cap ----
        if not halted and -day_pnl.get(today, 0.0) >= MAX_DAILY_LOSS:
            halted = True
            _event("FAV_HALT", reason="daily_loss_cap", day_pnl=round(day_pnl[today], 4))

        time.sleep(POLL_SECS)


if __name__ == "__main__":
    main()
