"""fav_taker — near-locked-favorite TAKER for the crypto UpDown markets.

Rationale (measured, see LEADERBOARD_THIERRAX1_ANALYSIS.md): the cheap-tail
"overshoot" edge does NOT exist — these markets are well-calibrated. The one real
static edge is the mirror image: the FAVORITE side is slightly underpriced, and a
skilled taker (@thierrax1) makes money buying the *near-locked* winner when the
orderbook ask still lags its true (near-1) probability.

This bot does exactly that. DURING the live bar it:
  1. estimates true P(favorite wins) from the underlying's intra-bar move vs the
     volatility of the move still to come:  z = lead / (sigma * sqrt(t_left)),
     true_up = Phi(z);  fav_true = max(true_up, 1-true_up).
  2. reads the favorite token's best ASK.
  3. taker-buys (FAK) the favorite iff a FAV_POCKETS gate passes.
     One buy per bar; holds to resolution (auto-redeems).

Execution paths (FAST_EXEC env, default true):
  fast    execution.runner.TakerRunner — event-driven: Binance aggTrade WS is
          the signal, CLOB market WS is the book, orders are presigned at bar
          start and fired over a warm session. Signal→order ≈ 200-400ms.
  legacy  3s REST polling loop (klines + ticker + gamma + /price ≈ 1.15s
          sequential) — kept for fallback/backtest parity. Signal→order 2-4.5s.

Gates (env): LIVE_TRADING=true AND DRY_RUN=false to place real orders; otherwise
paper (fills assumed at the observed ask). Caps: LIVE_MAX_ORDER_USD,
LIVE_MAX_DAILY_LOSS_USD. Events -> TRAINING_EVENT_LOG_PATH.
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import time
import urllib.request

from config import BAR_SECONDS, DRY_RUN, FAST_EXEC, TRAINING_EVENT_LOG_PATH, log

COIN = os.getenv("COIN", "sol").lower()
LIVE_TRADING = os.getenv("LIVE_TRADING", "false").lower() in ("true", "1", "yes")
NOTIONAL = min(float(os.getenv("QUOTE_NOTIONAL_USD", "5")), float(os.getenv("LIVE_MAX_ORDER_USD", "5")))
MAX_DAILY_LOSS = float(os.getenv("LIVE_MAX_DAILY_LOSS_USD", "50"))

# ── decision gates ───────────────────────────────────────────────────────────
# FAV_POCKETS: JSON list of gate pockets; the bet fires when ANY pocket passes.
#   {"p_lo","p_hi": ask band; "tl_lo","tl_hi": t_left secs; "edge": min NET edge
#    (fav_true − ask − taker fee); "true": min fav_true (0 = off);
#    "mom": 1 → require the last-30s move aligned with the favorite and calm
#    (0.2 ≤ mom_z ≤ 1.3 — violent aligned moves snap back per 30d calibration)}
# Unset → single pocket from the legacy FAV_* envs (backward compatible).
MIN_PRICE = float(os.getenv("FAV_MIN_PRICE", "0.80"))   # don't buy coin-flips
MAX_PRICE = float(os.getenv("FAV_MAX_PRICE", "0.97"))   # thin edge above this; also the FAK price cap
MIN_TRUE = float(os.getenv("FAV_MIN_TRUE", "0.90"))     # only near-locked favorites
MIN_EDGE = float(os.getenv("FAV_MIN_EDGE", "0.03"))     # NET edge (fee included) must clear this
MIN_TLEFT = int(os.getenv("FAV_MIN_TLEFT", "15"))       # secs left: not too late (settle-buffer safety)
MAX_TLEFT = int(os.getenv("FAV_MAX_TLEFT", "180"))      # secs left: not too early (move not yet decisive)
_pockets_env = os.getenv("FAV_POCKETS", "").strip()
if _pockets_env:
    POCKETS = json.loads(_pockets_env)
else:
    POCKETS = [{"p_lo": MIN_PRICE, "p_hi": MAX_PRICE, "tl_lo": MIN_TLEFT, "tl_hi": MAX_TLEFT,
                "edge": MIN_EDGE, "true": MIN_TRUE, "mom": 0}]
MOM_ALIGN_LO = float(os.getenv("FAV_MOM_ALIGN_LO", "0.2"))
MOM_ALIGN_HI = float(os.getenv("FAV_MOM_ALIGN_HI", "1.3"))
# Polymarket taker fee on 5m crypto markets: fee = shares * rate * p * (1-p), USDC at match
# (live CLOB reports taker_base_fee=1000bps on these markets; makers pay nothing).
FEE_RATE = float(os.getenv("FAV_TAKER_FEE_RATE", "0.10"))
# knife-edge floor: bars ending within ~2bps of open are label coin-flips (win%
# measured 63% vs 92% overall on 30d Binance 1s) — don't fire on micro-leads.
MIN_LEAD_BPS = float(os.getenv("FAV_MIN_LEAD_BPS", "4"))
# BTC's 1m-sigma understates short-horizon vol → Phi(z) overconfident by ~2.5pp
# in the firing zone (30d 1s calibration). Shrink z by k(t_left); alts are fine.
_BTC_Z_SHRINK = {60: 1.24, 120: 1.05, 180: 1.03, 10 ** 9: 1.02}


def z_shrink(t_left: float) -> float:
    if COIN != "btc":
        return 1.0
    for cap in sorted(_BTC_Z_SHRINK):
        if t_left < cap:
            return _BTC_Z_SHRINK[cap]
    return 1.0


def taker_fee_ps(price: float) -> float:
    """taker fee per share at `price`."""
    return FEE_RATE * price * (1.0 - price)

SETTLE_BUFFER = 90
POLL_SECS = 3
_BINANCE = ["https://api.binance.com", "https://data-api.binance.vision"]
_real = LIVE_TRADING and not DRY_RUN


from execution.events import EventLog

_event_log = EventLog(TRAINING_EVENT_LOG_PATH)


def _event(ev: str, **kw):
    _event_log.write(ev, coin=COIN, **kw)


def _http(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return json.loads(urllib.request.urlopen(req, timeout=10).read())


def _gamma(params: dict):
    return _http("https://gamma-api.polymarket.com/markets?" + "&".join(f"{k}={v}" for k, v in params.items()))


def _slug(ws: int) -> str:
    return f"{COIN}-updown-{BAR_SECONDS // 60}m-{ws}"


def market_tokens(ws: int):
    """(condition_id, up_token, down_token) for the live bar market, or None."""
    try:
        d = _gamma({"slug": _slug(ws)})
        if not d or d[0].get("closed"):
            return None
        toks = json.loads(d[0]["clobTokenIds"])         # [UP, DOWN]
        return d[0].get("conditionId", ""), toks[0], toks[1]
    except Exception as exc:
        log.debug("market_tokens %s: %s", ws, exc)
        return None


def outcome_up(ws: int):
    try:
        d = _gamma({"slug": _slug(ws), "closed": "true"})
        if not d or not d[0].get("closed"):
            return None
        op = d[0]["outcomePrices"]
        op = json.loads(op) if isinstance(op, str) else op
        return str(op[0]) in ("1", "1.0")
    except Exception:
        return None


def norm_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def pocket_match(ask: float, t_left: float, edge: float, fav_true: float,
                 mom_fav: float | None):
    """Index of the first passing pocket, or None. Pure — shared by both paths.

    "true"/"true_hi" bound the MODEL's probability for the fired side. The
    upper bound matters for tail pockets: model≈0.50 means "no information"
    (lead≈0 knife-edge — measured degenerate on xrp live 2026-07-16: 0/13 at
    constant 0.50) and ≈1.0 is the quiet-tape sigma-collapse glitch. A tail
    is only a trade when the model ACTIVELY asserts partial life."""
    for i, p in enumerate(POCKETS):
        if not (p["p_lo"] <= ask <= p["p_hi"] and p["tl_lo"] <= t_left <= p["tl_hi"]):
            continue
        if edge < p["edge"] or fav_true < p.get("true", 0.0):
            continue
        if fav_true > p.get("true_hi", 1.0):
            continue
        if p.get("mom"):
            if mom_fav is None or not (MOM_ALIGN_LO <= mom_fav <= MOM_ALIGN_HI):
                continue
        return i
    return None


def pocket_shares(pocket: dict) -> float:
    """Deterministic per-pocket size so the order can be presigned at bar
    start: sized at the pocket's price cap (may be ≤ the legacy ask-based
    size by at most 2 shares; speed > the last fractional share)."""
    return max(5.0, math.floor(NOTIONAL / pocket["p_hi"]))


MIN_TL_LO = min(p["tl_lo"] for p in POCKETS)


# ═════════════════════════════ fast path ═════════════════════════════════════
class FavStrategy:
    """Pocket-gated favorite taker on the event-driven TakerRunner."""

    def __init__(self) -> None:
        self.runner = None
        self.open_bets: dict[int, dict] = {}
        self.acted: set[int] = set()
        self.settled: set[int] = set()
        self.best_seen: dict[int, float] = {}
        self.day_pnl: dict[str, float] = {}
        self.halted = False

    def bind(self, runner) -> None:
        self.runner = runner

    # one presigned FAK per pocket per side, built at bar start
    def presign_requests(self, ctx):
        reqs = []
        for i, p in enumerate(POCKETS):
            size = pocket_shares(p)
            if ctx.up_token:
                reqs.append((f"p{i}-UP", ctx.up_token, p["p_hi"], size))
            if ctx.down_token:
                reqs.append((f"p{i}-DOWN", ctx.down_token, p["p_hi"], size))
        return reqs

    async def on_tick(self, ctx) -> None:
        if self.halted or ctx.ws in self.acted or ctx.ws in self.settled:
            return
        if ctx.bar_open is None or not ctx.sigma_ps or ctx.spot <= 0:
            return
        if ctx.spot_age > 5.0:            # stale feed → no decisions
            return
        t0 = time.time()
        lead = (ctx.spot - ctx.bar_open) / ctx.bar_open
        t_left = ctx.t_left
        if t_left <= 0:
            return
        z = lead / (ctx.sigma_ps * math.sqrt(t_left))
        true_up = norm_cdf(z / z_shrink(t_left))
        fav_up = true_up >= 0.5
        fav_true = true_up if fav_up else 1 - true_up
        mom_z_up = None
        if ctx.ret_30s is not None and ctx.sigma_ps:
            mom_z_up = ctx.ret_30s / (ctx.sigma_ps * math.sqrt(30.0))

        # evaluate BOTH sides, favorite first: fav/mom pockets (p_lo >= ~0.5)
        # only ever match the favorite; tail pockets (p_hi <= ~0.1) only match
        # the underdog when its ask lags the model's residual probability.
        pocket = None
        fav_side, ask, edge, fav_true_out, mom_fav = "UP", 1.0, None, fav_true, None
        sides = [("UP", true_up), ("DOWN", 1 - true_up)]
        sides.sort(key=lambda s: -s[1])
        for side, side_true in sides:
            s_ask = ctx.up_ask if side == "UP" else ctx.down_ask
            if not (ctx.book_ready and 0 < s_ask < 1):
                continue
            if MIN_LEAD_BPS and abs(lead) * 1e4 < MIN_LEAD_BPS:
                continue
            s_edge = side_true - s_ask - taker_fee_ps(s_ask)
            s_mom = None if mom_z_up is None else (mom_z_up if side == "UP" else -mom_z_up)
            if side_true >= 0.5:
                self.best_seen[ctx.ws] = max(self.best_seen.get(ctx.ws, -1), s_edge)
            pk = pocket_match(s_ask, t_left, s_edge, side_true, s_mom)
            if pk is not None:
                pocket, fav_side, ask, edge = pk, side, s_ask, s_edge
                fav_true_out, mom_fav = side_true, s_mom
                break
            if side_true >= 0.5:      # keep favorite values for NOBET telemetry
                fav_side, ask, edge, fav_true_out, mom_fav = side, s_ask, s_edge, side_true, s_mom
        fav_true = fav_true_out
        fav_up = fav_side == "UP"

        if pocket is not None:
            pk = POCKETS[pocket]
            shares = pocket_shares(pk)
            key = f"p{pocket}-{fav_side}"
            fav_token = ctx.up_token if fav_up else ctx.down_token
            t_decide = time.time()
            presigned = self.runner.exec.has_presigned(key)
            err = ""
            if presigned:
                order_id, matched, post_ms, avg_px, fill_qty = \
                    await self.runner.exec.fire_presigned(key)
                sign_ms = 0.0
            else:
                try:
                    order_id, matched, sign_ms, post_ms, avg_px, fill_qty = \
                        await self.runner.exec.fire_direct(fav_token, pk["p_hi"], shares)
                except Exception as exc:
                    order_id, matched, sign_ms, post_ms, avg_px, fill_qty = \
                        None, False, 0.0, 0.0, None, None
                    err = str(exc)[:200]
            # live: settle on ACTUAL avg fill price/size (FAK is dollar-capped;
            # price improvement returns more shares at a lower avg than quoted)
            fill_px = avg_px if avg_px else ask
            # paper: fill CUMULATIVELY across visible ask levels <= the FAK cap
            # (what live actually sweeps — top-level-only capping understated it)
            ask_size = ctx.up_ask_size if fav_up else ctx.down_ask_size
            depth = ctx.up_depth if fav_up else ctx.down_depth
            depth_at_cap = sum(sz for px, sz in depth.items() if px <= pk["p_hi"])
            if not _real:
                levels = sorted((px, sz) for px, sz in depth.items() if px <= pk["p_hi"])
                if levels:
                    want = shares; got = 0.0; cost = 0.0
                    for px_l, sz_l in levels:
                        take = min(want - got, sz_l)
                        got += take; cost += take * px_l
                        if got >= want: break
                    if got > 0:
                        # ladder can still lag the freshest top print — never
                        # fill LESS than the live top level offers
                        top_fill = min(shares, ask_size) if ask_size else 0
                        if top_fill > got:
                            fill_qty, fill_px = top_fill, ask
                        else:
                            fill_qty, fill_px = got, cost / got
                elif ask_size and ask_size > 0:
                    fill_qty = min(shares, ask_size)
            self.open_bets[ctx.ws] = {"side": fav_side, "token": fav_token, "entry": ask,
                                      "cap": pk["p_hi"],
                                      "fill_px": fill_px, "fill_qty": fill_qty,
                                      "fav_true": round(fav_true, 4), "shares": shares,
                                      "order_id": order_id}
            self.acted.add(ctx.ws)
            signal_age_ms = (t_decide - ctx.signal_ts) * 1000.0 if ctx.signal_ts else -1
            _event("FAV_BET_PLACED", bar=ctx.ws, side=fav_side, entry=round(ask, 4),
                   ask_size=round(ask_size, 1) if ask_size else 0,
                   depth_at_cap=round(depth_at_cap, 1),
                   fill_px=round(fill_px, 4), fill_qty=None if fill_qty is None else round(fill_qty, 2),
                   fav_true=round(fav_true, 4), edge=round(edge, 4),
                   lead_bps=round(lead * 1e4, 1), t_left=int(t_left),
                   mom_z=None if mom_fav is None else round(mom_fav, 2), pocket=pocket,
                   shares=shares, order=order_id or "FAILED", matched=matched,
                   live=_real, err=err)
            from core.binance_ws import binance_state
            _event("EXEC_TIMING", bar=ctx.ws, wake_source=ctx.wake_source,
                   signal_age_ms=round(signal_age_ms, 1),
                   decide_ms=round((t_decide - t0) * 1000.0, 2),
                   sign_ms=round(sign_ms, 1), post_ms=round(post_ms, 1),
                   presigned=presigned,
                   binance_delay_ewma_ms=round(binance_state.delay_ewma_ms, 1))
        elif t_left < MIN_TL_LO:
            self.acted.add(ctx.ws)
            _event("FAV_NOBET", bar=ctx.ws, best_edge=round(self.best_seen.get(ctx.ws, -1), 4),
                   last_true=round(fav_true, 4), last_ask=round(ask, 4),
                   lead_bps=round(lead * 1e4, 1),
                   mom_z=None if mom_fav is None else round(mom_fav, 2), live=_real)

    async def settle_loop(self) -> None:
        while True:
            await asyncio.sleep(5.0)
            now = time.time()
            today = time.strftime("%Y-%m-%d", time.gmtime(now))
            try:
                for t in list(self.open_bets):
                    if now < t + BAR_SECONDS + SETTLE_BUFFER:
                        continue
                    bet = self.open_bets[t]
                    oc = await asyncio.to_thread(outcome_up, t)
                    if oc is None:
                        continue
                    filled = bet.get("fill_qty") or bet["shares"]
                    _gtc = os.getenv("FAV_ORDER_TYPE", "fak").lower() == "gtc"
                    if _real and bet["order_id"] and (_gtc or not bet.get("fill_qty")):
                        try:
                            from engine.clob import fetch_order_status
                            st = await asyncio.to_thread(
                                fetch_order_status, self.runner.exec.clob, bet["order_id"]) or {}
                            filled = float(st.get("size_matched", st.get("matched", bet["shares"])) or 0)
                        except Exception as exc:
                            log.debug("settle status: %s", exc)
                    px = bet.get("fill_px", bet["entry"])
                    won = (oc and bet["side"] == "UP") or ((not oc) and bet["side"] == "DOWN")
                    crossed = min(filled, bet.get("fill_qty") or filled)
                    resting = max(0.0, filled - crossed)   # late GTC maker fills: cap price, NO fee
                    pnl = (crossed * ((1.0 if won else 0.0) - px - taker_fee_ps(px))
                           + resting * ((1.0 if won else 0.0) - bet.get("cap", px)))
                    self.day_pnl[today] = self.day_pnl.get(today, 0.0) + pnl
                    _event("FAV_BET_SETTLE", bar=t, side=bet["side"], entry=bet["entry"],
                           fill_px=round(px, 4), fav_true=bet["fav_true"],
                           outcome="UP" if oc else "DOWN",
                           filled=round(filled, 2), won=won, pnl=round(pnl, 4),
                           day_pnl=round(self.day_pnl[today], 4), live=_real)
                    self.settled.add(t)
                    self.open_bets.pop(t, None)
                if not self.halted and -self.day_pnl.get(today, 0.0) >= MAX_DAILY_LOSS:
                    self.halted = True
                    _event("FAV_HALT", reason="daily_loss_cap",
                           day_pnl=round(self.day_pnl[today], 4))
            except Exception as exc:
                log.exception("settle loop: %s", exc)


def main_fast():
    from execution.runner import TakerRunner
    log.info("fav_taker %s FAST: coin=%s notional=$%.2f pockets=%s dailyCap=$%.2f",
             "LIVE" if _real else "PAPER", COIN, NOTIONAL, json.dumps(POCKETS), MAX_DAILY_LOSS)
    runner = TakerRunner(FavStrategy(), live=_real, event_logger=_event)
    asyncio.run(runner.run())


# ═════════════════════════════ legacy path ═══════════════════════════════════
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


_px_hist: list[tuple[float, float]] = []    # (ts, spot) — for 30s momentum


def _momentum_z(now: float, cur: float, bar_open: float, sig: float) -> float | None:
    """sigma-scaled last-30s move; None until 30s of history exists."""
    _px_hist.append((now, cur))
    while _px_hist and now - _px_hist[0][0] > 90:
        _px_hist.pop(0)
    if not sig:
        return None
    # sample closest to 30s back, accepted within [26, 34]s
    cands = [(t, p) for (t, p) in _px_hist if 26 <= now - t <= 34]
    if not cands:
        return None
    _, p30 = cands[0]
    return ((cur - p30) / bar_open) / (sig * math.sqrt(30.0))


def evaluate(ws: int):
    """Return (fav_side, fav_token, cond, fav_true, ask, edge_net, lead_bps,
    t_left, mom_z, pocket_idx|None) or None when no decision possible."""
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
    now = time.time()
    t_left = ws + BAR_SECONDS - now
    if t_left <= 0:
        return None
    mom_z_up = _momentum_z(now, cur, bar_open, sig)   # signed toward UP
    lead = (cur - bar_open) / bar_open
    if abs(lead) * 1e4 < MIN_LEAD_BPS:
        return None
    z = lead / (sig * math.sqrt(t_left)) if t_left > 0 else 0.0
    true_up = norm_cdf(z / z_shrink(t_left))
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
    edge = fav_true - ask - taker_fee_ps(ask)      # NET of taker fee
    # favorite-signed momentum: positive = move continuing toward the favorite
    mom_fav = None if mom_z_up is None else (mom_z_up if fav_up else -mom_z_up)
    pocket = pocket_match(ask, t_left, edge, fav_true, mom_fav)
    return (fav_side, fav_token, info[0], round(fav_true, 4), round(ask, 4), round(edge, 4),
            round(lead * 1e4, 1), int(t_left), None if mom_fav is None else round(mom_fav, 2), pocket)


def main_legacy():
    clob = None
    if _real:
        from engine.clob import build_clob_client, ensure_approvals
        clob = build_clob_client()
        ensure_approvals(clob)
    log.info("fav_taker %s: coin=%s notional=$%.2f pockets=%s dailyCap=$%.2f",
             "LIVE" if _real else "PAPER", COIN, NOTIONAL, json.dumps(POCKETS), MAX_DAILY_LOSS)

    open_bets: dict[int, dict] = {}     # bar_ws -> bet
    acted: set[int] = set()             # bars we've already decided (bought or gave up)
    settled: set[int] = set()
    best_seen: dict[int, float] = {}    # bar_ws -> best edge seen (for FAV_NOBET telemetry)
    day_pnl: dict[str, float] = {}
    halted = False

    while True:
        now = time.time()
        cur = int(now // BAR_SECONDS) * BAR_SECONDS   # the live bar opens at `cur`
        today = time.strftime("%Y-%m-%d", time.gmtime(now))

        # ---- 1. evaluate the live bar, act at most once ----
        if not halted and cur not in acted and cur not in settled:
            ev = evaluate(cur)
            if ev:
                fav_side, fav_token, cond, fav_true, ask, edge, lead_bps, t_left, mom_z, pocket = ev
                best_seen[cur] = max(best_seen.get(cur, -1), edge)
                if pocket is not None:
                    pk = POCKETS[pocket]
                    shares = max(5.0, math.floor(NOTIONAL / ask))
                    order_id, matched, err = None, False, ""
                    entry = ask
                    if _real:
                        try:
                            from engine.clob import place_market_buy
                            order_id, matched, *_ = place_market_buy(clob, fav_token, float(shares), pk["p_hi"], cond)
                        except Exception as exc:
                            err = str(exc)[:200]
                    else:
                        order_id, matched = f"paper-{cur}", True
                    open_bets[cur] = {"side": fav_side, "token": fav_token, "entry": entry,
                                      "fav_true": fav_true, "shares": shares, "order_id": order_id}
                    acted.add(cur)
                    _event("FAV_BET_PLACED", bar=cur, side=fav_side, entry=entry, fav_true=fav_true,
                           edge=edge, lead_bps=lead_bps, t_left=t_left, mom_z=mom_z, pocket=pocket,
                           shares=shares, order=order_id or "FAILED", matched=matched, live=_real, err=err)
                # give up on this bar once it's too late for every pocket
                elif t_left < MIN_TL_LO:
                    acted.add(cur)
                    _event("FAV_NOBET", bar=cur, best_edge=round(best_seen.get(cur, -1), 4),
                           last_true=fav_true, last_ask=ask, lead_bps=lead_bps, mom_z=mom_z, live=_real)

        # ---- 2. settle matured bets ----
        for t in list(open_bets):
            if now < t + BAR_SECONDS + SETTLE_BUFFER:
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


def main():
    if FAST_EXEC:
        main_fast()
    else:
        main_legacy()


if __name__ == "__main__":
    main()
