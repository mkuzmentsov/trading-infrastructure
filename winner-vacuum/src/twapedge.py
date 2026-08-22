"""twapedge — paper bot for the 2026-08-07 settlement rule change.

On 2026-08-07 00:00 UTC Polymarket switches these markets from a single point
sample at the bell to a 30-second trailing TWAP. The book prices off the last
price; from that moment the last price stops being what settles.

Measured on 120 days x 6 coins of 1s klines joined to the real 1Hz books:
at T-5s the settlement TWAP is already determined (0.09% wrong overall, 0.00%
once |estimate| >= 2bps), and on ~24-30 bars/day it points the OPPOSITE way to
the last price while the book still offers the TWAP-implied winner at a median
17-29c. Those same picks win only 33 of 121 under today's point rule — so this
strategy is -EV today and +EV from the switch. Running it on paper across the
boundary is therefore a clean falsification test: it SHOULD lose money now and
flip afterwards. If it does not lose now, the signal wiring is wrong.

Settlement window (measured live on 8 symbols to 0.0000 bps, see core/rtds.py):
the TWAP tick stamped at t covers [t-32, t-3]. Which tick resolution reads is
still unknown, so every bar records both candidates:

  H1  settlement = tick stamped at T      -> window [T-32, T-3]
  H2  settlement = tick stamped at T+3    -> window [T-29, T]

Both are trailing, so the trade direction holds either way; only the estimator
shifts. PF_TE_SETTLE logs which hypothesis matched the real outcome, which
resolves it empirically within hours of the switch.

Env: PM_TE_SIZE(50) PM_TE_THRESH_BPS(1.0) PM_TE_EVAL_TL(4.5)
     PM_TE_MIN_ASK(0.02) PM_TE_MAX_ASK(0.90)
"""
from __future__ import annotations

import asyncio
import json
import os
import time
import urllib.request

from config import (BAR_SECONDS, DRY_RUN, LIVE_MAX_DAILY_LOSS_USD,
                    LIVE_MAX_ORDER_USD, LIVE_TRADING,
                    TRAINING_EVENT_LOG_PATH, log)
from core.gamma import grid_window_start, window_slug
from core.pm_ws import pm_state, run_pm_ws, set_post_close_grace
from core.rtds import rtds_state, run_rtds
from execution.events import EventLog

COIN = os.getenv("COIN", "btc").lower()
_real = LIVE_TRADING and not DRY_RUN
SYM = os.getenv("PM_TE_SYMBOL", "").strip() or f"{COIN}/usd"
SIZE = float(os.getenv("PM_TE_SIZE", "50"))
# v2 gate: THRESH separates "estimate decides" (>= : 99%+ accurate, buy to
# MAX_ASK) from "genuine tie" (< : ~coin flip, buy only to TIE_MAX_ASK)
THRESH = float(os.getenv("PM_TE_THRESH_BPS", "0.10"))
# §28 time-scaled gate (2026-08-18): flip risk is f(|est|, tl) — a 0.5-1.0bps
# signal flips ~3.1% live at T−28 but ~0-0.6% at T≤14, so weak estimates may
# only fire LATE. Effective threshold = THRESH + SLOPE·max(0, tl−ANCHOR):
# 0.5bps at tl≤14 → ~0.75 at tl 21 → ~1.05 at tl 30 (defaults). Era replay
# (live fills 08-17→18): blocked clips netted −$27.75 incl. ALL 9 losses.
THRESH_SLOPE = float(os.getenv("PM_TE_THRESH_SLOPE", "0.035"))
THRESH_ANCHOR = float(os.getenv("PM_TE_THRESH_ANCHOR", "14"))
COV_FLOOR = float(os.getenv("PM_TE_MIN_COVERAGE", "0.8"))
EVAL_TL = float(os.getenv("PM_TE_EVAL_TL", "4.5"))
MIN_ASK = float(os.getenv("PM_TE_MIN_ASK", "0.02"))
MAX_ASK = float(os.getenv("PM_TE_MAX_ASK", "0.97"))
TIE_MAX_ASK = float(os.getenv("PM_TE_TIE_MAX_ASK", "0.45"))
# live sizing is separate from the paper-sim size so the paper PnL stays
# comparable across the fleet; per-order and per-day dollar caps on top
LIVE_SIZE = float(os.getenv("PM_TE_LIVE_SIZE", "20"))
LIVE_INFLIGHT_CAP = float(os.getenv("PM_TE_LIVE_INFLIGHT_USD", "120"))
LIVE_PX_BUFFER = float(os.getenv("PM_TE_LIVE_PX_BUFFER", "0.01"))
# retry-FAK (2026-08-16): after a killed FAK, re-check the estimate and the
# book and take again for up to LIVE_RETRY_S (0 disables). Measured need:
# 11/11 no-fills in the everybar experiment were asks gone within the
# ~450ms sign+post path, all on bars that settled our way — a kill is free,
# so retake while the signal still qualifies. Taker-only by design: never
# converted to a resting bid (informed flow fills resters exactly when the
# estimate flips — the asymmetry that killed btc-vacuum and mintsalvage).
LIVE_RETRY_S = float(os.getenv("PM_TE_LIVE_RETRY_S", "3.0"))
LIVE_RETRY_GAP_S = float(os.getenv("PM_TE_LIVE_RETRY_GAP_S", "0.3"))
# max the retry may pay ABOVE the original seen ask. Without it the loop
# chased 0.80 -> 0.97 on xrp 2026-08-16 17:14 (650sh level swept mid-flight
# = flip in motion; the re-read "valid in-band ask" was 17c worse for the
# same whisper signal, and lost on a +0.009bps tie). A vanished-and-
# repriced-up book is evidence AGAINST the signal — never chase it.
LIVE_RETRY_CHASE = float(os.getenv("PM_TE_LIVE_RETRY_CHASE", "0.03"))
# ── vol-conditioned ask cap (2026-08-16, measured on 2,034 settled fleet
# bars — docs/vacmaker-offline-notes.md §20). Ambient vol = mean |bar move|
# over the last VOL_BARS settled bars. Sign-hold rate (eval side == winner)
# by |signal| x vol tercile:
#   sig<0.15:   84% / 81% / 71%      0.15-0.5: 96% / 88% / 96%(n47)
#   0.5-1.5:    99% / 98.5% / 94.7%  >=1.5:    100% / 99.8% / 99.8%
# Max affordable ask ~= hold rate; the table below subtracts ~2c margin and
# is clamped by the coin's band cap. Whispers at 0.9x priced 5 of the first
# 8 fleet losses — this cap is the fix that keeps the every-bar behavior
# while refusing to overpay for noise. STRONG signals (>=STRONG_BPS) hold
# ~100% in every regime: those sign the FAK limit AT the band cap (accept
# post-jump fills; everything weaker keeps the tight ask+buffer limit).
VOL_BARS = int(os.getenv("PM_TE_VOL_BARS", "6"))
VOL_LO = float(os.getenv("PM_TE_VOL_LO", "1.9"))      # bps, low/mid tercile
VOL_HI = float(os.getenv("PM_TE_VOL_HI", "3.4"))      # bps, mid/high tercile
STRONG_BPS = float(os.getenv("PM_TE_STRONG_BPS", "1.5"))
#            sig bucket:   <0.15  0.15-0.5  0.5-1.5   (>=1.5 -> band cap)
CAP_TABLE = {"low":        (0.80,  0.94,     0.98),
             "mid":        (0.75,  0.86,     0.97),
             "high":       (0.65,  0.90,     0.93)}
# ── WHALE MODE (2026-08-17, user: clone 0xefdf6abc exactly). Continuous
# taker loop over tl in [WHALE_END, WHALE_START]: every ~0.4s, if the recon
# is decisive (>=THRESH, coverage floor) and the favorite's ask <= WHALE_CAP,
# FAK a clip — and KEEP GOING (his measured 2.76 clips/bar, max 6) until
# WHALE_LADDER_USD is spent on the bar. Measured profile of the wallet:
# entries only inside T-30..T+90 (post-close part = the snipe leg, enabled
# via config), flat 0.99 cap, ~$8 clips, no resting, all 7 coins.
# WHALE_START=0 disables (legacy one-shot path unchanged).
WHALE_START = float(os.getenv("PM_TE_WHALE_START", "0"))
WHALE_END = float(os.getenv("PM_TE_WHALE_END", "3"))
WHALE_LADDER_USD = float(os.getenv("PM_TE_WHALE_LADDER_USD", "16"))
WHALE_COOLDOWN = float(os.getenv("PM_TE_WHALE_COOLDOWN_S", "1.0"))
WHALE_CAP = float(os.getenv("PM_TE_WHALE_CAP", "0.99"))
# Ladder clips beyond the first only on confirmed favorites: every laddered
# loss bar (btc/hype 2026-08-17) was a mid-band double-down, while marginal
# clips at >=0.94 ran 16/16. Clip 1 keeps the full MIN_ASK band.
WHALE_LADDER_MIN_ASK = float(os.getenv("PM_TE_WHALE_LADDER_MIN_ASK", "0.94"))
# In high ambient vol the early lane buys noise: every 08-20 loss bar was
# tl 23-30 x vol>=10 (union-era cell 300 clips −$49.21, chop-day −$83),
# while tl<=20 clips are 105/105 era-wide and the whale's own answer is
# T-15 timing (notes §32/§33 addendum). When ambient vol >= VOL_DELAY_VOL,
# hold whale_loop fire until tl <= VOL_DELAY_TL — a DELAY, not a skip: the
# est gate, coverage floor and band are unchanged, the clip just waits for
# the late lane. Inactive until the vol window warms (~4 settled bars after
# a restart) and when VOL_DELAY_VOL=0.
WHALE_VOL_DELAY_VOL = float(os.getenv("PM_TE_WHALE_VOL_DELAY_VOL", "10"))
WHALE_VOL_DELAY_TL = float(os.getenv("PM_TE_WHALE_VOL_DELAY_TL", "20"))
# ── post-close winner snipe: once the settlement tick lands (~T+1.5s relay)
# the outcome is an identity, not an estimate (ties resolve UP). Any ask on
# the winner below SNIPE_CAP after that moment is free money left by holders
# who cannot call near-ties. 0 disables. Applies to paper sim AND live.
SNIPE_CAP = float(os.getenv("PM_TE_SNIPE_CAP", "0.10"))
# settlement TWAP window length in seconds: 30 for the 5m series, 60 for
# 15m/4h (venue: cryptoMarketConfig.twapLookbackSeconds). H1 = [T-(W+2),T-3].
W = int(os.getenv("PM_TE_TWAP_WINDOW", "30"))
TWAP_TOPIC = ("crypto_prices_twap_thirty" if W == 30
              else "crypto_prices_twap_sixty")
SNIPE_SIZE = float(os.getenv("PM_TE_SNIPE_SIZE", "200"))
SNIPE_LIVE_USD = float(os.getenv("PM_TE_SNIPE_LIVE_USD", "10"))
SNIPE_WINDOW_S = float(os.getenv("PM_TE_SNIPE_WINDOW_S", "45"))
SNIPE_RETRY_S = float(os.getenv("PM_TE_SNIPE_RETRY_S", "1.0"))
# ── lockbuy: endgame favourite-taker (the forensics-proven 99.6% lane).
# Buy the TWAP-implied winner late in the bar when our measured accuracy
# table says the estimate is effectively locked, paying up to the tier cap.
# Tiers (k = seconds left, |est| bps -> max ask): measured on post-switch
# recorder books (bt.py): k<=20 & est>=2.0 -> 100% -> 0.99; k<=10 & est>=1.0
# -> 99.7% -> 0.98. One order per bar; PF_TE_LOCK_* events. 0 disables.
LOCK_LIVE_USD = float(os.getenv("PM_TE_LOCK_LIVE_USD", "15"))
LOCK_WINDOW = float(os.getenv("PM_TE_LOCK_WINDOW_S", "20"))
# k<=5 only: at k=10 the frozen-tail est still drifts toward ties
# (eth 2026-08-11 20:10 fired at k=9.9 est-1.08, decayed to -0.60, lost
# -$14.70). LOCK_MIN_ASK stops a FAK sweeping a thin cheap level deep into
# the book (that fill printed 0.767 avg, not the 0.98 cap).
LOCK_TIERS = [(5.0, 1.5, 0.99), (5.0, 3.0, 0.99)]
LOCK_MIN_ASK = float(os.getenv("PM_TE_LOCK_MIN_ASK", "0.90"))
# ── vacuum-maker: REST a post-only bid instead of lifting an ask ────────────
# Measured on hype 2026-08-14 (6 bars, |est|>=2bps, T-14s): 4 bars had NO ask
# on the implied winner at all and the other 2 offered only 0.999 — you cannot
# take liquidity that does not exist, which is why the FAK path fired 0 times.
# The winner's book is a big BID with no offer, so the 0.94-0.99 buys that
# wallet 0xefdf6abc… books are RESTING bids being hit by late sellers.
# The edge is queue POSITION, not order type: the 0.99 wall measured ~1.4k
# shares at T-3s and ~98k just after close, so arming at T-14s puts us near the
# front while the queue is still short. post_only=True guarantees maker (the
# venue rejects rather than crosses). 0 disables → unchanged FAK behaviour.
MAKER_REST_PX = float(os.getenv("PM_TE_MAKER_REST_PX", "0"))
# cancel the resting bid if the estimate decays below this |bps| before close
MAKER_CANCEL_BPS = float(os.getenv("PM_TE_MAKER_CANCEL_BPS", "1.0"))
FEE = 0.07

_event_log = EventLog(TRAINING_EVENT_LOG_PATH)


def _event(ev: str, **kw):
    _event_log.write(ev, coin=COIN, **kw)


def _bps(px: float, strike: float) -> float:
    return (px - strike) / strike * 1e4


def _outcome_up(ws: int):
    """True/False once resolved, else None."""
    try:
        url = ("https://gamma-api.polymarket.com/markets?slug=" + window_slug(ws)
               + "&closed=true")
        req = urllib.request.Request(url, headers={"User-Agent": "twapedge"})
        d = json.loads(urllib.request.urlopen(req, timeout=10).read())
        if not d or not d[0].get("closed"):
            return None
        op = d[0]["outcomePrices"]
        op = json.loads(op) if isinstance(op, str) else op
        return str(op[0]) in ("1", "1.0")
    except Exception:
        return None


def _reference(ws: int):
    """(priceToBeat, finalPrice) — the exact numbers resolution used.

    Backfilled into gamma ~5-20 min after close, so useless live, but perfect
    as an audit: it catches any drift between our reconstruction of the
    settlement references and the real ones.
    """
    try:
        url = ("https://gamma-api.polymarket.com/markets?slug=" + window_slug(ws)
               + "&closed=true")
        req = urllib.request.Request(url, headers={"User-Agent": "twapedge"})
        d = json.loads(urllib.request.urlopen(req, timeout=10).read())
        if not d:
            return None, None
        md = (d[0].get("events") or [{}])[0].get("eventMetadata") or {}
        return md.get("priceToBeat"), md.get("finalPrice")
    except Exception:
        return None, None


class Bar:
    __slots__ = ("ws", "strike", "evaluated", "bet", "settled", "verified",
                 "close_px", "live", "gtry", "maker_oid", "maker_side",
                 "maker_token", "maker_sh", "maker_fill0", "maker_cost0",
                 "maker_px", "whale", "whale_spent", "whale_last",
                 "whale_delayed")

    def __init__(self, ws: int):
        self.ws = ws
        self.strike = None
        self.evaluated = False
        self.bet = None
        self.settled = False
        self.verified = False
        self.close_px = None
        self.live = None
        self.gtry = 0.0
        self.maker_oid = None            # resting GTC bid (vacmaker v2)
        self.maker_side = None
        self.maker_token = None
        self.maker_sh = 0.0
        self.maker_fill0 = 0.0           # shares crossed at placement
        self.maker_px = 0.0              # actual legal rest price used
        self.maker_cost0 = 0.0           # $ cost of the crossed portion
        self.whale = []                  # whale-mode clips [{side,filled,cost}]
        self.whale_spent = 0.0           # $ committed on this bar's ladder
        self.whale_last = 0.0            # last fire timestamp (cooldown)
        self.whale_delayed = False       # vol-delay counterfactual logged


class TwapEdge:
    def __init__(self):
        self.bars: dict[int, Bar] = {}
        self.day_pnl: dict[str, float] = {}
        self.n_eval = 0
        self.n_bet = 0
        self.clob = None
        self.live_day_pnl: dict[str, float] = {}
        self.live_halted = False
        self.live_inflight = 0.0          # USD in unresolved live positions
        self.recent_moves: list = []      # |bar move bps|, last VOL_BARS bars
        self.presigned: dict = {}         # token_id -> signed cap-limit BUY

    def _ambient_vol(self):
        """Mean |move| of the last VOL_BARS settled bars; None until warm."""
        if len(self.recent_moves) < 4:
            return None
        return sum(self.recent_moves) / len(self.recent_moves)

    def _dyn_cap(self, sig_abs: float):
        """(max_ask, vol, strong) for this signal under current ambient vol.
        Falls back to the flat band cap until the vol window is warm."""
        strong = sig_abs >= STRONG_BPS
        vol = self._ambient_vol()
        if strong or vol is None:
            return MAX_ASK, vol, strong
        regime = "low" if vol < VOL_LO else ("mid" if vol < VOL_HI else "high")
        row = CAP_TABLE[regime]
        cap = row[0] if sig_abs < 0.15 else (row[1] if sig_abs < 0.5 else row[2])
        return min(MAX_ASK, cap), vol, strong

    # ── live order (the paper sim above stays untouched as the benchmark) ───
    async def _live_fire(self, bar: Bar, side: str, ask: float, asz: float):
        day = time.strftime("%Y-%m-%d", time.gmtime())
        if self.live_day_pnl.get(day, 0.0) <= -LIVE_MAX_DAILY_LOSS_USD:
            if not self.live_halted:
                self.live_halted = True
                _event("PF_TE_LIVE_HALT", day=day,
                       day_pnl=round(self.live_day_pnl.get(day, 0.0), 2))
            return
        self.live_halted = False
        # retry-FAK: a kill costs nothing, so after one we re-read book and
        # estimate and take again while BOTH still qualify (same side, over
        # threshold, over the coverage floor, ask in band). Every attempt is
        # a fresh taker decision at a moment we choose — never a rester.
        deadline = min(time.time() + LIVE_RETRY_S,
                       bar.ws + BAR_SECONDS - 2.5)
        orig_ask = ask
        attempt = 0
        while True:
            attempt += 1
            filled = await asyncio.to_thread(self._fire_once, bar, side,
                                             ask, attempt)
            if filled or LIVE_RETRY_S <= 0:
                return
            # wait for a fresh qualifying ask; signal re-checked every tick,
            # and we only fall through to fire with a validated in-band ask
            while True:
                if time.time() >= deadline:
                    return
                await asyncio.sleep(LIVE_RETRY_GAP_S)
                est = self._estimate(bar.ws, "H1")
                if est is None:
                    return
                tw, obs, tot = est
                tl_now = bar.ws + BAR_SECONDS - time.time()
                eff_thresh = THRESH + THRESH_SLOPE * max(0.0, tl_now - THRESH_ANCHOR)
                if ((tw > 0) != (side == "UP") or abs(tw) < eff_thresh
                        or obs / max(tot, 1) < COV_FLOOR):
                    _event("PF_TE_LIVE_RETRY_STOP", bar=bar.ws,
                           reason="signal", est=round(tw, 3),
                           attempt=attempt)
                    return
                ask = pm_state.up_ask if side == "UP" else pm_state.down_ask
                asz = (pm_state.up_ask_size if side == "UP"
                       else pm_state.down_ask_size)
                if (ask and asz
                        and MIN_ASK <= ask <= bar.bet.get("cap", MAX_ASK)
                        and ask <= orig_ask + LIVE_RETRY_CHASE):
                    break             # fresh supply near our price — take it

    def _fire_once(self, bar: Bar, side: str, ask: float,
                   attempt: int) -> bool:
        """One signal-checked FAK. True = filled or firing is pointless."""
        # INTEGER shares only: the venue caps the maker (dollar) amount at 2
        # decimals — 9.1sh x 0.81 = $7.371 was rejected live 2026-08-10. With
        # 2dp prices, whole shares keep the product at 2dp always.
        # Do NOT cap by the visible ask size: FAK partial-fills whatever is
        # there and kills the rest, while an asz cap blocks the venue's $1
        # marketable-BUY minimum on cheap asks (6.3sh x 0.14 = $0.88 rejected
        # live 2026-08-10) and undersizes against refreshing depth.
        sh = float(int(min(LIVE_SIZE, LIVE_MAX_ORDER_USD / max(ask, 0.01))))
        if sh < 5 or sh * ask < 1.05:     # venue minimums: 5 shares AND $1
            _event("PF_TE_LIVE_SKIP", bar=bar.ws, reason="venue_min",
                   sh=round(sh, 1), ask=ask)
            return False
        if self.live_inflight + sh * ask > LIVE_INFLIGHT_CAP:
            _event("PF_TE_LIVE_SKIP", bar=bar.ws, reason="inflight_cap",
                   inflight=round(self.live_inflight, 2))
            return True                   # cap-bound: retrying cannot help
        token = (pm_state.token_id_up if side == "UP"
                 else pm_state.token_id_down)
        if not token:
            _event("PF_TE_LIVE_SKIP", bar=bar.ws, reason="no_token")
            return False
        from engine.clob import post_signed_buy, sign_buy_order
        tick = pm_state.tick_size.get(token, 0.01)
        # 1-tick buffer above the seen ask: the first live order lost the race
        # ("no orders found to match with FAK") because the level vanished in
        # the ~0.6s sign+post path. FAK still fills at the best available ask
        # <= limit, so the buffer only pays extra when the book actually moved
        # one tick — and never past the strategy cap.
        if abs(bar.bet["twap_bps"]) >= THRESH:
            cap = bar.bet.get("cap", MAX_ASK)
        else:
            cap = TIE_MAX_ASK
        if bar.bet.get("strong"):
            # >=STRONG_BPS holds ~100% in every vol regime: sign the limit AT
            # the band cap so a mid-flight book jump still fills (the venue
            # price-improves to the true best ask; the cap is the worst case).
            px = round(cap, 3)
        else:
            px = round(min(ask + LIVE_PX_BUFFER, cap), 3)
        # strong-signal hot path: use the bar-start presigned cap order
        # (identical px/sh by construction) — POST only, no 100-300ms sign
        pre = None
        if bar.bet.get("strong") and px == round(MAX_ASK, 3):
            pre = self.presigned.pop(token, None)
        t0 = time.time()
        try:
            signed = pre if pre is not None else sign_buy_order(
                self.clob, token, sh, px, tick_size=tick)
            oid, matched, avg_px, filled = post_signed_buy(self.clob, signed, "FAK")
        except Exception as exc:
            _event("PF_TE_LIVE_ERR", bar=bar.ws, err=str(exc)[:160])
            return False
        cost = (avg_px or px) * (filled or 0.0)
        got = bool(filled)
        if got:
            self.live_inflight += cost
        if got or bar.live is None:       # a fill is never clobbered by a
            bar.live = dict(side=side, ask=px, req_sh=round(sh, 1), oid=oid,
                            matched=matched, avg_px=avg_px,
                            filled=filled or 0.0, cost=cost)
        _event("PF_TE_LIVE_ORDER", bar=bar.ws, side=side, seen_ask=ask,
               req_px=px, req_sh=round(sh, 1), order=oid, matched=matched,
               avg_px=avg_px, filled=filled, cost=round(cost, 4),
               ms=int((time.time() - t0) * 1000), attempt=attempt,
               presigned=bool(pre))
        return got

    # ── vacuum-maker: rest a post-only bid on the implied winner ───────────
    def _maker_rest(self, bar: Bar, side: str, est_bps: float):
        day = time.strftime("%Y-%m-%d", time.gmtime())
        if self.live_day_pnl.get(day, 0.0) <= -LIVE_MAX_DAILY_LOSS_USD:
            if not self.live_halted:
                self.live_halted = True
                _event("PF_TE_LIVE_HALT", day=day,
                       day_pnl=round(self.live_day_pnl.get(day, 0.0), 2))
            return
        self.live_halted = False
        token_pre = (pm_state.token_id_up if side == "UP"
                     else pm_state.token_id_down)
        tick_pre = float(pm_state.tick_size.get(token_pre, 0.01) or 0.01)
        # venue validates price against the CURRENT tick grid: max = 1 - tick.
        # 0.991 is only legal after the book's tick flips to 0.001 (>~0.96);
        # before that the best legal front-of-wall price is 0.99 (measured
        # live 2026-08-16 21:0x: every rest errored "invalid price (0.991),
        # max: 0.99"). Round the configured rest px DOWN onto the legal grid.
        px = min(MAKER_REST_PX, 1.0 - tick_pre)
        px = round(int(px / tick_pre) * tick_pre, 3)
        # whole shares only (venue caps the maker dollar amount at 2 decimals)
        sh = float(int(min(LIVE_SIZE, LIVE_MAX_ORDER_USD / max(px, 0.01))))
        if sh < 5 or sh * px < 1.05:          # venue minimums: 5 shares AND $1
            _event("PF_TE_MAKER_SKIP", bar=bar.ws, reason="venue_min",
                   sh=round(sh, 1), px=px)
            return
        if self.live_inflight + sh * px > LIVE_INFLIGHT_CAP:
            _event("PF_TE_MAKER_SKIP", bar=bar.ws, reason="inflight_cap",
                   inflight=round(self.live_inflight, 2))
            return
        token = (pm_state.token_id_up if side == "UP"
                 else pm_state.token_id_down)
        if not token:
            _event("PF_TE_MAKER_SKIP", bar=bar.ws, reason="no_token")
            return
        # plain marketable GTC (user 2026-08-17: NOT post-only): crosses any
        # asks <= px immediately at their prices, remainder RESTS at px.
        from engine.clob import post_signed_buy, sign_buy_order
        tick = pm_state.tick_size.get(token, 0.01)
        t0 = time.time()
        try:
            signed = sign_buy_order(self.clob, token, sh, px, tick_size=tick)
            oid, matched, avg_px, fill0 = post_signed_buy(self.clob, signed,
                                                          "GTC")
        except Exception as exc:
            _event("PF_TE_MAKER_ERR", bar=bar.ws, err=str(exc)[:160])
            return
        if not oid:
            _event("PF_TE_MAKER_ERR", bar=bar.ws, err="no_order_id")
            return
        bar.maker_oid, bar.maker_side = oid, side
        bar.maker_token, bar.maker_sh = token, sh
        bar.maker_fill0 = fill0 or 0.0
        bar.maker_cost0 = (avg_px or px) * (fill0 or 0.0)
        bar.maker_px = px
        self.live_inflight += sh * px
        _event("PF_TE_MAKER_REST", bar=bar.ws, side=side, px=px,
               sh=round(sh, 1), order=oid, est_bps=round(est_bps, 3),
               crossed=round(fill0 or 0.0, 2),
               crossed_avg=avg_px,
               ms=int((time.time() - t0) * 1000))

    async def maker_loop(self):
        """Cancel a resting bid if the estimate that justified it decays or
        flips before the bell; otherwise leave it to be hit by late sellers.
        After close, book whatever actually filled."""
        if MAKER_REST_PX <= 0:
            return
        from engine.clob import cancel_order, get_order_filled
        while True:
            await asyncio.sleep(0.5)
            now = time.time()
            for ws, bar in list(self.bars.items()):
                if not bar.maker_oid:
                    continue
                tl = ws + BAR_SECONDS - now
                if tl > 0:
                    est = self._estimate(ws, "H1")
                    if est is None:
                        continue
                    tw, _obs, _tot = est
                    flipped = (tw > 0) != (bar.maker_side == "UP")
                    if flipped or abs(tw) < MAKER_CANCEL_BPS:
                        # cancel FIRST (stop the bleed), then book whatever
                        # crossed at placement or was hit before the cancel —
                        # a GTC can hold real shares the settle must account.
                        ok = await asyncio.to_thread(cancel_order, self.clob,
                                                     bar.maker_oid)
                        filled = await asyncio.to_thread(get_order_filled,
                                                         self.clob,
                                                         bar.maker_oid)
                        filled = max(float(filled or 0.0), bar.maker_fill0)
                        rest = max(0.0, filled - bar.maker_fill0)
                        cost = bar.maker_cost0 + rest * bar.maker_px
                        self.live_inflight = max(
                            0.0, self.live_inflight
                            - bar.maker_sh * bar.maker_px + cost)
                        if filled > 0:
                            bar.live = dict(side=bar.maker_side,
                                            ask=bar.maker_px,
                                            req_sh=bar.maker_sh,
                                            oid=bar.maker_oid, matched=True,
                                            avg_px=round(cost / filled, 4),
                                            filled=filled, cost=cost)
                        _event("PF_TE_MAKER_CANCEL", bar=ws,
                               side=bar.maker_side, est_bps=round(tw, 3),
                               flipped=flipped, tl=round(tl, 2), ok=ok,
                               filled=round(filled, 2))
                        bar.maker_oid = None
                    continue
                if tl < -20:                  # bar closed: book the real fill
                    filled = await asyncio.to_thread(get_order_filled,
                                                     self.clob, bar.maker_oid)
                    filled = max(float(filled or 0.0), bar.maker_fill0)
                    rest = max(0.0, filled - bar.maker_fill0)
                    cost = bar.maker_cost0 + rest * bar.maker_px
                    self.live_inflight = max(
                        0.0, self.live_inflight - bar.maker_sh * bar.maker_px + cost)
                    if filled > 0:
                        bar.live = dict(side=bar.maker_side, ask=bar.maker_px,
                                        req_sh=bar.maker_sh, oid=bar.maker_oid,
                                        matched=True,
                                        avg_px=round(cost / filled, 4),
                                        filled=filled, cost=cost)
                    else:
                        await asyncio.to_thread(cancel_order, self.clob,
                                                bar.maker_oid)
                    _event("PF_TE_MAKER_DONE", bar=ws, side=bar.maker_side,
                           order=bar.maker_oid, filled=round(filled, 1),
                           req_sh=bar.maker_sh, cost=round(cost, 4),
                           fill_rate=round(filled / max(bar.maker_sh, 1), 3))
                    bar.maker_oid = None

    # ── the estimate ────────────────────────────────────────────────────────
    def _estimate(self, ws: int, hyp: str):
        """(twap_lead_bps, observed, total) for hypothesis H1 or H2."""
        end = ws + BAR_SECONDS
        lo, hi = (end - (W + 2), end - 3) if hyp == "H1" else (end - (W - 1), end)
        r = rtds_state.window_mean(SYM, lo, hi)
        if r is None:
            return None
        mean, obs, tot = r
        return _bps(mean, self.bars[ws].strike), obs, tot

    async def eval_loop(self):
        while True:
            await asyncio.sleep(0.25)
            now = time.time()
            ws = grid_window_start(now)
            bar = self.bars.get(ws)
            if bar is None:
                bar = self.bars[ws] = Bar(ws)
            if bar.strike is None:
                # SETTLEMENT RULE, proven 2026-08-08 on 2,237 post-switch bars
                # (PF_TE_VERIFY vs gamma): priceToBeat = the TWAP-feed tick
                # stamped EXACTLY at ws (chaining finalPrice[N]==priceToBeat[N+1]
                # held 2237/2237, and the end tick matches our [T-32,T-3] window
                # to 0.0019 bps median). So the strike is read straight off the
                # twap topic. The relay runs ~1.7s behind — keep retrying until
                # the ws-stamped tick lands rather than accepting a neighbour.
                # (Pre-switch this bot used the point tick at ws: that was the
                # rule then; post-switch the point strike is ~0.4bps off and
                # flips every sub-bp call.)
                bar.strike = rtds_state.twap_at(SYM, ws)
                if (bar.strike is None and now - ws > 120
                        and now - bar.gtry > 45):
                    # feed started after this bar opened (long grids / pod
                    # restarts): gamma backfills priceToBeat ~5-10 min into
                    # the bar — use it so 15m/4h bars are not lost.
                    bar.gtry = now
                    ptb, _ = await asyncio.to_thread(_reference, ws)
                    if not ptb:
                        # chaining identity: this bar's strike == the PREVIOUS
                        # bar's finalPrice (proven 2237/2237), and gamma
                        # backfills finalPrice minutes after the prev close —
                        # available for the whole current bar on long grids
                        # where our own ptb only appears near the end.
                        _, fin_prev = await asyncio.to_thread(
                            _reference, ws - BAR_SECONDS)
                        ptb = fin_prev
                    if ptb:
                        bar.strike = float(ptb)
                        _event("PF_TE_STRIKE_GAMMA", bar=ws, strike=bar.strike)
                if bar.strike is None and 0 < ws + BAR_SECONDS - now <= EVAL_TL \
                        and not bar.evaluated:
                    # loud, not silent: a bar reached its eval window without
                    # any strike (cost the first two 4h bars, 2026-08-11)
                    bar.evaluated = True
                    _event("PF_TE_EVAL_MISS", bar=ws, reason="no_strike")
                continue
            tl = ws + BAR_SECONDS - now
            if bar.evaluated or not (0.5 < tl <= EVAL_TL):
                continue
            bar.evaluated = True
            self.n_eval += 1
            try:
                await self._evaluate(bar, tl)
            except Exception as exc:
                log.exception("evaluate: %s", exc)
                _event("PF_TE_ERR", bar=bar.ws, err=str(exc)[:160])

    async def _evaluate(self, bar: Bar, tl: float):
        latest = rtds_state.latest(SYM)
        if latest is None:
            return
        point_lead = _bps(latest[1], bar.strike)
        e1 = self._estimate(bar.ws, "H1")
        e2 = self._estimate(bar.ws, "H2")
        if e1 is None:
            return
        tw1, obs1, tot1 = e1
        tw2 = e2[0] if e2 else None
        # feed-coverage guard: with RTDS gaps the forward-filled window mean
        # can be badly wrong (xrp 08-09 18:50: obs 16/30, est +1.64 vs true
        # -0.51, lost at 96%-against-book pricing). Low coverage -> the
        # estimate is NOT in the verified 99.7% zone; demote to tie handling.
        coverage = obs1 / max(tot1, 1)
        # NOT pm_state.ready: that flag needs BOTH sides live (bid AND ask on
        # UP and DOWN), which is architecturally False in the last seconds of
        # a decided bar — the loser's bid legitimately vanishes. Measured
        # 2026-08-08: ready was False on ~85% of evals while the recorder saw
        # tradable asks on our side. We only need: right market window, a
        # flowing feed, and (implicitly, via the ask<=cap gate) a real ask on
        # the side we want — _apply_top_of_book keeps per-side values current
        # on every event, so ask=1.0/sz=0 already encodes "no ask".
        book_ok = (pm_state.market_end_ts == bar.ws + BAR_SECONDS
                   and pm_state.book_events > 0
                   and time.time() - (pm_state.last_ws_message_at or 0) < 10)
        side = "UP" if tw1 > 0 else "DOWN"
        ask = pm_state.up_ask if side == "UP" else pm_state.down_ask
        asz = pm_state.up_ask_size if side == "UP" else pm_state.down_ask_size
        disagree = (tw1 > 0) != (point_lead > 0)
        # GATE v2 (2026-08-08, backtested on 1.5d of post-switch recorder books
        # + the fleet's own corrected RTDS estimates): the estimate is 99.0-99.9%
        # right at |est|>=0.25bps and 93% at 0-0.25, so simply buy the implied
        # winner whenever its ask is below MAX_ASK — no point-disagreement
        # condition (v1's disagree-gate compared two feeds sampled at different
        # instants and fired never post-switch / on favourites pre-switch).
        # Exact ties (|est|<TIE_BPS) are ~coin-flips: only take them at
        # TIE_MAX_ASK or better, where 50/50 still pays.
        # coverage floor: 0.8 suits the T-4.5 near-complete-window read; at
        # early eval_tl (40-50s) only ~(62-tl)/59 of the window is observable
        # so 0.8 is unreachable and blocks ALL fires (found live 2026-08-15,
        # eth/bnb 0 fires in 3.5h). Env-gated; default keeps old behavior.
        decisive = abs(tw1) >= THRESH and coverage >= COV_FLOOR
        # vol-conditioned ask cap: refuse to pay more than the measured
        # hold-rate for this (signal, ambient-vol) cell affords (§ module
        # consts). Strong signals keep the full band cap.
        dyn_cap, amb_vol, strong = self._dyn_cap(abs(tw1))
        # maker mode needs NO ask — that is the whole point (see MAKER_REST_PX).
        # It still requires a live, window-matched book so we never rest into a
        # stale/rolled market, and it only ever rests on a DECISIVE estimate.
        maker = MAKER_REST_PX > 0 and decisive and book_ok
        fire = (book_ok and asz > 0 and MIN_ASK <= ask
                and (ask <= dyn_cap if decisive else ask <= TIE_MAX_ASK))
        _event("PF_TE_EVAL", bar=bar.ws, tl=round(tl, 2), strike=bar.strike,
               pm_ready=pm_state.ready, pm_end=pm_state.market_end_ts,
               pm_q=(pm_state.question or "")[:40],
               pm_msg_age=round(time.time() - (pm_state.last_ws_message_at or 0), 1),
               point_bps=round(point_lead, 3), twap_h1_bps=round(tw1, 3),
               twap_h2_bps=None if tw2 is None else round(tw2, 3),
               obs=obs1, tot=tot1, coverage=round(coverage, 2),
               disagree=disagree, side=side,
               ask=round(ask, 3), ask_sz=round(asz, 1), book=book_ok,
               cap=round(dyn_cap, 2),
               vol=None if amb_vol is None else round(amb_vol, 2),
               lat=round(rtds_state.lat_ewma, 2), fire=fire, maker=maker)
        if maker and not bar.maker_oid:
            bar.bet = dict(side=side, ask=MAKER_REST_PX, sh=SIZE,
                           fee=FEE * MAKER_REST_PX * (1 - MAKER_REST_PX),
                           point_bps=point_lead, twap_bps=tw1, tl=tl)
            if _real and self.clob is not None:
                await asyncio.to_thread(self._maker_rest, bar, side, tw1)
            else:
                _event("PF_TE_MAKER_PAPER", bar=bar.ws, side=side,
                       px=MAKER_REST_PX, sh=SIZE, twap_bps=round(tw1, 3),
                       tl=round(tl, 2))
            return
        if not fire:
            return
        sh = min(SIZE, asz)
        fee = FEE * ask * (1 - ask)
        bar.bet = dict(side=side, ask=ask, sh=sh, fee=fee,
                       point_bps=point_lead, twap_bps=tw1, tl=tl,
                       cap=dyn_cap, strong=strong)
        self.n_bet += 1
        _event("PF_TE_BET", bar=bar.ws, side=side, px=round(ask, 3), sh=round(sh, 1),
               cost=round(sh * (ask + fee), 4), point_bps=round(point_lead, 3),
               twap_bps=round(tw1, 3), tl=round(tl, 2), paper=True)
        if _real and self.clob is not None and WHALE_START <= 0:
            await self._live_fire(bar, side, ask, asz)

    # ── settle ──────────────────────────────────────────────────────────────
    async def settle_loop(self):
        while True:
            await asyncio.sleep(10.0)
            now = time.time()
            for ws, bar in list(self.bars.items()):
                if bar.settled or bar.strike is None:
                    continue
                if now < ws + BAR_SECONDS + 45:
                    continue
                # hard-bound the gamma lookup: on 2026-08-17 12:11 one hung
                # urllib call (despite its own timeout) froze this loop for
                # 45+ min fleet-wide — whale fills went unbooked. wait_for
                # guarantees the pipeline advances past a stuck bar.
                try:
                    up = await asyncio.wait_for(
                        asyncio.to_thread(_outcome_up, ws), timeout=25)
                except Exception:
                    up = None
                if up is None:
                    if now > ws + BAR_SECONDS + 900:
                        bar.settled = True
                        if bar.whale or (bar.live and bar.live.get("filled")):
                            _event("PF_TE_SETTLE_ABANDONED", bar=ws,
                                   whale_clips=len(bar.whale),
                                   note="outcome unresolvable; positions "
                                        "redeem via sweeper, pnl unbooked")
                    continue
                try:
                    await self._settle(bar, up)
                except Exception as exc:
                    log.exception("settle %s: %s", ws, exc)
                    bar.settled = True

    async def _settle(self, bar: Bar, up: bool):
        bar.settled = True
        won = "UP" if up else "DOWN"
        end = bar.ws + BAR_SECONDS
        # realized references, now that the whole window is published
        pt = rtds_state.point_at(SYM, end, back=0)
        # the true settlement close is the TWAP tick at the bell (finalPrice)
        bar.close_px = rtds_state.twap_at(SYM, end) or pt
        # ambient-vol tracker for the dynamic ask cap
        if bar.close_px is not None and bar.strike:
            self.recent_moves.append(abs(_bps(bar.close_px, bar.strike)))
            del self.recent_moves[:-VOL_BARS]
        r1 = rtds_state.window_mean(SYM, end - (W + 2), end - 3)
        r2 = rtds_state.window_mean(SYM, end - (W - 1), end)
        pl = None if pt is None else _bps(pt, bar.strike)
        t1 = None if r1 is None else _bps(r1[0], bar.strike)
        t2 = None if r2 is None else _bps(r2[0], bar.strike)
        says = lambda v: None if v is None else ("UP" if v > 0 else "DOWN")
        pnl = 0.0
        if bar.bet:
            b = bar.bet
            gross = (1.0 if b["side"] == won else 0.0) - b["ask"] - b["fee"]
            pnl = gross * b["sh"]
            day = time.strftime("%Y-%m-%d", time.gmtime())
            self.day_pnl[day] = self.day_pnl.get(day, 0.0) + pnl
        if bar.live and bar.live.get("filled"):
            lv = bar.live
            payout = lv["filled"] * (1.0 if lv["side"] == won else 0.0)
            lpnl = payout - lv["cost"]
            self.live_inflight = max(0.0, self.live_inflight - lv["cost"])
            day = time.strftime("%Y-%m-%d", time.gmtime())
            self.live_day_pnl[day] = self.live_day_pnl.get(day, 0.0) + lpnl
            _event("PF_TE_LIVE_SETTLE", bar=bar.ws, side=lv["side"], won=won,
                   filled=round(lv["filled"], 2), cost=round(lv["cost"], 4),
                   payout=round(payout, 4), pnl=round(lpnl, 4),
                   live_day_pnl=round(self.live_day_pnl.get(day, 0.0), 3),
                   avg_px=lv.get("avg_px"), req_px=lv.get("ask"))
        for i, cl in enumerate(bar.whale):
            payout = cl["filled"] * (1.0 if cl["side"] == won else 0.0)
            lpnl = payout - cl["cost"]
            self.live_inflight = max(0.0, self.live_inflight - cl["cost"])
            day = time.strftime("%Y-%m-%d", time.gmtime())
            self.live_day_pnl[day] = self.live_day_pnl.get(day, 0.0) + lpnl
            _event("PF_TE_LIVE_SETTLE", bar=bar.ws, side=cl["side"], won=won,
                   filled=round(cl["filled"], 2), cost=round(cl["cost"], 4),
                   payout=round(payout, 4), pnl=round(lpnl, 4),
                   live_day_pnl=round(self.live_day_pnl.get(day, 0.0), 3),
                   avg_px=cl.get("avg_px"), req_px=None, clip=i + 1)
        bar.whale = []
        _event("PF_TE_SETTLE", bar=bar.ws, won=won,
               bet_side=None if not bar.bet else bar.bet["side"],
               bet_px=None if not bar.bet else round(bar.bet["ask"], 3),
               bet_sh=None if not bar.bet else round(bar.bet["sh"], 1),
               pnl=round(pnl, 4),
               day_pnl=round(self.day_pnl.get(
                   time.strftime("%Y-%m-%d", time.gmtime()), 0.0), 3),
               point_bps=None if pl is None else round(pl, 3),
               h1_bps=None if t1 is None else round(t1, 3),
               h2_bps=None if t2 is None else round(t2, 3),
               point_says=says(pl), h1_says=says(t1), h2_says=says(t2),
               point_ok=None if pl is None else (says(pl) == won),
               h1_ok=None if t1 is None else (says(t1) == won),
               h2_ok=None if t2 is None else (says(t2) == won),
               paper=True)
        for w in [w for w in self.bars if self.bars[w].settled and w < bar.ws - 7200]:
            self.bars.pop(w, None)

    async def snipe_loop(self):
        """Post-close winner snipe. Once the settlement tick for T lands
        (~T+1.5s relay) the winner is an identity (ties resolve UP). Any ask
        on that token <= SNIPE_CAP during the grace window is bought: paper
        always, live FAK when _real. The sniper fleets run price feeds and go
        blind on near-ties; the tick does not."""
        if SNIPE_CAP <= 0:
            return
        done: set[int] = set()
        while True:
            await asyncio.sleep(0.2)
            now = time.time()
            T = grid_window_start(now)            # current bar's start
            end = T                               # previous bar ended at T
            bar = self.bars.get(end - BAR_SECONDS)
            if bar is None or end in done:
                continue
            age = now - end
            if not (0.5 <= age <= SNIPE_WINDOW_S):
                continue
            tick = rtds_state.twap_at(SYM, end)
            fb = False
            if tick is None and age > 3.0:
                # the 1Hz twap feed has occasional holes at the boundary
                # second (measured live 2026-08-11: SNIPE_SKIP no_tick).
                # A neighbouring tick's window differs by <=2s of the mean —
                # sign-identical unless the bar is a genuine near-tie, so
                # accept it only with a decisiveness guard below.
                tick = (rtds_state.twap_at(SYM, end + 1)
                        or rtds_state.twap_at(SYM, end + 2))
                fb = tick is not None
            strike = bar.strike
            if tick is None or strike is None:
                if age > 10:
                    done.add(end)
                    # say WHICH is missing: "no_tick" alone sent me probing the
                    # RTDS feed (which turned out to be a clean contiguous 1Hz
                    # with zero missing seconds) when the strike was the real
                    # suspect. twap_ct shows whether the tick cache is warm.
                    _event("PF_TE_SNIPE_SKIP", bar=bar.ws,
                           reason=("no_tick" if tick is None else "no_strike"),
                           tick=tick, strike=strike, age=round(age, 1),
                           twap_ct=len(rtds_state.twap.get(SYM, {})),
                           end=end, bar_ws=bar.ws)
                continue
            if fb and abs((tick - strike) / strike * 1e4) < 1.0:
                done.add(end)
                _event("PF_TE_SNIPE_SKIP", bar=bar.ws, reason="fb_near_tie")
                continue
            winner = "UP" if tick >= strike else "DOWN"   # ties -> UP
            # book must still be the ENDED market (grace keeps it subscribed)
            if pm_state.market_end_ts != end:
                continue
            ask = pm_state.up_ask if winner == "UP" else pm_state.down_ask
            asz = (pm_state.up_ask_size if winner == "UP"
                   else pm_state.down_ask_size)
            if not ask or not (0 < ask <= SNIPE_CAP) or not asz:
                continue
            done.add(end)
            if len(done) > 400:
                done = {x for x in done if x > end - 7200}
            move = (tick - strike) / strike * 1e4
            sh_p = min(SNIPE_SIZE, asz)
            fee = 0.07 * ask * (1 - ask)
            _event("PF_TE_SNIPE_PAPER", bar=bar.ws, winner=winner,
                   move_bps=round(move, 3), ask=ask, asz=round(asz, 1),
                   sh=round(sh_p, 1), pnl=round(sh_p * (1 - ask - fee), 4),
                   age=round(age, 2), paper=True)
            if _real and self.clob is not None:
                await asyncio.to_thread(self._snipe_fire, bar, winner, end)

    def _snipe_fire(self, bar: Bar, winner: str, end: int):
        day = time.strftime("%Y-%m-%d", time.gmtime())
        if self.live_day_pnl.get(day, 0.0) <= -LIVE_MAX_DAILY_LOSS_USD:
            return
        token = (pm_state.token_id_up if winner == "UP"
                 else pm_state.token_id_down)
        if not token:
            return
        sh = float(int(min(SNIPE_SIZE, SNIPE_LIVE_USD / SNIPE_CAP)))
        if sh < 5 or sh * SNIPE_CAP < 1.05:
            return
        from engine.clob import post_signed_buy, sign_buy_order
        tick_sz = pm_state.tick_size.get(token, 0.01)
        t0 = time.time()
        try:
            signed = sign_buy_order(self.clob, token, sh, SNIPE_CAP,
                                    tick_size=tick_sz)
            oid, matched, avg_px, filled = post_signed_buy(self.clob, signed,
                                                           "FAK")
        except Exception as exc:
            _event("PF_TE_SNIPE_ERR", bar=bar.ws, err=str(exc)[:160])
            return
        filled = filled or 0.0
        cost = (avg_px or SNIPE_CAP) * filled
        # outcome is already known: book realized pnl immediately
        fee = 0.07 * (avg_px or SNIPE_CAP) * (1 - (avg_px or SNIPE_CAP)) * filled
        pnl = filled * 1.0 - cost - fee if filled else 0.0
        if filled:
            self.live_day_pnl[day] = self.live_day_pnl.get(day, 0.0) + pnl
        _event("PF_TE_SNIPE_ORDER", bar=bar.ws, winner=winner, cap=SNIPE_CAP,
               req_sh=sh, order=oid, matched=matched, avg_px=avg_px,
               filled=filled, cost=round(cost, 4), pnl=round(pnl, 4),
               live_day_pnl=round(self.live_day_pnl.get(day, 0.0), 3),
               ms=int((time.time() - t0) * 1000))

    async def lock_loop(self):
        """Endgame lock-buy: scan the final LOCK_WINDOW seconds; when (k,|est|)
        hits a tier, buy the implied winner at up to the tier cap (paper
        always, live FAK when _real)."""
        if LOCK_LIVE_USD <= 0 and not True:
            return
        done: set[int] = set()
        while True:
            await asyncio.sleep(0.4)
            now = time.time()
            ws = grid_window_start(now)
            bar = self.bars.get(ws)
            if bar is None or bar.strike is None or ws in done:
                continue
            k = ws + BAR_SECONDS - now
            if not (2.5 < k <= 5.0):
                continue
            e1 = self._estimate(ws, "H1")
            if e1 is None:
                continue
            est, obs, tot = e1
            # coverage of the OBSERVABLE portion only: at k seconds left the
            # final (k-3) window seconds cannot exist yet — demanding 80% of
            # the WHOLE window silenced every k>5 tier (0 lock events in the
            # first 24 bars). The tier table was measured with exactly this
            # frozen-tail estimator, so partial windows are priced in; the
            # guard only needs to catch holes in the PUBLISHED part.
            observable = max(1.0, tot - max(0.0, k - 3.0) - 2.0)
            if obs < 0.8 * observable:
                continue
            cap = 0.0
            for kmax, emin, c in LOCK_TIERS:
                if k <= kmax and abs(est) >= emin:
                    cap = max(cap, c)
            if cap <= 0:
                continue
            if pm_state.market_end_ts != ws + BAR_SECONDS:
                continue
            side = "UP" if est >= 0 else "DOWN"
            ask = pm_state.up_ask if side == "UP" else pm_state.down_ask
            asz = (pm_state.up_ask_size if side == "UP"
                   else pm_state.down_ask_size)
            if not ask or not (LOCK_MIN_ASK <= ask <= cap) or not asz:
                continue
            done.add(ws)
            if len(done) > 400:
                done = {x for x in done if x > ws - 7200}
            fee = FEE * ask * (1 - ask)
            sh_p = min(50.0, asz)
            _event("PF_TE_LOCK_PAPER", bar=ws, side=side, est=round(est, 3),
                   k=round(k, 1), ask=ask, asz=round(asz, 1), cap=cap,
                   sh=round(sh_p, 1), edge=round((1 - ask - fee) * 100, 3))
            if _real and self.clob is not None and LOCK_LIVE_USD > 0:
                await asyncio.to_thread(self._lock_fire, bar, side, cap, ask)

    def _lock_fire(self, bar: Bar, side: str, cap: float, seen_ask: float):
        day = time.strftime("%Y-%m-%d", time.gmtime())
        if self.live_day_pnl.get(day, 0.0) <= -LIVE_MAX_DAILY_LOSS_USD:
            return
        token = (pm_state.token_id_up if side == "UP"
                 else pm_state.token_id_down)
        if not token:
            return
        sh = float(int(LOCK_LIVE_USD / cap))
        if sh < 5 or sh * cap < 1.05:
            return
        from engine.clob import post_signed_buy, sign_buy_order
        tick = pm_state.tick_size.get(token, 0.01)
        t0 = time.time()
        try:
            signed = sign_buy_order(self.clob, token, sh, cap, tick_size=tick)
            oid, matched, avg_px, filled = post_signed_buy(self.clob, signed,
                                                           "FAK")
        except Exception as exc:
            _event("PF_TE_LOCK_ERR", bar=bar.ws, err=str(exc)[:140])
            return
        filled = filled or 0.0
        cost = (avg_px or cap) * filled
        bar.live = dict(side=side, ask=(avg_px or cap), req_sh=sh, oid=oid,
                        matched=matched, avg_px=avg_px, filled=filled,
                        cost=cost)
        self.live_inflight += cost
        _event("PF_TE_LOCK_ORDER", bar=bar.ws, side=side, cap=cap,
               seen_ask=seen_ask, req_sh=sh, order=oid, matched=matched,
               avg_px=avg_px, filled=filled, cost=round(cost, 4),
               ms=int((time.time() - t0) * 1000))

    async def verify_loop(self):
        """Audit our reconstructed references against the ones gamma publishes.

        A silent strike drift of a fraction of a bp is invisible in the PnL but
        flips exactly the sub-bp bars this strategy trades. This makes that
        failure loud instead of lucky.
        """
        while True:
            await asyncio.sleep(120.0)
            now = time.time()
            for ws, bar in list(self.bars.items()):
                if bar.verified or not bar.settled or bar.strike is None:
                    continue
                if now < ws + BAR_SECONDS + 1200:
                    continue
                try:
                    ptb, fin = await asyncio.wait_for(
                        asyncio.to_thread(_reference, ws), timeout=25)
                except Exception:
                    ptb, fin = None, None
                if ptb is None:
                    if now > ws + BAR_SECONDS + 5400:
                        bar.verified = True
                    continue
                bar.verified = True
                d_strike = (bar.strike - ptb) / ptb * 1e4
                d_close = (None if bar.close_px is None or not fin
                           else (bar.close_px - fin) / fin * 1e4)
                bad = abs(d_strike) > 0.05 or (d_close is not None
                                               and abs(d_close) > 0.05)
                _event("PF_TE_VERIFY", bar=ws, ok=not bad,
                       our_strike=bar.strike, true_strike=ptb,
                       strike_err_bps=round(d_strike, 4),
                       our_close=bar.close_px, true_close=fin,
                       close_err_bps=None if d_close is None else round(d_close, 4),
                       true_move_bps=None if not fin else
                       round((fin - ptb) / ptb * 1e4, 4))
                if bad:
                    log.warning("twapedge: reference drift bar=%s strike=%+.4fbps "
                                "close=%s", ws, d_strike, d_close)

    async def warm_loop(self):
        """Keep the CLOB session's TLS/auth warm: the first live order after
        idle paid 561ms vs ~200-300ms warm (measured 2026-08-10). A cheap
        authenticated read every 45s keeps connection pools open."""
        from engine.clob import fetch_usdc_balance
        while _real:
            await asyncio.sleep(45.0)
            if self.clob is not None:
                try:
                    await asyncio.to_thread(fetch_usdc_balance, self.clob)
                except Exception:
                    pass

    async def whale_loop(self):
        """The 0xefdf6abc clone: continuous taker over the endgame window.
        Fires a clip whenever recon-decisive AND favorite ask <= WHALE_CAP,
        then keeps watching for the next one (re-entry ladder) until the
        bar's ladder budget is spent. Pure taker — no resting, no chase:
        every fire prices off the CURRENT ask."""
        if WHALE_START <= 0 or not _real:
            return
        while True:
            await asyncio.sleep(0.4)
            if self.clob is None:
                continue
            now = time.time()
            ws = grid_window_start(now)
            bar = self.bars.get(ws)
            if bar is None or bar.strike is None:
                continue
            tl = ws + BAR_SECONDS - now
            if not (WHALE_END < tl <= WHALE_START):
                continue
            if bar.whale_spent >= WHALE_LADDER_USD:
                continue
            if now - bar.whale_last < WHALE_COOLDOWN:
                continue
            est = self._estimate(ws, "H1")
            if est is None:
                continue
            tw, obs, tot = est
            eff_thresh = THRESH + THRESH_SLOPE * max(0.0, tl - THRESH_ANCHOR)
            if abs(tw) < eff_thresh or obs / max(tot, 1) < COV_FLOOR:
                continue
            book_ok = (pm_state.market_end_ts == ws + BAR_SECONDS
                       and pm_state.book_events > 0
                       and now - (pm_state.last_ws_message_at or 0) < 10)
            if not book_ok:
                continue
            side = "UP" if tw > 0 else "DOWN"
            ask = pm_state.up_ask if side == "UP" else pm_state.down_ask
            asz = (pm_state.up_ask_size if side == "UP"
                   else pm_state.down_ask_size)
            if not ask or not asz or not (MIN_ASK <= ask <= WHALE_CAP):
                continue
            if bar.whale and ask < WHALE_LADDER_MIN_ASK:
                continue
            if WHALE_VOL_DELAY_VOL > 0 and tl > WHALE_VOL_DELAY_TL:
                vol = self._ambient_vol()
                if vol is not None and vol >= WHALE_VOL_DELAY_VOL:
                    # this tick would have fired — record the first blocked
                    # fire per bar so the delayed-vs-fired A/B stays measurable
                    if not bar.whale_delayed:
                        bar.whale_delayed = True
                        _event("PF_TE_WHALE_DELAY", bar=bar.ws, side=side,
                               ask=ask, est_bps=round(tw, 3),
                               tl=round(tl, 1), vol=round(vol, 2))
                    continue
            bar.whale_last = now
            await asyncio.to_thread(self._whale_fire, bar, side, ask,
                                    round(tw, 3), round(tl, 1))

    def _whale_fire(self, bar: Bar, side: str, ask: float, est: float,
                    tl: float):
        day = time.strftime("%Y-%m-%d", time.gmtime())
        if self.live_day_pnl.get(day, 0.0) <= -LIVE_MAX_DAILY_LOSS_USD:
            if not self.live_halted:
                self.live_halted = True
                _event("PF_TE_LIVE_HALT", day=day,
                       day_pnl=round(self.live_day_pnl.get(day, 0.0), 2))
            return
        self.live_halted = False
        sh = float(int(min(LIVE_SIZE, LIVE_MAX_ORDER_USD / max(ask, 0.01))))
        if sh < 5 or sh * ask < 1.05:
            return
        if self.live_inflight + sh * ask > LIVE_INFLIGHT_CAP:
            return
        token = (pm_state.token_id_up if side == "UP"
                 else pm_state.token_id_down)
        if not token:
            return
        from engine.clob import post_signed_buy, sign_buy_order
        tick = pm_state.tick_size.get(token, 0.01)
        px = round(min(ask + LIVE_PX_BUFFER, WHALE_CAP), 3)
        t0 = time.time()
        try:
            signed = sign_buy_order(self.clob, token, sh, px, tick_size=tick)
            oid, matched, avg_px, filled = post_signed_buy(self.clob, signed,
                                                           "FAK")
        except Exception as exc:
            _event("PF_TE_LIVE_ERR", bar=bar.ws, err=str(exc)[:160])
            return
        cost = (avg_px or px) * (filled or 0.0)
        if filled:
            self.live_inflight += cost
            bar.whale_spent += cost
            bar.whale.append(dict(side=side, filled=filled, cost=cost,
                                  avg_px=avg_px))
        _event("PF_TE_WHALE_ORDER", bar=bar.ws, side=side, seen_ask=ask,
               req_px=px, req_sh=round(sh, 1), order=oid, matched=matched,
               avg_px=avg_px, filled=filled, cost=round(cost, 4),
               est_bps=est, tl=tl, clip=len(bar.whale),
               spent=round(bar.whale_spent, 2),
               ms=int((time.time() - t0) * 1000))

    async def prewarm_loop(self):
        """Pay each market's ~300ms neg-risk REST lookup OUTSIDE the order
        path. py_clob_client caches per token, and every 5m bar brings fresh
        tokens, so before this loop EVERY live order paid that lookup inside
        sign — the bulk of the measured 344-657ms sign+post (the tick-size
        cache is already patched from the WS at sign time; neg-risk was the
        one REST left). Warm both sides as soon as the WS switches markets."""
        warmed: set = set()
        while _real:
            await asyncio.sleep(1.0)
            if self.clob is None:
                continue
            toks = [t for t in (pm_state.token_id_up, pm_state.token_id_down)
                    if t and t not in warmed]
            if not toks:
                continue
            t0 = time.time()
            ok = 0
            for tok in toks:
                try:
                    await asyncio.to_thread(self.clob.get_neg_risk, tok)
                    warmed.add(tok)
                    ok += 1
                except Exception as exc:
                    log.warning("prewarm %s: %s", str(tok)[:10], exc)
            if len(warmed) > 64:
                warmed.clear()            # old bars' tokens, let them go
            if ok:
                _event("PF_TE_PREWARM", tokens=ok,
                       ms=int((time.time() - t0) * 1000))
            # presign both sides at the band cap: EIP-712 signing is the
            # remaining 100-300ms of the hot path (orders still ~500ms after
            # the REST prewarm). Strong-signal fires (px == MAX_ASK, sizing
            # deterministic) become POST-only. Signed off the hot path here;
            # weaker signals keep the ask-dependent direct sign.
            from engine.clob import sign_buy_order
            sh = float(int(min(LIVE_SIZE, LIVE_MAX_ORDER_USD / MAX_ASK)))
            for tok in toks:
                if tok in self.presigned or sh < 5:
                    continue
                tick = pm_state.tick_size.get(tok, 0.01)
                t1 = time.time()
                try:
                    signed = await asyncio.to_thread(
                        sign_buy_order, self.clob, tok, sh, MAX_ASK, 0, tick)
                    self.presigned[tok] = signed
                    _event("PF_TE_PRESIGN", sh=sh, px=MAX_ASK,
                           ms=int((time.time() - t1) * 1000))
                except Exception as exc:
                    log.warning("presign %s: %s", str(tok)[:10], exc)
            if len(self.presigned) > 8:   # keep only recent bars' tokens
                for k in list(self.presigned)[:-4]:
                    self.presigned.pop(k, None)

    async def hb_loop(self):
        while True:
            await asyncio.sleep(300.0)
            day = time.strftime("%Y-%m-%d", time.gmtime())
            _event("PF_TE_HB", evals=self.n_eval, bets=self.n_bet,
                   day_pnl=round(self.day_pnl.get(day, 0.0), 3),
                   rtds_age=round(rtds_state.age(), 1),
                   rtds_lat=round(rtds_state.lat_ewma, 2),
                   ticks=len(rtds_state.point.get(SYM, {})),
                   twap_ticks=len(rtds_state.twap.get(SYM, {})),
                   book=pm_state.ready)

    async def run(self):
        log.info("twapedge %s %s sym=%s size=%.0f live_size=%.0f thresh=%.2fbps "
                 "eval_tl=%.1fs", "LIVE" if _real else "PAPER", COIN, SYM,
                 SIZE, LIVE_SIZE, THRESH, EVAL_TL)
        _event("PF_TE_START", sym=SYM, size=SIZE, thresh=THRESH,
               thresh_slope=THRESH_SLOPE, thresh_anchor=THRESH_ANCHOR,
               vol_delay_vol=WHALE_VOL_DELAY_VOL,
               vol_delay_tl=WHALE_VOL_DELAY_TL,
               eval_tl=EVAL_TL, paper=not _real, live=_real,
               live_size=LIVE_SIZE if _real else None)
        if _real:
            from engine.clob import (build_clob_client, ensure_approvals,
                                     fetch_usdc_balance)
            self.clob = await asyncio.to_thread(build_clob_client)
            await asyncio.to_thread(ensure_approvals, self.clob)
            bal = await asyncio.to_thread(fetch_usdc_balance, self.clob)
            _event("PF_TE_LIVE_READY", balance=bal,
                   max_order=LIVE_MAX_ORDER_USD,
                   max_daily_loss=LIVE_MAX_DAILY_LOSS_USD,
                   inflight_cap=LIVE_INFLIGHT_CAP)
            log.info("twapedge LIVE ready  balance=$%.2f  caps: order $%.0f, "
                     "daily loss $%.0f", bal or -1, LIVE_MAX_ORDER_USD,
                     LIVE_MAX_DAILY_LOSS_USD)
        if SNIPE_CAP > 0:
            # keep the ended market's book subscribed through the snipe window
            set_post_close_grace(SNIPE_WINDOW_S + 5)
        await asyncio.gather(run_rtds(("crypto_prices_chainlink", TWAP_TOPIC)), run_pm_ws(), self.eval_loop(),
                             self.settle_loop(), self.verify_loop(),
                             self.snipe_loop(), self.warm_loop(),
                             self.prewarm_loop(), self.whale_loop(),
                             self.lock_loop(), self.maker_loop(), self.hb_loop())


def main():
    asyncio.run(TwapEdge().run())


if __name__ == "__main__":
    main()
