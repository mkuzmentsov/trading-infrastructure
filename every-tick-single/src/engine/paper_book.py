"""
Paper fill engine for the maker-rebate quoting strategy.

Simulates resting maker BUY quotes against the LIVE Polymarket feed:

- Fill rule (conservative): a resting BUY at price P fills when a trade
  prints at price <= P on that token (fill_basis="trade_print"), fill size
  capped by the printed size. If the trade feed is silent (no
  last_trade_price event within PAPER_TRADE_FEED_TIMEOUT_SECS), fall back to
  book-cross: best_ask <= P for one observation (fill_basis="book_cross"),
  capped by the observed top-of-book ask size.
- Resting maker SELLs (bracket TP) mirror the rule: a SELL at price P fills
  when a trade prints at >= P (book-cross fallback: best_bid >= P).
- Bracket positions (entry-purpose fills) carry a conditional taker stop:
  when the token's best bid <= stop_price, the remaining size is sold at the
  observed best bid and charged the taker fee size × feeRate × p(1−p).
- At bar expiry all filled inventory settles at the actual outcome (1 for the
  winning side, 0 for the loser), determined from the settlement-aligned spot
  feed (btc_state: last observed price before bar end vs bar_open).
- NO CLOB calls ever happen here — everything is in-memory + jsonl events.

Events (via the training-event log): paper_quote_placed,
paper_quote_cancelled, paper_fill, paper_tp_placed, paper_tp_fill,
paper_stop_fired, paper_bar_settle, paper_daily_summary.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from core.btc_ws import btc_state
from config import (
    MAKER_FEE_RATE,
    MAX_FILLS_PER_BAR,
    PAPER_TRADE_FEED_TIMEOUT_SECS,
    STOP_LOSS_PRICE,
    TAKE_PROFIT_PRICE,
    log,
)
from core.pm_ws import pm_state


def fee_equivalent(size: float, price: float) -> float:
    """Maker rebate weight: shares × feeRate × p × (1−p)."""
    return size * MAKER_FEE_RATE * price * (1.0 - price)


@dataclass
class PaperOrder:
    order_id: str
    condition_id: str
    token_id: str
    direction: str          # "UP" or "DOWN"
    side: str               # "BUY" (quotes/entries) or "SELL" (bracket TP)
    price: float
    size: float             # requested shares
    placed_ts: float
    spot_at_place: float    # spot price when quoted (repriceZ reference)
    filled: float = 0.0
    purpose: str = "quote"  # "quote" (one/two_sided) | "entry" (bracket) | "tp"
    pos_id: int = 0         # bracket position this TP belongs to

    @property
    def remaining(self) -> float:
        return max(0.0, self.size - self.filled)


@dataclass
class BracketPosition:
    """One bracket entry fill: maker BUY held with a TP sell + taker stop."""
    pos_id: int
    direction: str          # "UP" or "DOWN"
    token_id: str
    size: float
    entry_price: float
    tp_price: float
    stop_price: float
    tp_filled: float = 0.0
    tp_order_id: str | None = None
    exit_kind: str | None = None    # "tp" | "stop" | "expiry" (set at settle)
    exit_price: float | None = None
    taker_fee: float = 0.0
    realized_pnl: float = 0.0

    @property
    def remaining(self) -> float:
        return max(0.0, self.size - self.tp_filled)

    @property
    def open(self) -> bool:
        return self.exit_kind is None and self.remaining > 1e-9


@dataclass
class _BarState:
    condition_id: str
    question: str
    start_ts: int
    end_ts: int
    bar_open: float
    token_id_up: str
    token_id_down: str
    last_price: float = 0.0
    last_price_ts: float = 0.0
    # Filled inventory this bar, per direction.
    shares: dict = field(default_factory=lambda: {"UP": 0.0, "DOWN": 0.0})
    cost: dict = field(default_factory=lambda: {"UP": 0.0, "DOWN": 0.0})
    fee_equivalent_sum: float = 0.0
    fills: int = 0
    # Bracket mode: entry fills spawn positions with a TP sell + taker stop.
    entry_fills: int = 0
    entry_fills_by_side: dict = field(default_factory=dict)  # {"UP": n, "DOWN": n}
    positions: list = field(default_factory=list)   # list[BracketPosition]
    pos_seq: int = 0
    # Strategy metadata for offline analysis (set via set_bar_meta).
    p_up: float | None = None
    p_up_source: str = ""
    side_rule: str = ""


class PaperBook:
    engine = "paper"

    def __init__(self) -> None:
        self.orders: dict[str, PaperOrder] = {}
        self._order_seq: int = 0
        self._trade_cursor: int = 0     # pm_state.trade_seq already consumed
        self._bar: _BarState | None = None
        self._emit = None               # injected by main (_write_training_event)
        # Rolling daily accumulators (UTC day).
        self._day: str = ""
        self._daily = self._fresh_daily()

    # ── wiring ───────────────────────────────────────────────────────────────
    def set_emitter(self, emit) -> None:
        """emit(event_type, **payload) — main.py's _write_training_event."""
        self._emit = emit

    def _event(self, event_type: str, **payload) -> None:
        if self._emit is not None:
            try:
                self._emit(event_type, **payload)
            except Exception as exc:
                log.warning("Paper event emit failed (%s): %s", event_type, exc)

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
        }

    # ── bar lifecycle ────────────────────────────────────────────────────────
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
            # Fast-forward the trade cursor: prints from before we started
            # tracking this bar can't fill quotes we haven't placed yet.
            self._trade_cursor = pm_state.trade_seq

        # Refresh settle inputs for the tracked bar.
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

        outcome = None  # "UP" | "DOWN" | None (unknown)
        if bar.bar_open > 0 and bar.last_price > 0:
            outcome = "UP" if bar.last_price > bar.bar_open else "DOWN"

        # ── Bracket positions: resolve unexited remainders at outcome ─────────
        bracket_pnl = 0.0
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
                        pos.realized_pnl += remaining * (payout - pos.entry_price)
                    else:
                        log.warning(
                            "Paper bracket settle with UNKNOWN outcome — pnl of %.2f residual shares dropped  market=%s",
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

        # ── Legacy (one/two_sided) inventory settle — bracket exits already
        # decremented shares, so in bracket mode this only sees leftovers that
        # the bracket loop above just settled; skip it to avoid double count.
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
                    "Paper settle with UNKNOWN outcome — directional pnl of %.2f/%.2f residual shares dropped  market=%s",
                    res_up, res_dn, bar.condition_id[:16],
                )
        else:
            matched = 0.0

        gross = locked_pair_pnl + directional_pnl + bracket_pnl
        if up_sh > 0 or dn_sh > 0 or bar.positions:
            log.info(
                "PAPER_BAR_SETTLE  market=%s outcome=%s up=%.1f@%.3f down=%.1f@%.3f locked=%.4f dir=%.4f bracket=%.4f taker_fees=%.4f fee_eq=%.4f gross=%.4f exits=%s",
                bar.condition_id[:16], outcome, up_sh, avg_up, dn_sh, avg_dn,
                locked_pair_pnl, directional_pnl, bracket_pnl, taker_fee_sum,
                bar.fee_equivalent_sum, gross,
                [p["exit_kind"] for p in positions_payload] or "-",
            )
        self._event(
            "paper_bar_settle",
            paper_condition_id=bar.condition_id,
            paper_question=bar.question,
            outcome=outcome,
            p_up=bar.p_up,
            p_up_source=bar.p_up_source,
            side_rule=bar.side_rule,
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
            paper=True,
        )

        # Rolling daily summary.
        day = datetime.fromtimestamp(now, tz=timezone.utc).strftime("%Y-%m-%d")
        if day != self._day:
            self._day = day
            self._daily = self._fresh_daily()
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
            "paper_daily_summary",
            date=day,
            bars_settled=d["bars_settled"],
            fills=d["fills"],
            filled_shares=round(d["filled_shares"], 4),
            locked_pair_pnl=round(d["locked_pair_pnl"], 4),
            directional_pnl=round(d["directional_pnl"], 4),
            bracket_pnl=round(d["bracket_pnl"], 4),
            taker_fees=round(d["taker_fees"], 6),
            fee_equivalent_sum=round(d["fee_equivalent_sum"], 6),
            gross_pnl=round(d["gross_pnl"], 4),
            paper=True,
        )

    # ── quote lifecycle ──────────────────────────────────────────────────────
    def bar_inventory(self, direction: str) -> float:
        return self._bar.shares.get(direction, 0.0) if self._bar else 0.0

    def bar_active(self) -> bool:
        return self._bar is not None and self._bar.condition_id == pm_state.condition_id

    def resting_quote(self, direction: str) -> PaperOrder | None:
        for o in self.orders.values():
            if o.direction == direction and o.purpose == "quote":
                return o
        return None

    def resting_entry(self, direction: str) -> PaperOrder | None:
        for o in self.orders.values():
            if o.direction == direction and o.purpose == "entry":
                return o
        return None

    def set_bar_meta(self, **kw) -> None:
        """Attach strategy metadata (p_up, side_rule) to the active bar;
        emitted with paper_bar_settle for offline signal analysis."""
        if self._bar is not None:
            for k, v in kw.items():
                setattr(self._bar, k, v)

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
        if not self.bar_active():
            return None
        bar = self._bar
        token_id = bar.token_id_up if direction == "UP" else bar.token_id_down
        if not token_id or not (0 < price < 1) or size <= 0:
            return None
        self._order_seq += 1
        order_id = f"paper-{int(now * 1000)}-{self._order_seq}"
        self.orders[order_id] = PaperOrder(
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
        )
        event_type = "paper_tp_placed" if purpose == "tp" else "paper_quote_placed"
        log.info(
            "%s  %s %s %.1f @ %.3f  purpose=%s  order=%s",
            event_type.upper(), direction, side, size, price, purpose, order_id,
        )
        extra = {"size_clamped_to_min": True} if size_clamped_to_min else {}
        self._event(
            event_type,
            order_id=order_id,
            direction=direction,
            token_id=token_id,
            side=side,
            price=round(price, 4),
            size=size,
            purpose=purpose,
            pos_id=pos_id,
            paper=True,
            **extra,
        )
        return order_id

    def cancel_quote(self, order_id: str, reason: str, now: float) -> None:
        order = self.orders.pop(order_id, None)
        if order is None:
            return
        # Unlink a cancelled TP from its position so it can be re-placed.
        if order.purpose == "tp" and self._bar is not None:
            for pos in self._bar.positions:
                if pos.pos_id == order.pos_id and pos.tp_order_id == order_id:
                    pos.tp_order_id = None
        log.info(
            "PAPER_QUOTE_CANCELLED  %s %s %.1f @ %.3f  purpose=%s reason=%s  order=%s",
            order.direction, order.side, order.remaining, order.price, order.purpose, reason, order_id,
        )
        self._event(
            "paper_quote_cancelled",
            order_id=order_id,
            direction=order.direction,
            token_id=order.token_id,
            side=order.side,
            price=round(order.price, 4),
            remaining=round(order.remaining, 4),
            filled=round(order.filled, 4),
            age_secs=round(now - order.placed_ts, 2),
            purpose=order.purpose,
            reason=reason,
            paper=True,
        )

    def cancel_all(self, reason: str, now: float) -> None:
        for order_id in list(self.orders.keys()):
            self.cancel_quote(order_id, reason, now)

    # ── fills ────────────────────────────────────────────────────────────────
    def _trade_feed_live(self, now: float) -> bool:
        return (
            pm_state.trade_events > 0
            and (now - pm_state.last_trade_ts) <= PAPER_TRADE_FEED_TIMEOUT_SECS
        )

    def check_fills(self, now: float) -> None:
        """Match resting quotes against trades since the last tick; fall back
        to book-cross when the trade feed is silent. Then check taker stops
        on open bracket positions against the current best bid."""
        if not self.orders:
            self._trade_cursor = pm_state.trade_seq
            self._check_stops(now)
            return

        trade_feed = self._trade_feed_live(now)

        # 1. Trade prints (conservative primary basis).
        for trade in list(pm_state.recent_trades):
            if trade["seq"] <= self._trade_cursor:
                continue
            for order in list(self.orders.values()):
                if order.token_id != trade["token_id"]:
                    continue
                if trade["ts"] < order.placed_ts:
                    continue
                # BUY fills on prints at <= our bid; SELL (TP) on prints at >= our ask.
                if order.side == "BUY" and trade["price"] > order.price:
                    continue
                if order.side == "SELL" and trade["price"] < order.price:
                    continue
                cap = trade["size"] if trade["size"] > 0 else order.remaining
                fill_size = min(order.remaining, cap)
                if fill_size <= 0:
                    continue
                self._record_fill(order, fill_size, order.price, "trade_print", now)
        self._trade_cursor = pm_state.trade_seq

        # 2. Book-cross fallback (only when no live trade feed).
        if not trade_feed:
            for order in list(self.orders.values()):
                if order.token_id == pm_state.token_id_up:
                    bid, bid_size = pm_state.up_bid, pm_state.up_bid_size
                    ask, ask_size = pm_state.up_ask, pm_state.up_ask_size
                elif order.token_id == pm_state.token_id_down:
                    bid, bid_size = pm_state.down_bid, pm_state.down_bid_size
                    ask, ask_size = pm_state.down_ask, pm_state.down_ask_size
                else:
                    continue
                if order.side == "BUY":
                    cross, cross_size = ask, ask_size
                    crossed = 0 < cross < 1 and cross <= order.price
                else:  # SELL (TP): the bid crossing up through our ask
                    cross, cross_size = bid, bid_size
                    crossed = 0 < cross < 1 and cross >= order.price
                if not crossed:
                    continue
                cap = cross_size if cross_size > 0 else order.remaining
                fill_size = min(order.remaining, cap)
                if fill_size <= 0:
                    continue
                self._record_fill(order, fill_size, order.price, "book_cross", now)

        # 3. Conditional taker stops on open bracket positions.
        self._check_stops(now)

    # ── bracket lifecycle ────────────────────────────────────────────────────
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
        order_id = self.place_quote(
            pos.direction, pos.tp_price, pos.remaining, now,
            side="SELL", purpose="tp", pos_id=pos.pos_id,
        )
        if order_id is not None:
            pos.tp_order_id = order_id

    def _open_bracket(self, order: PaperOrder, size: float, price: float, now: float) -> None:
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
        # Max fills per bar PER SIDE: no refill conveyor — pull this side's
        # remaining entry quotes (including the just-filled order's remainder)
        # as soon as the cap hits. The other side's entry (BRACKET_SIDES=both)
        # keeps resting.
        if bar.entry_fills_by_side[order.direction] >= MAX_FILLS_PER_BAR:
            self.cancel_entries("max_fills_per_bar", now, direction=order.direction)
        # Bracket immediately: resting maker TP sell + armed taker stop.
        self._place_tp(pos, now)

    def _check_stops(self, now: float) -> None:
        bar = self._bar
        if bar is None or not self.bar_active():
            return
        for pos in bar.positions:
            if not pos.open:
                continue
            # Keep the TP resting (re-place if it was swept by cancel_all).
            if pos.tp_order_id not in self.orders:
                pos.tp_order_id = None
                self._place_tp(pos, now)
            best_bid = pm_state.up_bid if pos.direction == "UP" else pm_state.down_bid
            if not (0 < best_bid < 1) or best_bid > pos.stop_price:
                continue
            # Stop fires: taker sell of the remaining size at the observed bid.
            remaining = pos.remaining
            exec_price = best_bid
            taker_fee = remaining * MAKER_FEE_RATE * exec_price * (1.0 - exec_price)
            realized = remaining * (exec_price - pos.entry_price) - taker_fee
            pos.taker_fee += taker_fee
            pos.realized_pnl += realized
            pos.exit_kind = "stop"
            pos.exit_price = exec_price
            bar.shares[pos.direction] -= remaining
            bar.cost[pos.direction] -= remaining * pos.entry_price
            if pos.tp_order_id is not None:
                self.cancel_quote(pos.tp_order_id, "stop_fired", now)
            log.info(
                "PAPER_STOP_FIRED  %s SELL %.1f @ %.3f (stop<=%.2f)  taker_fee=%.5f realized=%.4f  pos=%d",
                pos.direction, remaining, exec_price, pos.stop_price, taker_fee, pos.realized_pnl, pos.pos_id,
            )
            self._event(
                "paper_stop_fired",
                pos_id=pos.pos_id,
                direction=pos.direction,
                token_id=pos.token_id,
                stop_price=round(pos.stop_price, 4),
                exec_price=round(exec_price, 4),
                size=round(remaining, 4),
                entry_price=round(pos.entry_price, 4),
                taker_fee=round(taker_fee, 6),
                realized_pnl=round(pos.realized_pnl, 4),
                paper=True,
            )

    def _record_tp_fill(self, order: PaperOrder, size: float, price: float, basis: str, now: float) -> None:
        bar = self._bar
        pos = self._find_position(order.pos_id)
        if pos is None or pos.exit_kind is not None:
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
        log.info(
            "PAPER_TP_FILL  %s SELL %.1f @ %.3f  basis=%s fee_eq=%.5f realized=%.4f remaining=%.1f  pos=%d",
            pos.direction, fill, price, basis, fee_eq, realized, pos.remaining, pos.pos_id,
        )
        self._event(
            "paper_tp_fill",
            order_id=order.order_id,
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
            paper=True,
        )

    def _record_fill(self, order: PaperOrder, size: float, price: float, basis: str, now: float) -> None:
        bar = self._bar
        if bar is None or order.condition_id != bar.condition_id:
            # Stale-bar order — should have been cancelled at settle.
            self.orders.pop(order.order_id, None)
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
            "PAPER_FILL  %s BUY %.1f @ %.3f  basis=%s fee_eq=%.5f  inv_up=%.1f inv_down=%.1f  order=%s",
            order.direction, size, price, basis, fee_eq,
            bar.shares["UP"], bar.shares["DOWN"], order.order_id,
        )
        self._event(
            "paper_fill",
            order_id=order.order_id,
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
            paper=True,
        )
        if order.remaining <= 1e-9:
            self.orders.pop(order.order_id, None)
        if order.purpose == "entry":
            self._open_bracket(order, size, price, now)


paper_book = PaperBook()
