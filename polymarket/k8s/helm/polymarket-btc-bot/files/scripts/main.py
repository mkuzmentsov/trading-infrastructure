"""
Polymarket BTC direction bot — active trading edition.

This patched version fixes the major execution bugs:
- waits for both Polymarket books to be live before trading
- reconciles actual filled size / balance before opening a position
- avoids immediate passive exits after entry
- ensures CTF approval is refreshed for the actual traded token
- applies more conservative entry filters through generate_signal()
"""
from __future__ import annotations

import asyncio
import math
import os
import time

from btc_ws import btc_state, run_btc_ws
from clob import (
    build_clob_client,
    cancel_order,
    ensure_approvals,
    ensure_ctf_approval,
    fetch_token_balance,
    fetch_usdc_balance,
    get_order_fill_info,
    get_order_status,
    has_trade_on_market,
    place_bet,
    place_limit_sell,
)
from config import (
    BET_SIZE_MIN,
    DRY_RUN,
    ENTRY_MIN_SECONDS_LEFT,
    EVAL_INTERVAL_SECS,
    LOOP_INTERVAL,
    MIN_EDGE,
    MIN_EXIT_BID,
    ORDER_REPLACE_GAP,
    POLYMARKET_ADDRESS,
    POLYMARKET_PK,
    SIGNAL_EXIT_EDGE,
    STOP_LOSS,
    TAKE_PROFIT,
    log,
)
from math_signal import generate_signal
from pm_ws import pm_state, run_pm_ws
from positions import pos_store
from redemptions import redeem_resolved_positions
from telegram import tg

_traded_markets: set[str] = set()
_checked_markets: set[str] = set()
_approved_ctf_tokens: set[str] = set()

_balance_cache: list = [0.0, 0.0]
_BALANCE_TTL = 30.0
_PENDING_BUY_TIMEOUT = 60.0


async def _wait_for_ready(timeout: float = 60.0) -> bool:
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if btc_state.ready and pm_state.ready:
            return True
        await asyncio.sleep(1)
    return False


def _seconds_left_in_bar() -> int:
    now = time.time()
    bar_end = math.ceil(now / LOOP_INTERVAL) * LOOP_INTERVAL
    return max(0, int(bar_end - now))


def _next_bar_boundary() -> float:
    now = time.time()
    return (math.floor(now / LOOP_INTERVAL) + 1) * LOOP_INTERVAL


def _current_bid_for_position() -> float:
    pos = pos_store.position
    if pos is None:
        return 0.0
    return pm_state.up_bid if pos.direction == "UP" else pm_state.down_bid


async def _get_balance(clob) -> float:
    now = time.time()
    if now - _balance_cache[1] < _BALANCE_TTL and _balance_cache[0] > 0:
        return _balance_cache[0]
    bal = await asyncio.to_thread(fetch_usdc_balance, clob)
    _balance_cache[0] = bal
    _balance_cache[1] = now
    return bal


async def _ensure_ctf_approval_for_token(clob, token_id: str) -> None:
    if DRY_RUN or not clob or not token_id or token_id in _approved_ctf_tokens:
        return
    await asyncio.to_thread(ensure_ctf_approval, clob, token_id)
    _approved_ctf_tokens.add(token_id)


async def _check_pending_buy(clob) -> None:
    pb = pos_store.pending_buy
    if pb is None:
        return

    if pb.condition_id != pm_state.condition_id:
        log.info("Pending buy is for old market — cancelling  order=%s", pb.order_id)
        if not DRY_RUN:
            await asyncio.to_thread(cancel_order, clob, pb.order_id)
        pos_store.clear_pending_buy()
        return

    if DRY_RUN:
        log.info(
            "DRY_RUN — simulating fill of pending buy  dir=%s  shares=%d  price=%.4f",
            pb.direction, pb.shares, pb.price,
        )
        _confirm_fill(pb, shares=pb.shares, entry_price=pb.price)
        return

    status, matched_shares, avg_price = await asyncio.to_thread(
        get_order_fill_info, clob, pb.order_id, pb.price, pb.shares
    )
    if status == "filled":
        token_balance = await asyncio.to_thread(fetch_token_balance, clob, pb.token_id)
        balance_shares = max(0, int(math.floor(token_balance)))
        actual_shares = matched_shares or pb.shares
        if balance_shares > 0:
            actual_shares = min(actual_shares, balance_shares) if actual_shares > 0 else balance_shares

        if actual_shares <= 0:
            log.warning(
                "Buy reported filled but token balance is zero — clearing pending buy  order=%s",
                pb.order_id,
            )
            pos_store.clear_pending_buy()
            return

        log.info(
            "Pending buy FILLED  order=%s  dir=%s  requested=%d  actual=%d  price=%.4f",
            pb.order_id, pb.direction, pb.shares, actual_shares, avg_price,
        )
        _confirm_fill(pb, shares=actual_shares, entry_price=avg_price)
        if pos_store.position and actual_shares < 5:
            pos_store.position.hold_to_expiry = True
            log.warning(
                "Filled position below minimum sell size — hold-to-expiry  shares=%d",
                actual_shares,
            )
        tg(
            f"🎯 <b>BTC 5m Entry</b>\n"
            f"Market: {pm_state.question[:80]}\n"
            f"Direction: {pb.direction}\n"
            f"Price: {avg_price:.3f}  Shares: {actual_shares}\n"
            f"Order: {pb.order_id}"
        )
    elif status == "cancelled":
        log.info("Pending buy was cancelled/expired  order=%s", pb.order_id)
        pos_store.clear_pending_buy()
    else:
        age = time.time() - pb.placed_at
        log.debug("Pending buy still open  order=%s  age=%.0fs", pb.order_id, age)
        if age > _PENDING_BUY_TIMEOUT:
            log.info("Pending buy timed out after %.0fs — cancelling", age)
            await asyncio.to_thread(cancel_order, clob, pb.order_id)
            pos_store.clear_pending_buy()


def _confirm_fill(pb, shares: int, entry_price: float) -> None:
    pos_store.open(
        condition_id=pb.condition_id,
        token_id=pb.token_id,
        direction=pb.direction,
        shares=shares,
        entry_price=entry_price,
        entry_time=time.time(),
    )
    _traded_markets.add(pb.condition_id)
    pos_store.clear_pending_buy()


async def _manage_position(clob) -> None:
    pos = pos_store.position
    if pos is None:
        return

    if pos.condition_id != pm_state.condition_id and pm_state.condition_id:
        log.info("Old market expired — clearing position  dir=%s  market=%s", pos.direction, pos.condition_id[:16])
        pos_store.close()
        return

    if pos.hold_to_expiry:
        log.debug("Position hold-to-expiry  dir=%s  shares=%s", pos.direction, pos.shares)
        return

    if pos.sell_order_id:
        if not DRY_RUN:
            status, sold_shares, avg_price = await asyncio.to_thread(
                get_order_fill_info, clob, pos.sell_order_id, pos.sell_price, pos.shares
            )
            if status == "filled":
                exit_price = avg_price or pos.sell_price
                realized_shares = sold_shares or pos.shares
                pnl = round((exit_price - pos.entry_price) * realized_shares, 2)
                log.info(
                    "Sell FILLED  dir=%s  entry=%.4f  exit=%.4f  shares=%d  pnl=$%.2f  order=%s",
                    pos.direction, pos.entry_price, exit_price, realized_shares, pnl, pos.sell_order_id,
                )
                tg(
                    f"✅ <b>Position closed</b>\n"
                    f"Direction: {pos.direction}\n"
                    f"Entry: {pos.entry_price:.4f}  Exit: {exit_price:.4f}\n"
                    f"Shares: {realized_shares}\n"
                    f"PnL: ${pnl:+.2f}"
                )
                pos_store.close()
                _balance_cache[1] = 0.0
                return
            elif status == "cancelled":
                log.info("Sell order cancelled externally — will re-post")
                pos_store.clear_sell_order()

    current_bid = _current_bid_for_position()

    if current_bid >= pos.entry_price + TAKE_PROFIT:
        log.info(
            "TAKE_PROFIT  bid=%.4f  entry=%.4f  gain=%.4f",
            current_bid, pos.entry_price, current_bid - pos.entry_price,
        )
        await _exit_position(clob, pos, current_bid, reason="take_profit")
        return

    if current_bid <= pos.entry_price - STOP_LOSS:
        log.info(
            "STOP_LOSS  bid=%.4f  entry=%.4f  loss=%.4f",
            current_bid, pos.entry_price, pos.entry_price - current_bid,
        )
        await _exit_position(clob, pos, current_bid, reason="stop_loss")
        return

    seconds_left = _seconds_left_in_bar()
    signal = generate_signal(
        cash_amount=0,
        seconds_left=seconds_left,
        bar_open=btc_state.bar_open,
        current_price=btc_state.current_price,
        ret_30s=btc_state.ret_since(30),
        ret_60s=btc_state.ret_since(60),
        bid_vol_top=btc_state.bid_vol_top,
        ask_vol_top=btc_state.ask_vol_top,
        sigma_5m=btc_state.sigma_5m(),
        up_bid=pm_state.up_bid,
        up_ask=pm_state.up_ask,
        down_bid=pm_state.down_bid,
        down_ask=pm_state.down_ask,
    )
    opposite_action = "BUY_DOWN" if pos.direction == "UP" else "BUY_UP"
    if signal.action == opposite_action and signal.edge >= SIGNAL_EXIT_EDGE:
        log.info("SIGNAL_FLIP  holding=%s  new=%s  edge=%.4f", pos.direction, signal.action, signal.edge)
        await _exit_position(clob, pos, current_bid, reason="signal_flip")
        return

    if pos.sell_order_id and abs(current_bid - pos.sell_price) >= ORDER_REPLACE_GAP:
        new_price = max(current_bid, MIN_EXIT_BID)
        log.info("Sell stale  old=%.4f  bid=%.4f — replace at %.4f", pos.sell_price, current_bid, new_price)
        if not DRY_RUN:
            await asyncio.to_thread(cancel_order, clob, pos.sell_order_id)
        pos_store.clear_sell_order()
        await _post_sell_order(clob, pos, new_price)
        return

    log.debug(
        "Holding position  dir=%s  entry=%.4f  bid=%.4f  secs_left=%d",
        pos.direction, pos.entry_price, current_bid, _seconds_left_in_bar(),
    )


async def _exit_position(clob, pos, current_bid: float, reason: str) -> None:
    if pos.sell_order_id and not DRY_RUN:
        await asyncio.to_thread(cancel_order, clob, pos.sell_order_id)
        pos_store.clear_sell_order()
    sell_price = max(current_bid, MIN_EXIT_BID)
    await _post_sell_order(clob, pos, sell_price, reason=reason)


async def _post_sell_order(clob, pos, price: float, reason: str = "") -> None:
    label = f" ({reason})" if reason else ""
    if DRY_RUN:
        log.info("DRY_RUN — would sell  dir=%s  shares=%d  price=%.4f%s", pos.direction, pos.shares, price, label)
        pos_store.attach_sell_order("dry-run-sell-id", price)
        return

    shares = pos.shares
    try:
        order_id = await asyncio.to_thread(
            place_limit_sell, clob, pos.token_id, shares, price, pos.condition_id, pm_state.taker_fee
        )
    except Exception as exc:
        import re

        m = re.search(r"balance[:\s]+(\d+)", str(exc))
        if m:
            actual = int(m.group(1)) // 1_000_000
            min_sell = 5
            if actual >= min_sell:
                log.warning(
                    "Partial fill detected (expected=%d actual=%d) — retrying sell%s",
                    shares, actual, label,
                )
                if pos_store.position:
                    pos_store.position.shares = actual
                order_id = await asyncio.to_thread(
                    place_limit_sell, clob, pos.token_id, actual, price, pos.condition_id, pm_state.taker_fee
                )
            else:
                log.warning(
                    "Partial fill below min order size (actual=%d, min=5) — hold-to-expiry%s",
                    actual, label,
                )
                if pos_store.position:
                    pos_store.position.shares = max(0, actual)
                    pos_store.position.hold_to_expiry = True
                return
        else:
            log.warning("Limit sell failed — marking hold-to-expiry%s", label)
            if pos_store.position:
                pos_store.position.hold_to_expiry = True
            return

    if order_id:
        log.info("Limit sell posted  order=%s  price=%.4f%s", order_id, price, label)
        pos_store.attach_sell_order(order_id, price)
    else:
        log.warning("Limit sell failed — marking hold-to-expiry%s", label)
        if pos_store.position:
            pos_store.position.hold_to_expiry = True


async def _try_enter(clob, balance: float) -> None:
    if not pm_state.ready or not btc_state.ready:
        return

    seconds_left = _seconds_left_in_bar()
    if seconds_left < ENTRY_MIN_SECONDS_LEFT:
        return

    signal = generate_signal(
        cash_amount=balance,
        seconds_left=seconds_left,
        bar_open=btc_state.bar_open,
        current_price=btc_state.current_price,
        ret_30s=btc_state.ret_since(30),
        ret_60s=btc_state.ret_since(60),
        bid_vol_top=btc_state.bid_vol_top,
        ask_vol_top=btc_state.ask_vol_top,
        sigma_5m=btc_state.sigma_5m(),
        up_bid=pm_state.up_bid,
        up_ask=pm_state.up_ask,
        down_bid=pm_state.down_bid,
        down_ask=pm_state.down_ask,
    )

    log.info("Signal: %s  p_up=%.3f  edge=%.4f  %s", signal.action, signal.p_up, signal.edge, signal.reason)

    if signal.action == "NO_TRADE":
        return

    direction = "UP" if signal.action == "BUY_UP" else "DOWN"
    token_id = pm_state.token_id_up if direction == "UP" else pm_state.token_id_down
    spend = round(signal.size * signal.price, 2)

    if DRY_RUN:
        log.info(
            "DRY_RUN — would buy %s  price=%.4f  shares=%d  spend=$%.2f  market=%s",
            signal.action, signal.price, signal.size, spend, pm_state.question[:60],
        )
        pos_store.open(
            condition_id=pm_state.condition_id,
            token_id=token_id,
            direction=direction,
            shares=signal.size,
            entry_price=signal.price,
            entry_time=time.time(),
        )
        _traded_markets.add(pm_state.condition_id)
        return

    await _ensure_ctf_approval_for_token(clob, token_id)

    try:
        order_id = await asyncio.to_thread(
            place_bet, clob, token_id, signal.size, signal.price, pm_state.condition_id, pm_state.taker_fee
        )
    except Exception as exc:
        if "does not exist" in str(exc).lower() or "no orderbook" in str(exc).lower():
            log.warning("Token orderbook gone — skipping market %s", pm_state.condition_id[:16])
            pm_state.ready = False
            _traded_markets.add(pm_state.condition_id)
        else:
            log.error("Order failed: %s", exc)
        return

    if order_id:
        log.info(
            "GTC buy placed  order=%s  dir=%s  price=%.4f  shares=%d  spend=$%.2f",
            order_id, direction, signal.price, signal.size, spend,
        )
        pos_store.open_pending_buy(
            order_id=order_id,
            condition_id=pm_state.condition_id,
            token_id=token_id,
            direction=direction,
            shares=signal.size,
            price=signal.price,
        )
        tg(
            f"📋 <b>BTC 5m Order placed</b>\n"
            f"Market: {pm_state.question[:80]}\n"
            f"Direction: {direction}\n"
            f"P(UP)={signal.p_up:.2%}  price={signal.price:.3f}  edge={signal.edge:.3f}\n"
            f"Shares: {signal.size}  Spend: ${spend:.2f}\n"
            f"Order: {order_id}"
        )
        _balance_cache[1] = 0.0


async def _tick(clob) -> None:
    log.debug(
        "Tick  BTC=$%.2f  up=%.3f/%.3f  down=%.3f/%.3f  pos=%s  pending=%s",
        btc_state.current_price,
        pm_state.up_bid, pm_state.up_ask,
        pm_state.down_bid, pm_state.down_ask,
        pos_store.position.direction if pos_store.position else "none",
        pos_store.pending_buy.order_id[:10] if pos_store.pending_buy else "none",
    )

    if pos_store.has_position():
        await _manage_position(clob)
        return

    if pos_store.has_pending_buy():
        await _check_pending_buy(clob)
        return

    cid = pm_state.condition_id
    if cid in _traded_markets:
        secs = _seconds_left_in_bar()
        if secs % 60 < 5:
            log.info("Already traded market %s — next bar in %ds", cid[:16], secs)
        return

    if DRY_RUN:
        balance = float(os.getenv("DRY_RUN_BALANCE", "100.0"))
    else:
        if not pm_state.ready or not btc_state.ready:
            return
        balance = await _get_balance(clob)
        if balance < BET_SIZE_MIN:
            log.info("Balance $%.2f below minimum — skipping entry", balance)
            return

    if not DRY_RUN and cid and cid not in _checked_markets:
        already = await asyncio.to_thread(has_trade_on_market, clob, cid)
        _checked_markets.add(cid)
        if already:
            log.info("Existing trade on %s — skipping entry", cid[:16])
            _traded_markets.add(cid)
            return

    await _try_enter(clob, balance)


async def main() -> None:
    log.info("=" * 60)
    log.info("Polymarket BTC Bot (patched) starting")
    log.info("  DRY_RUN=%s  MIN_EDGE=%.3f  EVAL_INTERVAL=%ds", DRY_RUN, MIN_EDGE, EVAL_INTERVAL_SECS)
    log.info("  TP=%.3f  SL=%.3f  SIGNAL_EXIT=%.3f  REPLACE_GAP=%.3f", TAKE_PROFIT, STOP_LOSS, SIGNAL_EXIT_EDGE, ORDER_REPLACE_GAP)
    log.info("=" * 60)

    if not POLYMARKET_PK and not DRY_RUN:
        raise RuntimeError("POLYMARKET_PK not set and DRY_RUN=false — refusing to start")

    asyncio.create_task(run_btc_ws(), name="btc_ws")
    asyncio.create_task(run_pm_ws(), name="pm_ws")

    log.info("Waiting for WebSocket feeds …")
    ready = await _wait_for_ready(timeout=60)
    if not ready:
        log.warning("Feeds not ready after 60s — proceeding anyway")
    else:
        log.info("Feeds ready  BTC=$%.2f  PM=%s", btc_state.current_price, pm_state.question[:50])

    clob = None
    if not DRY_RUN:
        try:
            clob = build_clob_client()
            from py_clob_client.clob_types import AssetType, BalanceAllowanceParams

            bal_data = clob.get_balance_allowance(
                params=BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
            )
            bal = float(bal_data.get("balance", 0)) / 1_000_000
            log.info("Wallet %s  balance: %.2f USDC", POLYMARKET_ADDRESS, bal)

            ensure_approvals(clob)

            if pm_state.token_id_up:
                await _ensure_ctf_approval_for_token(clob, pm_state.token_id_up)
        except Exception as exc:
            log.error("CLOB client init failed: %s", exc)
            raise

    next_redemption = _next_bar_boundary()

    while True:
        tick_start = time.time()
        try:
            await _tick(clob)
        except Exception as exc:
            log.exception("Tick error: %s", exc)

        now = time.time()
        if now >= next_redemption:
            next_redemption = (math.floor(now / LOOP_INTERVAL) + 1) * LOOP_INTERVAL
            if not DRY_RUN:
                try:
                    await asyncio.to_thread(redeem_resolved_positions)
                except Exception as exc:
                    log.error("Redemption sweep failed: %s", exc)

            pos = pos_store.position
            if pos and pos.condition_id != pm_state.condition_id:
                log.info("Bar boundary: clearing stale position (old market %s)", pos.condition_id[:16])
                pos_store.close()
            pb = pos_store.pending_buy
            if pb and pb.condition_id != pm_state.condition_id:
                log.info("Bar boundary: clearing stale pending buy (old market %s)", pb.condition_id[:16])
                pos_store.clear_pending_buy()

        elapsed = time.time() - tick_start
        await asyncio.sleep(max(0, EVAL_INTERVAL_SECS - elapsed))


if __name__ == "__main__":
    asyncio.run(main())
