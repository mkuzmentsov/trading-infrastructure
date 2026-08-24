"""
LIVE CLOB order engine for the maker_rebate strategy.

Same interface as paper_book.PaperBook (place_quote / cancel_quote /
cancel_all / cancel_entries / resting_quote / resting_entry / bar_inventory /
bar_entry_fills / bar_active / check_fills / observe) so the strategy is
engine-agnostic — but every order is a real signed CLOB order.

Design:
  * place_quote → signed GTC limit, maker by construction: a hard never-cross
    guard clamps a would-cross BUY to ask − tick (SELL to bid + tick) — a
    marketable order is NEVER sent from this engine.
  * Submission / cancellation run as fire-and-forget asyncio tasks (EIP-712
    signing + HTTP round trip are ~100-500ms and must not block the event
    loop). The order is tracked immediately in "pending" state so the
    strategy sees it as resting; the CLOB order id is attached on ack.
  * Fills confirm via the authenticated user WS (user_state.matched_shares /
    avg_price / order_status keyed by the CLOB order id), with a REST
    get_order reconciliation sweep every LIVE_RECONCILE_SECS as fallback.
  * Bracket lifecycle mirrors paper_book: entry fill → resting GTC TP SELL at
    TAKE_PROFIT_PRICE + armed taker stop (FAK sell, reusing the old taker
    bot's exit machinery) when the token's best bid <= STOP_LOSS_PRICE.
    Unexited inventory settles at expiry — accounting happens here; the USDC
    itself arrives via the redemptions.py sweep that main triggers on market
    rotation.
  * Safety: LIVE_MAX_ORDER_USD caps per-order BUY notional;
    LIVE_MAX_DAILY_LOSS_USD is a daily realized-loss kill switch — cancel
    everything, refuse to quote until the next UTC day, log LOUDLY.

Events (same emitter as paper): live_quote_placed (entries carry
bar_start_to_entry_ms), live_quote_cancelled, live_fill, live_tp_placed,
live_tp_fill, live_stop_fired, live_bar_settle, live_daily_summary,
live_kill_switch.
"""
from __future__ import annotations

import asyncio
import math
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from core.btc_ws import btc_state
from config import (
    AGGRESSIVE_EXIT_SLIPPAGE,
    LIVE_MAX_DAILY_LOSS_USD,
    LIVE_MAX_ORDER_USD,
    LIVE_RECONCILE_SECS,
    MAKER_FEE_RATE,
    MAX_FILLS_PER_BAR,
    STOP_LOSS_PRICE,
    TAKE_PROFIT_PRICE,
    log,
)
from engine.paper_book import BracketPosition, _BarState, fee_equivalent
from core.pm_ws import pm_state
from core.telegram import tg
from engine.user_ws import user_state

_TICK = 0.01


def _round_down_tick(price: float) -> float:
    return math.floor(price / _TICK + 1e-9) * _TICK


def _round_up_tick(price: float) -> float:
    return math.ceil(price / _TICK - 1e-9) * _TICK


class ClobAdapter:
    """Thin sync wrapper over clob.py — everything the live engine needs.
    Tests substitute a stub with the same four methods (no network)."""

    def __init__(self, clob) -> None:
        self._clob = clob

    def place_limit(self, token_id: str, side: str, size: float, price: float):
        from engine.clob import place_limit_order
        return place_limit_order(self._clob, token_id, side, size, price)

    def cancel(self, order_id: str) -> bool:
        from engine.clob import cancel_order
        return cancel_order(self._clob, order_id)

    def sell_fak(self, token_id: str, size: float, min_price: float):
        from engine.clob import post_signed_sell_fak, sign_sell_order
        signed = sign_sell_order(self._clob, token_id, size, min_price)
        return post_signed_sell_fak(self._clob, signed)

    def order_status(self, order_id: str):
        from engine.clob import fetch_order_status
        return fetch_order_status(self._clob, order_id)

    def conditional_balance(self, token_id: str) -> float:
        """Sellable shares of a CTF token per the exchange (raw 1e6 units).
        The chain credits fills with a lag (and sometimes a dust haircut), so
        this is the ONLY truth for how many shares a SELL may reference."""
        from py_clob_client_v2.clob_types import AssetType, BalanceAllowanceParams
        r = self._clob.get_balance_allowance(
            BalanceAllowanceParams(asset_type=AssetType.CONDITIONAL, token_id=token_id)
        )
        return float(r.get("balance", 0) or 0) / 1e6

    def collateral_balance(self) -> float:
        """USDC cash on the exchange (raw 1e6 units)."""
        from py_clob_client_v2.clob_types import AssetType, BalanceAllowanceParams
        r = self._clob.get_balance_allowance(
            BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
        )
        return float(r.get("balance", 0) or 0) / 1e6


@dataclass
class LiveOrder:
    order_id: str            # local id ("live-<ms>-<seq>") — what the strategy sees
    condition_id: str
    token_id: str
    direction: str           # "UP" | "DOWN"
    side: str                # "BUY" | "SELL"
    price: float
    size: float
    placed_ts: float
    spot_at_place: float
    exchange_id: str = ""    # CLOB order id, attached on submit ack
    filled: float = 0.0
    purpose: str = "quote"   # "quote" | "entry" | "tp"
    pos_id: int = 0
    state: str = "pending"   # pending | live | cancelled | dead
    cancel_requested: bool = False
    submit_ack_ts: float = 0.0
    size_clamped_to_min: bool = False

    @property
    def remaining(self) -> float:
        return max(0.0, self.size - self.filled)


class LiveBook:
    engine = "live"

    def __init__(self) -> None:
        self.orders: dict[str, LiveOrder] = {}       # local_id → open order
        self._zombies: dict[str, LiveOrder] = {}     # exchange_id → cancelled order (late fills)
        self._by_exchange: dict[str, str] = {}       # exchange_id → local_id
        self._order_seq: int = 0
        self._bar: _BarState | None = None
        self._adapter = None                          # ClobAdapter (or test stub)
        self._emit = None                             # main._write_training_event
        self._tasks: set = set()
        self._stop_pending: set[int] = set()          # pos_ids with an in-flight stop
        self._tp_retry_at: dict[int, float] = {}      # pos_id → earliest next TP submit
        self._tp_size_cap: dict[int, float] = {}      # pos_id → exchange-confirmed sellable shares
        self._day: str = ""
        self._daily = self._fresh_daily()
        self._halted_day: str = ""
        self._halt_log_ts: float = 0.0
        self._last_reconcile_ts: float = 0.0

    # ── wiring ────────────────────────────────────────────────────────────────
    def set_client(self, adapter) -> None:
        self._adapter = adapter

    def set_emitter(self, emit) -> None:
        self._emit = emit

    def _event(self, event_type: str, **payload) -> None:
        if self._emit is not None:
            try:
                self._emit(event_type, **payload)
            except Exception as exc:
                log.warning("Live event emit failed (%s): %s", event_type, exc)

    @staticmethod
    def _fresh_daily() -> dict:
        return {
            "bars_settled": 0,
            "fills": 0,
            "filled_shares": 0.0,
            "locked_pair_pnl": 0.0,
            "directional_pnl": 0.0,
            "bracket_pnl": 0.0,
            "taker_fees": 0.0,
            "fee_equivalent_sum": 0.0,
            "gross_pnl": 0.0,
            "realized_pnl": 0.0,
        }

    @staticmethod
    def _day_of(now: float) -> str:
        return datetime.fromtimestamp(now, tz=timezone.utc).strftime("%Y-%m-%d")

    def _roll_daily(self, now: float) -> None:
        day = self._day_of(now)
        if day != self._day:
            self._day = day
            self._daily = self._fresh_daily()

    def halted(self, now: float) -> bool:
        return self._halted_day == self._day_of(now)

    def daily_realized_pnl(self, now: float) -> float:
        self._roll_daily(now)
        return self._daily["realized_pnl"]

    # ── task plumbing ─────────────────────────────────────────────────────────
    def _spawn(self, coro, name: str) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            log.error("LIVE task %s dropped — no running event loop", name)
            coro.close()
            return
        task = loop.create_task(coro, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def flush(self, timeout: float = 10.0) -> None:
        """Await all in-flight submit/cancel/stop tasks (tests + roll hook)."""
        deadline = time.time() + timeout
        while self._tasks and time.time() < deadline:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    # ── daily-loss kill switch ────────────────────────────────────────────────
    def _register_realized(self, pnl: float, now: float) -> None:
        self._roll_daily(now)
        self._daily["realized_pnl"] += pnl
        realized = self._daily["realized_pnl"]
        if (
            LIVE_MAX_DAILY_LOSS_USD > 0
            and realized <= -LIVE_MAX_DAILY_LOSS_USD
            and self._halted_day != self._day
        ):
            self._halted_day = self._day
            for line in (
                "#" * 72,
                "###  LIVE DAILY-LOSS KILL SWITCH FIRED  ###",
                f"###  realized today = ${realized:+.2f}  limit = ${LIVE_MAX_DAILY_LOSS_USD:.2f}  ###",
                "###  cancelling ALL orders — quoting HALTED until next UTC day  ###",
                "#" * 72,
            ):
                log.error(line)
            self._event(
                "live_kill_switch",
                date=self._day,
                realized_pnl=round(realized, 4),
                limit_usd=LIVE_MAX_DAILY_LOSS_USD,
                live=True,
            )
            try:
                tg(
                    f"🛑 <b>LIVE KILL SWITCH</b>\n"
                    f"Daily realized ${realized:+.2f} breached −${LIVE_MAX_DAILY_LOSS_USD:.2f}.\n"
                    f"All orders cancelled; quoting halted until next UTC day."
                )
            except Exception:
                pass
            self.cancel_all("daily_loss_kill_switch", now)

    # ── bar lifecycle ─────────────────────────────────────────────────────────
    def observe(self, now: float) -> None:
        """Track the active bar; settle the previous one when it expires or
        the market rotates. Call once per loop tick, before fill checks."""
        bar = self._bar
        if bar is not None and (
            now >= bar.end_ts or (pm_state.condition_id and pm_state.condition_id != bar.condition_id)
        ):
            self._settle_bar(bar, now)
            self._bar = None
            bar = None

        if (
            bar is None
            and pm_state.condition_id
            and pm_state.market_end_ts > 0
            and now < pm_state.market_end_ts
        ):
            self._bar = _BarState(
                condition_id=pm_state.condition_id,
                question=pm_state.question,
                start_ts=pm_state.market_start_ts,
                end_ts=pm_state.market_end_ts,
                bar_open=btc_state.bar_open,
                token_id_up=pm_state.token_id_up,
                token_id_down=pm_state.token_id_down,
            )
            # Drop zombies from bars before the previous one — their late
            # fills can no longer be attributed to a tracked bar anyway.
            self._zombies = {
                eid: o for eid, o in self._zombies.items()
                if o.condition_id == pm_state.condition_id
            }

        if self._bar is not None:
            if self._bar.bar_open <= 0 and btc_state.bar_open > 0:
                self._bar.bar_open = btc_state.bar_open
            if btc_state.current_price > 0 and now < self._bar.end_ts:
                self._bar.last_price = btc_state.current_price
                self._bar.last_price_ts = now

    def _settle_bar(self, bar: _BarState, now: float) -> None:
        self.cancel_all("bar_end", now)

        up_sh, dn_sh = bar.shares["UP"], bar.shares["DOWN"]
        up_cost, dn_cost = bar.cost["UP"], bar.cost["DOWN"]
        avg_up = up_cost / up_sh if up_sh > 0 else 0.0
        avg_dn = dn_cost / dn_sh if dn_sh > 0 else 0.0

        outcome = None
        if bar.bar_open > 0 and bar.last_price > 0:
            outcome = "UP" if bar.last_price > bar.bar_open else "DOWN"

        bracket_pnl = 0.0
        expiry_pnl = 0.0
        taker_fee_sum = 0.0
        positions_payload = []
        for pos in bar.positions:
            if pos.exit_kind is None:
                remaining = pos.remaining
                pos.exit_kind = "expiry"
                if remaining > 1e-9:
                    if outcome is not None:
                        payout = 1.0 if pos.direction == outcome else 0.0
                        pos.exit_price = payout
                        pnl = remaining * (payout - pos.entry_price)
                        pos.realized_pnl += pnl
                        expiry_pnl += pnl
                    else:
                        log.warning(
                            "LIVE bracket settle with UNKNOWN outcome — pnl of %.2f residual shares dropped  market=%s",
                            remaining, bar.condition_id[:16],
                        )
            bracket_pnl += pos.realized_pnl
            taker_fee_sum += pos.taker_fee
            positions_payload.append(
                {
                    "pos_id": pos.pos_id,
                    "direction": pos.direction,
                    "size": round(pos.size, 4),
                    "entry_price": round(pos.entry_price, 4),
                    "exit_kind": pos.exit_kind,
                    "exit_price": round(pos.exit_price, 4) if pos.exit_price is not None else None,
                    "tp_filled": round(pos.tp_filled, 4),
                    "taker_fee": round(pos.taker_fee, 6),
                    "realized_pnl": round(pos.realized_pnl, 4),
                    "win": pos.realized_pnl > 0,
                }
            )

        # Legacy one/two_sided inventory settle (bracket exits already
        # decremented shares — mirror paper's guard).
        locked_pair_pnl = 0.0
        directional_pnl = 0.0
        if not bar.positions:
            matched = min(up_sh, dn_sh)
            locked_pair_pnl = matched * (1.0 - avg_up - avg_dn) if matched > 0 else 0.0
            res_up = up_sh - matched
            res_dn = dn_sh - matched
            if outcome is not None:
                if res_up > 0:
                    directional_pnl += res_up * ((1.0 if outcome == "UP" else 0.0) - avg_up)
                if res_dn > 0:
                    directional_pnl += res_dn * ((1.0 if outcome == "DOWN" else 0.0) - avg_dn)
            elif res_up > 0 or res_dn > 0:
                log.warning(
                    "LIVE settle with UNKNOWN outcome — directional pnl of %.2f/%.2f residual shares dropped  market=%s",
                    res_up, res_dn, bar.condition_id[:16],
                )
        else:
            matched = 0.0

        gross = locked_pair_pnl + directional_pnl + bracket_pnl
        if up_sh > 0 or dn_sh > 0 or bar.positions:
            log.info(
                "LIVE_BAR_SETTLE  market=%s outcome=%s up=%.1f@%.3f down=%.1f@%.3f locked=%.4f dir=%.4f bracket=%.4f taker_fees=%.4f fee_eq=%.4f gross=%.4f exits=%s",
                bar.condition_id[:16], outcome, up_sh, avg_up, dn_sh, avg_dn,
                locked_pair_pnl, directional_pnl, bracket_pnl, taker_fee_sum,
                bar.fee_equivalent_sum, gross,
                [p["exit_kind"] for p in positions_payload] or "-",
            )
        self._event(
            "live_bar_settle",
            live_condition_id=bar.condition_id,
            live_question=bar.question,
            outcome=outcome,
            settle_price=round(bar.last_price, 4),
            settle_bar_open=round(bar.bar_open, 4),
            up_shares=round(up_sh, 4),
            up_avg_price=round(avg_up, 4),
            down_shares=round(dn_sh, 4),
            down_avg_price=round(avg_dn, 4),
            matched_pairs=round(matched, 4),
            locked_pair_pnl=round(locked_pair_pnl, 4),
            directional_pnl=round(directional_pnl, 4),
            bracket_pnl=round(bracket_pnl, 4),
            taker_fee_sum=round(taker_fee_sum, 6),
            positions=positions_payload,
            fee_equivalent_sum=round(bar.fee_equivalent_sum, 6),
            gross_pnl=round(gross, 4),
            fills=bar.fills,
            live=True,
        )

        # Equity snapshot (cash + open position value) — the number the user
        # tracks; cash alone swings every bar as orders fill and settle.
        self._spawn(self._log_equity(now), "live_equity_snapshot")

        self._roll_daily(now)
        d = self._daily
        d["bars_settled"] += 1
        d["fills"] += bar.fills
        d["filled_shares"] += up_sh + dn_sh
        d["locked_pair_pnl"] += locked_pair_pnl
        d["directional_pnl"] += directional_pnl
        d["bracket_pnl"] += bracket_pnl
        d["taker_fees"] += taker_fee_sum
        d["fee_equivalent_sum"] += bar.fee_equivalent_sum
        d["gross_pnl"] += gross
        self._event(
            "live_daily_summary",
            date=self._day,
            bars_settled=d["bars_settled"],
            fills=d["fills"],
            filled_shares=round(d["filled_shares"], 4),
            locked_pair_pnl=round(d["locked_pair_pnl"], 4),
            directional_pnl=round(d["directional_pnl"], 4),
            bracket_pnl=round(d["bracket_pnl"], 4),
            taker_fees=round(d["taker_fees"], 6),
            fee_equivalent_sum=round(d["fee_equivalent_sum"], 6),
            gross_pnl=round(d["gross_pnl"], 4),
            realized_pnl=round(d["realized_pnl"], 4),
            live=True,
        )
        # Expiry remainders are realized at settle (TP/stop fills were
        # registered at fill time; legacy inventory realizes here too).
        self._register_realized(expiry_pnl + locked_pair_pnl + directional_pnl, now)

    # ── strategy-facing queries (same as paper) ───────────────────────────────
    def bar_inventory(self, direction: str) -> float:
        return self._bar.shares.get(direction, 0.0) if self._bar else 0.0

    def bar_active(self) -> bool:
        return self._bar is not None and self._bar.condition_id == pm_state.condition_id

    def resting_quote(self, direction: str) -> LiveOrder | None:
        for o in self.orders.values():
            if o.direction == direction and o.purpose == "quote":
                return o
        return None

    def resting_entry(self, direction: str) -> LiveOrder | None:
        for o in self.orders.values():
            if o.direction == direction and o.purpose == "entry":
                return o
        return None

    def bar_entry_fills(self, direction: str | None = None) -> int:
        if self._bar is None:
            return 0
        if direction is None:
            return self._bar.entry_fills
        return self._bar.entry_fills_by_side.get(direction, 0)

    def cancel_entries(self, reason: str, now: float, direction: str | None = None) -> None:
        for order_id, order in list(self.orders.items()):
            if order.purpose == "entry" and (direction is None or order.direction == direction):
                self.cancel_quote(order_id, reason, now)

    # ── order placement / cancellation ────────────────────────────────────────
    def place_quote(
        self,
        direction: str,
        price: float,
        size: float,
        now: float,
        side: str = "BUY",
        purpose: str = "quote",
        pos_id: int = 0,
        size_clamped_to_min: bool = False,
    ) -> str | None:
        if self._adapter is None:
            log.error("LIVE place_quote refused — no CLOB adapter wired")
            return None
        if self.halted(now):
            if now - self._halt_log_ts > 60:
                self._halt_log_ts = now
                log.error(
                    "LIVE quoting HALTED (daily-loss kill switch, day=%s) — order suppressed",
                    self._halted_day,
                )
            return None
        if not self.bar_active():
            return None
        bar = self._bar
        token_id = bar.token_id_up if direction == "UP" else bar.token_id_down
        if not token_id or not (0 < price < 1) or size <= 0:
            return None

        # Hard never-cross guard: this engine NEVER sends a marketable order.
        bid, ask = (
            (pm_state.up_bid, pm_state.up_ask)
            if direction == "UP"
            else (pm_state.down_bid, pm_state.down_ask)
        )
        orig_price = price
        if side == "BUY" and 0 < ask < 1 and price >= ask:
            price = _round_down_tick(ask - _TICK)
        elif side == "SELL" and 0 < bid < 1 and price <= bid:
            price = _round_up_tick(bid + _TICK)
        if not (0 < price < 1):
            log.warning(
                "LIVE quote suppressed — never-cross clamp left no room  %s %s want=%.3f bid=%.3f ask=%.3f",
                direction, side, orig_price, bid, ask,
            )
            return None
        if abs(price - orig_price) > 1e-9:
            log.info(
                "LIVE never-cross clamp  %s %s %.3f → %.3f  (bid=%.3f ask=%.3f)",
                direction, side, orig_price, price, bid, ask,
            )

        # Per-order notional hard cap (BUY only — SELLs reduce risk).
        if side == "BUY" and LIVE_MAX_ORDER_USD > 0 and price * size > LIVE_MAX_ORDER_USD:
            capped = math.floor((LIVE_MAX_ORDER_USD / price) * 100) / 100.0
            log.warning(
                "LIVE order clamped by LIVE_MAX_ORDER_USD  %s BUY %.2f → %.2f shares @ %.3f (cap=$%.2f)",
                direction, size, capped, price, LIVE_MAX_ORDER_USD,
            )
            size = capped
            if size < 1.0:
                log.warning("LIVE order suppressed — size below 1 share after notional cap")
                return None

        self._order_seq += 1
        order_id = f"live-{int(now * 1000)}-{self._order_seq}"
        order = LiveOrder(
            order_id=order_id,
            condition_id=bar.condition_id,
            token_id=token_id,
            direction=direction,
            side=side,
            price=price,
            size=size,
            placed_ts=now,
            spot_at_place=btc_state.current_price,
            purpose=purpose,
            pos_id=pos_id,
            size_clamped_to_min=size_clamped_to_min,
        )
        self.orders[order_id] = order
        self._spawn(self._submit(order), f"live_submit_{order_id}")
        return order_id

    async def _submit(self, order: LiveOrder) -> None:
        try:
            eid = await asyncio.to_thread(
                self._adapter.place_limit, order.token_id, order.side, order.size, order.price
            )
        except Exception as exc:
            log.error(
                "LIVE order submit raised  %s %s %.1f @ %.3f  purpose=%s: %s",
                order.direction, order.side, order.size, order.price, order.purpose, exc,
            )
            order.state = "dead"
            self.orders.pop(order.order_id, None)
            return
        if not eid:
            log.error(
                "LIVE order submit FAILED (no order id)  %s %s %.1f @ %.3f  purpose=%s",
                order.direction, order.side, order.size, order.price, order.purpose,
            )
            order.state = "dead"
            self.orders.pop(order.order_id, None)
            if order.purpose == "tp" and order.pos_id is not None:
                # Typical cause: the exchange hasn't credited the entry's CTF
                # shares yet (chain lag) or credited slightly fewer than the
                # fill (dust haircut). Learn the sellable balance so the next
                # attempt (3s backoff in _place_tp) sizes to what exists.
                try:
                    bal = await asyncio.to_thread(
                        self._adapter.conditional_balance, order.token_id
                    )
                    if bal > 0:
                        self._tp_size_cap[order.pos_id] = bal
                        log.info(
                            "LIVE TP size capped to exchange balance  pos=%d  %.4f shares",
                            order.pos_id, bal,
                        )
                except Exception as exc:
                    log.debug("LIVE conditional balance fetch failed: %s", exc)
            return

        order.exchange_id = str(eid)
        order.submit_ack_ts = time.time()
        if order.state == "pending":
            order.state = "live"
        self._by_exchange[order.exchange_id] = order.order_id

        extra: dict = {}
        if order.purpose == "entry" and self._bar is not None and self._bar.start_ts > 0:
            ms = (order.submit_ack_ts - self._bar.start_ts) * 1000.0
            extra["bar_start_to_entry_ms"] = round(ms, 1)
            log.info(
                "LIVE entry on book  %s BUY %.1f @ %.3f  bar_start_to_entry_ms=%.0f  order=%s clob=%s",
                order.direction, order.size, order.price, ms, order.order_id, order.exchange_id,
            )
        if order.size_clamped_to_min:
            extra["size_clamped_to_min"] = True

        event_type = "live_tp_placed" if order.purpose == "tp" else "live_quote_placed"
        log.info(
            "%s  %s %s %.1f @ %.3f  purpose=%s  order=%s clob=%s",
            event_type.upper(), order.direction, order.side, order.size, order.price,
            order.purpose, order.order_id, order.exchange_id,
        )
        self._event(
            event_type,
            order_id=order.order_id,
            exchange_order_id=order.exchange_id,
            direction=order.direction,
            token_id=order.token_id,
            side=order.side,
            price=round(order.price, 4),
            size=order.size,
            purpose=order.purpose,
            pos_id=order.pos_id,
            live=True,
            **extra,
        )

        # Cancelled while the submit was in flight — undo on the exchange.
        if order.cancel_requested:
            self._zombies[order.exchange_id] = order
            await self._do_cancel(order, "cancel_requested_during_submit")

    async def _log_equity(self, now: float) -> None:
        """Emit a live_equity event: exchange cash + open position value."""
        try:
            cash = await asyncio.to_thread(self._adapter.collateral_balance)
        except Exception as exc:
            log.debug("LIVE equity: collateral fetch failed: %s", exc)
            return
        pos_value = 0.0
        try:
            import requests
            from config import DATA_API, POLYMARKET_FUNDER

            def _positions() -> float:
                r = requests.get(
                    f"{DATA_API}/positions",
                    params={"user": POLYMARKET_FUNDER, "sizeThreshold": "0.01"},
                    timeout=10,
                )
                r.raise_for_status()
                return sum(float(p.get("currentValue") or 0) for p in r.json())

            pos_value = await asyncio.to_thread(_positions)
        except Exception as exc:
            log.debug("LIVE equity: positions fetch failed: %s", exc)
        equity = cash + pos_value
        log.info(
            "LIVE_EQUITY  cash=%.2f positions=%.2f equity=%.2f", cash, pos_value, equity
        )
        self._event(
            "live_equity",
            cash=round(cash, 2),
            positions_value=round(pos_value, 2),
            equity=round(equity, 2),
            live=True,
        )

    async def _do_cancel(self, order: LiveOrder, reason: str) -> None:
        try:
            ok = await asyncio.to_thread(self._adapter.cancel, order.exchange_id)
        except Exception as exc:
            ok = False
            log.warning("LIVE cancel raised  clob=%s: %s", order.exchange_id, exc)
        if not ok:
            log.warning(
                "LIVE cancel NOT confirmed  clob=%s reason=%s — order may still fill (tracked as zombie)",
                order.exchange_id, reason,
            )

    def cancel_quote(self, order_id: str, reason: str, now: float) -> None:
        order = self.orders.pop(order_id, None)
        if order is None:
            return
        order.cancel_requested = True
        if order.purpose == "tp" and self._bar is not None:
            for pos in self._bar.positions:
                if pos.pos_id == order.pos_id and pos.tp_order_id == order_id:
                    pos.tp_order_id = None
        if order.exchange_id:
            order.state = "cancelled"
            self._zombies[order.exchange_id] = order
            self._spawn(self._do_cancel(order, reason), f"live_cancel_{order.exchange_id[:12]}")
        else:
            # Still pending submit — _submit will cancel on ack.
            order.state = "cancelled"
        log.info(
            "LIVE_QUOTE_CANCELLED  %s %s %.1f @ %.3f  purpose=%s reason=%s  order=%s clob=%s",
            order.direction, order.side, order.remaining, order.price,
            order.purpose, reason, order_id, order.exchange_id or "-",
        )
        self._event(
            "live_quote_cancelled",
            order_id=order_id,
            exchange_order_id=order.exchange_id,
            direction=order.direction,
            token_id=order.token_id,
            side=order.side,
            price=round(order.price, 4),
            remaining=round(order.remaining, 4),
            filled=round(order.filled, 4),
            age_secs=round(now - order.placed_ts, 2),
            purpose=order.purpose,
            reason=reason,
            live=True,
        )

    def cancel_all(self, reason: str, now: float) -> None:
        for order_id in list(self.orders.keys()):
            self.cancel_quote(order_id, reason, now)

    # ── fills ─────────────────────────────────────────────────────────────────
    def check_fills(self, now: float) -> None:
        """Drain user_ws-confirmed fills into the book, run the periodic REST
        reconciliation, keep TPs resting, and arm/fire taker stops."""
        for order in list(self.orders.values()) + list(self._zombies.values()):
            eid = order.exchange_id
            if not eid:
                continue
            matched = user_state.matched_shares.get(eid, 0.0)
            delta = matched - order.filled
            if delta > 1e-9 and order.remaining > 1e-9:
                fill = min(delta, order.remaining)
                price = user_state.avg_price.get(eid, 0.0)
                if not (0 < price < 1):
                    price = order.price
                # Maker orders can never fill worse than their limit. Polymarket
                # reports cross-token matches in the complement's terms (a DOWN
                # buy resting at 0.48 shows price 0.52) — clamp to the limit so
                # PnL/kill-switch accounting uses what we actually paid.
                if order.side == "BUY":
                    price = min(price, order.price)
                else:
                    price = max(price, order.price)
                self._record_fill(order, fill, price, "user_ws", now)
            status = user_state.order_status.get(eid, "")
            if status == "cancelled" and order.order_id in self.orders and not order.cancel_requested:
                log.info(
                    "LIVE order cancelled EXTERNALLY  clob=%s  %s %s %.1f @ %.3f",
                    eid, order.direction, order.side, order.remaining, order.price,
                )
                self.cancel_quote(order.order_id, "cancelled_externally", now)

        if (
            self._adapter is not None
            and LIVE_RECONCILE_SECS > 0
            and now - self._last_reconcile_ts >= LIVE_RECONCILE_SECS
        ):
            self._last_reconcile_ts = now
            self._spawn(self._reconcile_rest(now), "live_rest_reconcile")

        self._check_stops(now)

    async def _reconcile_rest(self, now: float) -> None:
        """REST fallback: poll order status for resting orders the user WS may
        have missed (every LIVE_RECONCILE_SECS)."""
        for order in list(self.orders.values()):
            if not order.exchange_id or now - order.placed_ts < 5.0:
                continue
            try:
                info = await asyncio.to_thread(self._adapter.order_status, order.exchange_id)
            except Exception as exc:
                log.debug("LIVE reconcile fetch failed  clob=%s: %s", order.exchange_id, exc)
                continue
            if not isinstance(info, dict):
                continue
            status = str(info.get("status", "")).lower()
            try:
                size_matched = float(info.get("size_matched") or 0.0)
            except (TypeError, ValueError):
                size_matched = 0.0
            if size_matched > order.filled + 1e-9 and order.remaining > 1e-9:
                fill = min(size_matched - order.filled, order.remaining)
                log.warning(
                    "LIVE REST reconcile found missed fill  clob=%s  filled=%.4f ws=%.4f",
                    order.exchange_id, size_matched, order.filled,
                )
                self._record_fill(order, fill, order.price, "rest_reconcile", time.time())
            if status in ("canceled", "cancelled", "expired") and order.order_id in self.orders:
                self.orders.pop(order.order_id, None)
                log.info("LIVE REST reconcile: order gone on exchange  clob=%s status=%s", order.exchange_id, status)

    def _record_fill(self, order: LiveOrder, size: float, price: float, basis: str, now: float) -> None:
        bar = self._bar
        if bar is None or order.condition_id != bar.condition_id:
            order.filled += size
            log.warning(
                "LIVE stale-bar fill ignored for accounting  %s %s %.1f @ %.3f  order=%s",
                order.direction, order.side, size, price, order.order_id,
            )
            return
        if order.side == "SELL":
            self._record_tp_fill(order, size, price, basis, now)
            return
        order.filled += size
        bar.shares[order.direction] += size
        bar.cost[order.direction] += size * price
        fee_eq = fee_equivalent(size, price)
        bar.fee_equivalent_sum += fee_eq
        bar.fills += 1
        log.info(
            "LIVE_FILL  %s BUY %.1f @ %.3f  basis=%s fee_eq=%.5f  inv_up=%.1f inv_down=%.1f  order=%s clob=%s",
            order.direction, size, price, basis, fee_eq,
            bar.shares["UP"], bar.shares["DOWN"], order.order_id, order.exchange_id,
        )
        self._event(
            "live_fill",
            order_id=order.order_id,
            exchange_order_id=order.exchange_id,
            direction=order.direction,
            token_id=order.token_id,
            side="BUY",
            price=round(price, 4),
            size=round(size, 4),
            fill_basis=basis,
            purpose=order.purpose,
            fee_equivalent=round(fee_eq, 6),
            bar_inventory_up=round(bar.shares["UP"], 4),
            bar_inventory_down=round(bar.shares["DOWN"], 4),
            live=True,
        )
        if order.remaining <= 1e-9:
            self.orders.pop(order.order_id, None)
            self._zombies.pop(order.exchange_id, None)
        if order.purpose == "entry":
            self._open_bracket(order, size, price, now)

    # ── bracket lifecycle (mirrors paper) ─────────────────────────────────────
    def _find_position(self, pos_id: int) -> BracketPosition | None:
        if self._bar is None:
            return None
        for pos in self._bar.positions:
            if pos.pos_id == pos_id:
                return pos
        return None

    def _place_tp(self, pos: BracketPosition, now: float) -> None:
        if not pos.open or pos.tp_order_id in self.orders:
            return
        if now < self._tp_retry_at.get(pos.pos_id, 0.0):
            return
        # Never reference more shares than the exchange says are sellable:
        # fills credit on-chain with a lag (and occasionally a dust haircut,
        # e.g. 9.9946 credited for a 10-share fill), and a SELL for more than
        # the credited balance is rejected outright.
        size = pos.remaining
        cap = self._tp_size_cap.get(pos.pos_id)
        if cap is not None:
            size = min(size, cap)
        size = math.floor(size * 100) / 100.0
        if size <= 0:
            return
        self._tp_retry_at[pos.pos_id] = now + 3.0
        order_id = self.place_quote(
            pos.direction, pos.tp_price, size, now,
            side="SELL", purpose="tp", pos_id=pos.pos_id,
        )
        if order_id is not None:
            pos.tp_order_id = order_id

    def _open_bracket(self, order: LiveOrder, size: float, price: float, now: float) -> None:
        bar = self._bar
        bar.entry_fills += 1
        bar.entry_fills_by_side[order.direction] = (
            bar.entry_fills_by_side.get(order.direction, 0) + 1
        )
        bar.pos_seq += 1
        pos = BracketPosition(
            pos_id=bar.pos_seq,
            direction=order.direction,
            token_id=order.token_id,
            size=size,
            entry_price=price,
            tp_price=TAKE_PROFIT_PRICE,
            stop_price=STOP_LOSS_PRICE,
        )
        bar.positions.append(pos)
        if bar.entry_fills_by_side[order.direction] >= MAX_FILLS_PER_BAR:
            self.cancel_entries("max_fills_per_bar", now, direction=order.direction)
        self._place_tp(pos, now)

    def _record_tp_fill(self, order: LiveOrder, size: float, price: float, basis: str, now: float) -> None:
        bar = self._bar
        pos = self._find_position(order.pos_id)
        if pos is None or pos.exit_kind is not None:
            order.filled += size
            self.orders.pop(order.order_id, None)
            return
        fill = min(size, pos.remaining)
        if fill <= 0:
            return
        order.filled += fill
        pos.tp_filled += fill
        realized = fill * (price - pos.entry_price)
        pos.realized_pnl += realized
        fee_eq = fee_equivalent(fill, price)
        bar.fee_equivalent_sum += fee_eq
        bar.fills += 1
        bar.shares[pos.direction] -= fill
        bar.cost[pos.direction] -= fill * pos.entry_price
        if pos.remaining <= 1e-9:
            pos.exit_kind = "tp"
            pos.exit_price = price
            pos.tp_order_id = None
            self.orders.pop(order.order_id, None)
            self._zombies.pop(order.exchange_id, None)
        log.info(
            "LIVE_TP_FILL  %s SELL %.1f @ %.3f  basis=%s fee_eq=%.5f realized=%.4f remaining=%.1f  pos=%d",
            pos.direction, fill, price, basis, fee_eq, realized, pos.remaining, pos.pos_id,
        )
        self._event(
            "live_tp_fill",
            order_id=order.order_id,
            exchange_order_id=order.exchange_id,
            pos_id=pos.pos_id,
            direction=pos.direction,
            token_id=order.token_id,
            side="SELL",
            price=round(price, 4),
            size=round(fill, 4),
            fill_basis=basis,
            fee_equivalent=round(fee_eq, 6),
            entry_price=round(pos.entry_price, 4),
            realized_pnl=round(realized, 4),
            remaining=round(pos.remaining, 4),
            live=True,
        )
        self._register_realized(realized, now)

    def _check_stops(self, now: float) -> None:
        bar = self._bar
        if bar is None or not self.bar_active():
            return
        for pos in bar.positions:
            if not pos.open:
                continue
            # Keep the TP resting (re-place if it was swept by cancel_all).
            if pos.tp_order_id not in self.orders and pos.pos_id not in self._stop_pending:
                pos.tp_order_id = None
                self._place_tp(pos, now)
            if pos.stop_price <= 0:
                continue
            best_bid = pm_state.up_bid if pos.direction == "UP" else pm_state.down_bid
            if not (0 < best_bid < 1) or best_bid > pos.stop_price:
                continue
            if pos.pos_id in self._stop_pending:
                continue
            self._stop_pending.add(pos.pos_id)
            self._spawn(self._fire_stop(pos, best_bid), f"live_stop_{pos.pos_id}")

    async def _fire_stop(self, pos: BracketPosition, best_bid: float) -> None:
        try:
            now = time.time()
            # Pull the resting TP first so the shares are free for the taker sell.
            if pos.tp_order_id and pos.tp_order_id in self.orders:
                tp_order = self.orders.pop(pos.tp_order_id)
                pos.tp_order_id = None
                tp_order.cancel_requested = True
                tp_order.state = "cancelled"
                if tp_order.exchange_id:
                    self._zombies[tp_order.exchange_id] = tp_order
                    await self._do_cancel(tp_order, "stop_fired")
            remaining = pos.remaining
            if remaining <= 1e-9 or pos.exit_kind is not None:
                return
            floor_price = max(0.01, round(best_bid - AGGRESSIVE_EXIT_SLIPPAGE, 2))
            try:
                order_id, matched = await asyncio.to_thread(
                    self._adapter.sell_fak, pos.token_id, remaining, floor_price
                )
            except Exception as exc:
                log.warning("LIVE stop FAK raised — will retry next tick  pos=%d: %s", pos.pos_id, exc)
                return
            if not order_id or not matched:
                log.info(
                    "LIVE stop FAK unfilled — will retry  pos=%d bid=%.3f floor=%.3f",
                    pos.pos_id, best_bid, floor_price,
                )
                return
            # Brief user_ws reconciliation for the actual fill size/price.
            deadline = time.time() + 3.0
            shares = 0.0
            price = 0.0
            while time.time() < deadline:
                shares = user_state.matched_shares.get(order_id, 0.0)
                price = user_state.avg_price.get(order_id, 0.0)
                if shares > 0 and price > 0:
                    break
                await asyncio.sleep(0.1)
            shares = shares or remaining
            # FAK can't fill below its floor; clamp complement-flipped reports.
            price = max(price, floor_price) if 0 < price < 1 else floor_price
            taker_fee = shares * MAKER_FEE_RATE * price * (1.0 - price)
            realized = shares * (price - pos.entry_price) - taker_fee
            pos.taker_fee += taker_fee
            pos.realized_pnl += realized
            pos.exit_kind = "stop"
            pos.exit_price = price
            bar = self._bar
            if bar is not None and pos in bar.positions:
                bar.shares[pos.direction] -= shares
                bar.cost[pos.direction] -= shares * pos.entry_price
            log.info(
                "LIVE_STOP_FIRED  %s SELL %.1f @ %.3f (stop<=%.2f)  taker_fee=%.5f realized=%.4f  pos=%d clob=%s",
                pos.direction, shares, price, pos.stop_price, taker_fee, pos.realized_pnl,
                pos.pos_id, order_id,
            )
            self._event(
                "live_stop_fired",
                exchange_order_id=order_id,
                pos_id=pos.pos_id,
                direction=pos.direction,
                token_id=pos.token_id,
                stop_price=round(pos.stop_price, 4),
                exec_price=round(price, 4),
                size=round(shares, 4),
                entry_price=round(pos.entry_price, 4),
                taker_fee=round(taker_fee, 6),
                realized_pnl=round(pos.realized_pnl, 4),
                live=True,
            )
            self._register_realized(realized, time.time())
        finally:
            self._stop_pending.discard(pos.pos_id)


live_book = LiveBook()
