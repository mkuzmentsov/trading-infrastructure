"""
Polymarket BTC 5m direction bot — latency arb + hold-to-expiry.

Strategy:
- Uses Binance BTC/USDT feed (1-3s ahead of Chainlink oracle) to detect
  BTC moves before the Polymarket book reprices.
- When the PM book is stale relative to the true BTC price, buys the
  cheap side (UP or DOWN token).
- Holds to expiry — the edge comes from information advantage at entry,
  not from active exit management. Payout is binary: 1.00 or 0.00.
- Falls back to Chainlink-only if Binance is unavailable.
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import re
import time

from binance_ws import binance_state, run_binance_ws
from btc_next_bar_model import blend_model_probabilities, predict_next_bar_p_up
from btc_ws import btc_state, run_btc_ws
from clob import (
    build_clob_client,
    cancel_order,
    ensure_approvals,
    ensure_ctf_approval,
    fetch_usdc_balance,
    place_bet,
    place_market_buy,
    place_market_sell,
    post_signed_buy_fak,
    post_signed_sell_fak,
    sign_buy_order,
    sign_sell_order,
)
from config import (
    AGGRESSIVE_EXIT_SLIPPAGE,
    BINANCE_STALE_SECS,
    BINANCE_WS_URL,
    BET_SIZE_MAX,
    BET_SIZE_MIN,
    DRIFT_A3,
    DRY_RUN,
    ENTRY_CONFIRMATION_TICKS,
    ENTRY_BOOK_MAX_TAKE_FRACTION,
    ENTRY_MAKER_OFFSET,
    ENTRY_MIN_SECONDS_LEFT,
    ENTRY_ORDER_TIMEOUT_SECS,
    ENTRY_SLIPPAGE_CAP,
    ENTRY_REPLACE_GAP,
    ENTRY_REPLACE_MIN_AGE_SECS,
    EVAL_INTERVAL_MS,
    EVAL_INTERVAL_SECS,
    FEED_STALE_SECS,
    HOLD_TO_EXPIRY_DEFAULT,
    LOOP_INTERVAL,
    MAX_ENTRY_PRICE,
    MIN_ENTRY_PRICE,
    MIN_EDGE,
    MIN_EXIT_BID,
    MIN_POSITION_SHARES,
    ORDER_REPLACE_GAP,
    POLYMARKET_ADDRESS,
    POLYMARKET_PK,
    REENTRY_EDGE_PENALTY,
    SL_ARM_DELAY_SECS,
    SL_MIN_ADVERSE_BTC,
    STOP_LOSS_MARKET_LIMIT,
    STRATEGY_NAME,
    ULTRA_CHEAP_SL_DELAY_SECS,
    ULTRA_CHEAP_TAIL_PRICE,
    TRAINING_EVENT_LOG_PATH,
    TRAINING_LOG_PATH,
    THESIS_MIN_BTC_DISTANCE,
    STOP_LOSS,
    TRAILING_ARM_GAIN,
    TRAILING_STOP_GAP,
    TAKE_PROFIT,
    WS_HEARTBEAT_SECS,
    log,
)
from ml_signal import predict_p_up as ml_predict_p_up
from pm_ws import pm_state, refresh_pm_quotes_from_rest, run_pm_ws
from positions import pos_store
from user_ws import run_user_ws, set_runtime_creds as _user_ws_set_creds, user_state
from redemptions import redeem_resolved_positions
from strategy import StrategyContext, build_strategy
from telegram import tg, tg_async

_approved_ctf_tokens: set[str] = set()

_balance_cache: list = [0.0, 0.0]
_BALANCE_TTL = 30.0
_last_feed_diag_at = 0.0
_entry_confirmation: dict = {"condition_id": "", "action": "", "count": 0, "edge": 0.0}
_stop_loss_reentry_guard: dict[tuple[str, str], float] = {}
_market_stop_loss_count: dict[str, int] = {}
_sell_cancel_cooldown_until: float = 0.0

# Fast-retry signal: set by handlers (e.g. FAK kill) to wake the main loop
# before the normal EVAL_INTERVAL_SECS sleep elapses. Initialized in main().
_retry_now_event: "asyncio.Event | None" = None
_FAST_RETRY_WS_SETTLE_SECS = 0.15


async def _schedule_fast_retry(reason: str) -> None:
    """Let the WS cache settle briefly, then wake the main loop for a retry."""
    if _retry_now_event is None:
        return
    log.info("Fast-retry scheduled  reason=%s  settle=%.2fs", reason, _FAST_RETRY_WS_SETTLE_SECS)
    await asyncio.sleep(_FAST_RETRY_WS_SETTLE_SECS)
    _retry_now_event.set()
# Tracks how many times we've seen a "filled but residual" result for a given sell order.
# On the first occurrence we wait for on-chain settlement; on the second we treat it as real.
_sell_residual_retries: dict[str, int] = {}
_pos_heartbeat_ts: float = 0.0  # last time we logged a position status line
_strategy = build_strategy(STRATEGY_NAME)


def _append_jsonl(path: str, record: dict, warning_label: str) -> None:
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, separators=(",", ":"), sort_keys=True) + "\n")
    except Exception as exc:
        log.warning("%s write failed: %s", warning_label, exc)


def _write_training_event(event_type: str, **payload) -> None:
    if not TRAINING_EVENT_LOG_PATH:
        return
    record = {
        "ts": round(time.time(), 3),
        "event": event_type,
        "condition_id": pm_state.condition_id,
        "question": pm_state.question,
        "market_start_ts": pm_state.market_start_ts,
        "market_end_ts": pm_state.market_end_ts,
        "seconds_left": _seconds_left_in_bar(),
        "btc_price": round(btc_state.current_price, 4),
        "bar_open": round(btc_state.bar_open, 4),
        "up_bid": round(pm_state.up_bid, 4),
        "up_ask": round(pm_state.up_ask, 4),
        "up_bid_size": round(pm_state.up_bid_size, 4),
        "up_ask_size": round(pm_state.up_ask_size, 4),
        "down_bid": round(pm_state.down_bid, 4),
        "down_ask": round(pm_state.down_ask, 4),
        "down_bid_size": round(pm_state.down_bid_size, 4),
        "down_ask_size": round(pm_state.down_ask_size, 4),
    }
    record.update(payload)
    _append_jsonl(TRAINING_EVENT_LOG_PATH, record, "Training event")


def _write_position_parked_event(pos, reason: str) -> None:
    _write_training_event(
        "position_parked",
        condition_id=pos.condition_id,
        question=pm_state.question if pos.condition_id == pm_state.condition_id else "",
        direction=pos.direction,
        token_id=pos.token_id,
        shares=pos.shares,
        entry_price=round(pos.entry_price, 4),
        hold_to_expiry=pos.hold_to_expiry,
        reason=reason,
        dry_run=DRY_RUN,
    )


async def _refresh_pm_quotes_if_stale(reason: str) -> bool:
    ages = _feed_staleness()
    if ages["pm_up_age"] <= FEED_STALE_SECS and ages["pm_down_age"] <= FEED_STALE_SECS:
        return False
    refreshed = await asyncio.to_thread(refresh_pm_quotes_from_rest, reason)
    if refreshed:
        _log_feed_diag(force=True, reason=f"pm_rest_refresh:{reason}")
    return refreshed


def _binance_price_if_fresh() -> float:
    """Return Binance BTC price if available and fresh, else 0.0."""
    if binance_state.ready and binance_state.age() <= BINANCE_STALE_SECS:
        return binance_state.current_price
    return 0.0


def _build_ml_snapshot(seconds_left: int) -> dict:
    """Minimal snapshot shape consumed by ml_signal.predict_p_up. Keep keys
    aligned with ai/pm_btc/features.py so training and inference use identical
    inputs."""
    return {
        "seconds_left": seconds_left,
        "btc": {
            "bar_open": btc_state.bar_open,
            "current_price": btc_state.current_price,
            "ret_30s": btc_state.ret_since(30),
            "ret_60s": btc_state.ret_since(60),
            "sigma_5m": btc_state.sigma_5m(),
        },
        "pm": {
            "up_bid": pm_state.up_bid,
            "up_ask": pm_state.up_ask,
            "up_bid_size": pm_state.up_bid_size,
            "up_ask_size": pm_state.up_ask_size,
            "down_bid": pm_state.down_bid,
            "down_ask": pm_state.down_ask,
            "down_bid_size": pm_state.down_bid_size,
            "down_ask_size": pm_state.down_ask_size,
            "book_events": pm_state.book_events,
        },
        "feeds": {
            "staleness": _feed_staleness(),
        },
    }


def _combined_ml_probability(seconds_left: int, ml_snapshot: dict | None = None) -> float | None:
    snapshot = ml_snapshot or _build_ml_snapshot(seconds_left)
    pm_prob = ml_predict_p_up(snapshot)
    prior_prob = predict_next_bar_p_up(
        binance_state.completed_bars(before_ts=pm_state.market_start_ts, limit=64),
        market_start_ts=pm_state.market_start_ts,
    )
    combined, info = blend_model_probabilities(pm_prob, prior_prob, seconds_left)
    if combined is not None and (pm_prob is not None or prior_prob is not None):
        log.debug(
            "ML blend  combined=%.4f pm=%.4f prior=%.4f prior_weight=%.3f prior_conf=%.3f",
            combined,
            pm_prob if pm_prob is not None else -1.0,
            prior_prob if prior_prob is not None else -1.0,
            float(info.get("prior_weight") or 0.0),
            float(info.get("prior_confidence") or 0.0),
        )
    return combined


def _write_training_snapshot(context: str, signal, cash_amount: float, seconds_left: int, ml_p_up: float | None) -> None:
    if not TRAINING_LOG_PATH:
        return

    pos = pos_store.position
    bp = _binance_price_if_fresh()
    record = {
        "ts": round(time.time(), 3),
        "context": context,
        "condition_id": pm_state.condition_id,
        "question": pm_state.question,
        "market_start_ts": pm_state.market_start_ts,
        "market_end_ts": pm_state.market_end_ts,
        "seconds_left": seconds_left,
        "cash_amount": round(cash_amount, 4),
        "btc": {
            "bar_open": round(btc_state.bar_open, 4),
            "current_price": round(btc_state.current_price, 4),
            "binance_price": round(bp, 4) if bp > 0 else None,
            "binance_age": round(binance_state.age(), 2) if binance_state.ready else None,
            "ret_30s": round(btc_state.ret_since(30), 6),
            "ret_60s": round(btc_state.ret_since(60), 6),
            "sigma_5m": round(btc_state.sigma_5m(), 6),
            "last_updated_at": btc_state.last_updated_at,
            "last_round_id": btc_state.last_round_id,
        },
        "pm": {
            "ready": pm_state.ready,
            "up_bid": round(pm_state.up_bid, 4),
            "up_ask": round(pm_state.up_ask, 4),
            "up_bid_size": round(pm_state.up_bid_size, 4),
            "up_ask_size": round(pm_state.up_ask_size, 4),
            "down_bid": round(pm_state.down_bid, 4),
            "down_ask": round(pm_state.down_ask, 4),
            "down_bid_size": round(pm_state.down_bid_size, 4),
            "down_ask_size": round(pm_state.down_ask_size, 4),
            "last_up_book_ts": round(pm_state.last_up_book_ts, 3),
            "last_down_book_ts": round(pm_state.last_down_book_ts, 3),
            "book_events": pm_state.book_events,
            "last_ws_message_at": round(pm_state.last_ws_message_at, 3),
        },
        "feeds": {
            "fresh": _feeds_are_fresh(),
            "staleness": {k: round(v, 3) for k, v in _feed_staleness().items()},
        },
        "signal": {
            "action": signal.action,
            "price": round(signal.price, 4) if signal.price is not None else None,
            "size": signal.size,
            "p_up": signal.p_up,
            "edge": signal.edge,
            "reason": signal.reason,
            "debug": signal.debug,
            "ml_p_up": ml_p_up,
        },
        "position": {
            "direction": pos.direction if pos else None,
            "shares": pos.shares if pos else 0,
            "entry_price": round(pos.entry_price, 4) if pos else None,
            "entry_edge": round(pos.entry_edge, 4) if pos else None,
            "entry_p_up": round(pos.entry_p_up, 4) if pos else None,
            "entry_seconds_left": pos.entry_seconds_left if pos else None,
            "peak_bid": round(pos.peak_bid, 4) if pos else None,
            "hold_to_expiry": pos.hold_to_expiry if pos else False,
        },
        "pending_buy": {
            "active": pos_store.pending_buy is not None,
            "order_id": pos_store.pending_buy.order_id if pos_store.pending_buy else None,
            "direction": pos_store.pending_buy.direction if pos_store.pending_buy else None,
            "shares": pos_store.pending_buy.shares if pos_store.pending_buy else 0,
            "price": round(pos_store.pending_buy.price, 4) if pos_store.pending_buy else None,
            "edge": round(pos_store.pending_buy.edge, 4) if pos_store.pending_buy else None,
            "p_up": round(pos_store.pending_buy.p_up, 4) if pos_store.pending_buy else None,
            "seconds_left": pos_store.pending_buy.seconds_left if pos_store.pending_buy else None,
        },
    }
    _append_jsonl(TRAINING_LOG_PATH, record, "Training snapshot")


def _build_strategy_context(cash_amount: float, seconds_left: int, ml_p_up: float | None) -> StrategyContext:
    staleness = _feed_staleness()
    return StrategyContext(
        cash_amount=cash_amount,
        seconds_left=seconds_left,
        bar_open=btc_state.bar_open,
        current_price=btc_state.current_price,
        ret_30s=btc_state.ret_since(30),
        ret_60s=btc_state.ret_since(60),
        sigma_5m=btc_state.sigma_5m(),
        up_bid=pm_state.up_bid,
        up_ask=pm_state.up_ask,
        up_bid_size=pm_state.up_bid_size,
        up_ask_size=pm_state.up_ask_size,
        down_bid=pm_state.down_bid,
        down_ask=pm_state.down_ask,
        down_bid_size=pm_state.down_bid_size,
        down_ask_size=pm_state.down_ask_size,
        book_events=pm_state.book_events,
        feed_price_age=staleness.get("price_age", 0.0),
        feed_up_age=staleness.get("pm_up_age", 0.0),
        feed_down_age=staleness.get("pm_down_age", 0.0),
        binance_price=_binance_price_if_fresh(),
        binance_age=binance_state.age() if binance_state.ready else 0.0,
        ml_p_up=ml_p_up,
    )


def _log_signal_debug(context: str, signal, cash_amount: float, seconds_left: int) -> None:
    bp = _binance_price_if_fresh()
    log.info(
        "Signal eval [%s] inputs: cash=%.2f secs_left=%d open=%.2f chainlink=%.2f binance=%.2f ret30=%.6f ret60=%.6f sigma5m=%.6f up_bid=%.3f up_ask=%.3f down_bid=%.3f down_ask=%.3f",
        context,
        cash_amount,
        seconds_left,
        btc_state.bar_open,
        btc_state.current_price,
        bp if bp > 0 else 0.0,
        btc_state.ret_since(30),
        btc_state.ret_since(60),
        btc_state.sigma_5m(),
        pm_state.up_bid,
        pm_state.up_ask,
        pm_state.down_bid,
        pm_state.down_ask,
    )
    p_up_ml = signal.debug.get("p_up_model")
    price_src = signal.debug.get("price_source", "?")
    divergence = signal.debug.get("divergence")
    log.info(
        "Signal eval [%s] result: action=%s price=%s size=%d p_up=%.4f edge=%.4f src=%s div=%s reason=%s",
        context,
        signal.action,
        f"{signal.price:.4f}" if signal.price is not None else "-",
        signal.size,
        signal.p_up,
        signal.edge,
        price_src,
        f"{divergence:.6f}" if divergence is not None else "n/a",
        signal.reason,
    )
    _write_training_snapshot(context, signal, cash_amount, seconds_left, p_up_ml)


def _push_user_ws_creds(clob) -> None:
    """Hand the CLOB client's L2 API creds to user_ws so it can authenticate.

    build_clob_client() already calls client.set_api_creds(create_or_derive_api_creds())
    when env creds are empty, so clob.creds is always populated here."""
    creds = getattr(clob, "creds", None)
    if creds is None:
        log.warning("CLOB client has no creds attribute — user_ws will stay idle")
        return
    try:
        _user_ws_set_creds(creds.api_key, creds.api_secret, creds.api_passphrase)
    except Exception as exc:
        log.warning("Failed to push creds into user_ws: %s", exc)


async def _init_clob() -> object:
    clob = build_clob_client()
    from py_clob_client.clob_types import AssetType, BalanceAllowanceParams

    _push_user_ws_creds(clob)

    bal_data = clob.get_balance_allowance(
        params=BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
    )
    bal = float(bal_data.get("balance", 0)) / 1_000_000
    log.info("Wallet %s  balance: %.2f USDC", POLYMARKET_ADDRESS, bal)

    ensure_approvals(clob)

    if pm_state.token_id_up:
        await _ensure_ctf_approval_for_token(clob, pm_state.token_id_up)
    return clob


async def _wait_for_ready(timeout: float = 60.0) -> bool:
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if btc_state.ready and pm_state.ready:
            if binance_state.ready:
                log.info("All feeds ready (including Binance)")
            else:
                log.info("Core feeds ready (Binance still connecting — will use Chainlink fallback)")
            return True
        await asyncio.sleep(1)
    return False


def _seconds_left_in_bar() -> int:
    now = time.time()
    if pm_state.market_end_ts > 0:
        return max(0, int(pm_state.market_end_ts - now))
    bar_end = math.ceil(now / LOOP_INTERVAL) * LOOP_INTERVAL
    return max(0, int(bar_end - now))


def _next_bar_boundary() -> float:
    if pm_state.market_end_ts > 0:
        return float(pm_state.market_end_ts)
    now = time.time()
    return (math.floor(now / LOOP_INTERVAL) + 1) * LOOP_INTERVAL


def _current_bid_for_position() -> float:
    pos = pos_store.position
    if pos is None:
        return 0.0
    return pm_state.up_bid if pos.direction == "UP" else pm_state.down_bid


def _entry_top_ask_size(direction: str) -> float:
    return pm_state.up_ask_size if direction == "UP" else pm_state.down_ask_size


def _depth_capped_entry_size(direction: str, requested_shares: int) -> int:
    top_ask_size = _entry_top_ask_size(direction)
    if top_ask_size <= 0 or requested_shares <= 0:
        return requested_shares
    max_by_top = int(math.floor(top_ask_size * ENTRY_BOOK_MAX_TAKE_FRACTION))
    if max_by_top <= 0:
        return 0
    return min(requested_shares, max_by_top)


def _feed_staleness() -> dict:
    now = time.time()
    price_age = now - btc_state.last_updated_at if btc_state.last_updated_at > 0 else float("inf")
    up_age = now - pm_state.last_up_book_ts if pm_state.last_up_book_ts > 0 else float("inf")
    down_age = now - pm_state.last_down_book_ts if pm_state.last_down_book_ts > 0 else float("inf")
    return {
        "price_age": price_age,
        "pm_up_age": up_age,
        "pm_down_age": down_age,
    }


def _feeds_are_fresh() -> bool:
    ages = _feed_staleness()
    return (
        ages["price_age"] <= FEED_STALE_SECS
        and ages["pm_up_age"] <= FEED_STALE_SECS
        and ages["pm_down_age"] <= FEED_STALE_SECS
    )


def _log_feed_diag(force: bool = False, reason: str = "") -> None:
    global _last_feed_diag_at
    now = time.time()
    if not force and now - _last_feed_diag_at < WS_HEARTBEAT_SECS:
        return
    _last_feed_diag_at = now
    ages = _feed_staleness()
    pos = pos_store.position
    pos_desc = "none"
    if pos:
        pos_desc = f"{pos.direction}:{pos.shares}@{pos.entry_price:.3f}"
        if pos.hold_to_expiry:
            pos_desc += ":hold"
    held_count = len(pos_store.held_positions)
    prefix = f"{reason}  " if reason else ""
    log.info(
        "%sFeed diag  fresh=%s  source=%s price=%.2f binance=%.2f open=%.2f age=%.1fs tick=%s pm_ready=%s up=%.3f/%.3f x %.1f age=%.1fs down=%.3f/%.3f x %.1f age=%.1fs pos=%s held=%d pending=%s binance_ok=%s binance_age=%.1fs rtds_session=%d rtds_msg_age=%.1fs rtds_msg=%s rtds_err=%s price_updates=%d pm_session=%d pm_events=%d pm_msg_age=%.1fs",
        prefix,
        _feeds_are_fresh(),
        btc_state.price_source,
        btc_state.current_price,
        binance_state.current_price if binance_state.ready else 0.0,
        btc_state.bar_open,
        ages["price_age"],
        btc_state.last_round_id,
        pm_state.ready,
        pm_state.up_bid,
        pm_state.up_ask,
        pm_state.up_ask_size,
        ages["pm_up_age"],
        pm_state.down_bid,
        pm_state.down_ask,
        pm_state.down_ask_size,
        ages["pm_down_age"],
        pos_desc,
        held_count,
        "yes" if pos_store.pending_buy else "no",
        binance_state.ready,
        binance_state.age() if binance_state.ready else -1,
        btc_state.rtds_session_id,
        now - btc_state.last_rtds_message_at if btc_state.last_rtds_message_at > 0 else -1,
        btc_state.last_rtds_message_kind,
        btc_state.last_rtds_error or "-",
        btc_state.price_updates,
        pm_state.ws_session_id,
        pm_state.book_events,
        now - pm_state.last_ws_message_at if pm_state.last_ws_message_at > 0 else -1,
    )


async def _get_balance(clob) -> float:
    now = time.time()
    if now - _balance_cache[1] < _BALANCE_TTL and _balance_cache[0] > 0:
        return _balance_cache[0]
    bal = await asyncio.to_thread(fetch_usdc_balance, clob)
    _balance_cache[0] = bal
    _balance_cache[1] = now
    return bal


_snapshot_in_flight: bool = False
_redemption_in_flight: bool = False


async def _sweep_redemptions(reason: str) -> None:
    """Run the on-chain redemption sweep off the event loop.

    `redeem_resolved_positions` performs Data API + Polygon RPC calls and
    signs/submits transactions — all blocking I/O. Delegate to a worker
    thread so the trading loop never stalls.
    """
    global _redemption_in_flight
    if DRY_RUN or _redemption_in_flight:
        return
    _redemption_in_flight = True
    try:
        log.info("Redemption sweep start (reason=%s)", reason)
        await asyncio.to_thread(redeem_resolved_positions, None)
        log.info("Redemption sweep done (reason=%s)", reason)
    except Exception as exc:
        log.exception("Redemption sweep failed: %s", exc)
    finally:
        _redemption_in_flight = False


async def _write_balance_snapshot(clob, reason: str) -> None:
    global _snapshot_in_flight
    if DRY_RUN or clob is None or _snapshot_in_flight:
        return
    _snapshot_in_flight = True
    try:
        _balance_cache[1] = 0.0
        balance = await _get_balance(clob)
        _write_training_event(
            "balance_snapshot",
            reason=reason,
            usdc_balance=round(balance, 4),
            active_position=pos_store.position is not None,
            held_positions=len(pos_store.held_positions),
            pending_buy=pos_store.pending_buy is not None,
            dry_run=False,
        )
        await tg_async(
            f"💰 <b>Balance</b>  ${balance:.2f} USDC\n"
            f"Reason: {reason}  "
            f"pos: {'yes' if pos_store.position else 'no'}  "
            f"held: {len(pos_store.held_positions)}"
        )
    finally:
        _snapshot_in_flight = False


async def _ensure_ctf_approval_for_token(clob, token_id: str) -> None:
    if DRY_RUN or not clob or not token_id or token_id in _approved_ctf_tokens:
        return
    await asyncio.to_thread(ensure_ctf_approval, clob, token_id)
    _approved_ctf_tokens.add(token_id)


async def _prewarm_ctf_approvals(clob) -> None:
    if DRY_RUN or not clob or not pm_state.ready:
        return
    for token_id in (pm_state.token_id_up, pm_state.token_id_down):
        if token_id and token_id not in _approved_ctf_tokens:
            await _ensure_ctf_approval_for_token(clob, token_id)


def _current_entry_ask(direction: str) -> float:
    return pm_state.up_ask if direction == "UP" else pm_state.down_ask


def _entry_price_still_valid(direction: str, entry_price: float) -> tuple[bool, str]:
    if not pm_state.ready:
        return False, "pm_not_ready"
    current_ask = _current_entry_ask(direction)
    if not (0 < current_ask < 1):
        return False, f"invalid_current_ask:{current_ask:.4f}"
    expected_price = round(max(0.01, current_ask - ENTRY_MAKER_OFFSET), 2) if ENTRY_MAKER_OFFSET > 0 else current_ask
    if abs(expected_price - entry_price) >= ENTRY_REPLACE_GAP:
        return False, f"ask_moved:{expected_price:.4f}"
    return True, ""


async def _check_pending_buy(clob) -> None:
    pb = pos_store.pending_buy
    if pb is None:
        return

    def _pending_buy_market_price() -> float:
        return pm_state.up_ask if pb.direction == "UP" else pm_state.down_ask

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

    status, matched_shares, avg_price = user_state.get_order_fill_info(
        pb.order_id, pb.price, pb.shares
    )
    if status == "filled":
        token_balance = user_state.get_token_balance(pb.token_id)
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
            _write_position_parked_event(pos_store.position, reason="below_min_position_size")
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
        seconds_left = _seconds_left_in_bar()
        current_ask = _pending_buy_market_price()
        log.debug("Pending buy still open  order=%s  age=%.0fs", pb.order_id, age)
        if seconds_left < ENTRY_MIN_SECONDS_LEFT:
            log.info(
                "Pending buy too late in bar — cancelling  order=%s age=%.0fs secs_left=%d",
                pb.order_id,
                age,
                seconds_left,
            )
            await asyncio.to_thread(cancel_order, clob, pb.order_id)
            pos_store.clear_pending_buy()
            return
        if (
            current_ask > 0
            and age >= ENTRY_REPLACE_MIN_AGE_SECS
            and abs((current_ask - ENTRY_MAKER_OFFSET) - pb.price) >= ENTRY_REPLACE_GAP
        ):
            log.info(
                "Pending buy stale vs market — cancelling  order=%s dir=%s old=%.4f ask=%.4f age=%.0fs",
                pb.order_id,
                pb.direction,
                pb.price,
                current_ask,
                age,
            )
            await asyncio.to_thread(cancel_order, clob, pb.order_id)
            pos_store.clear_pending_buy()
            return
        if age > ENTRY_ORDER_TIMEOUT_SECS:
            log.info("Pending buy timed out after %.0fs — cancelling", age)
            await asyncio.to_thread(cancel_order, clob, pb.order_id)
            pos_store.clear_pending_buy()


async def _await_fill_reconciliation(
    order_id: str,
    requested_shares: float,
    fallback_price: float,
    timeout_secs: float = 3.0,
    poll_interval: float = 0.1,
) -> tuple[float, float]:
    """Wait briefly for user_ws to deliver matched_shares/avg_price for a just-matched order.

    Returns (actual_shares, actual_price) — fractional shares accumulated across
    all trade events for this order, and the size-weighted avg fill price.
    Falls back to (requested_shares, fallback_price) if no fill event arrives.
    """
    deadline = time.time() + timeout_secs
    while time.time() < deadline:
        shares = user_state.matched_shares.get(order_id, 0.0)
        price = user_state.avg_price.get(order_id, 0.0)
        if shares > 0 and price > 0:
            return shares, price
        await asyncio.sleep(poll_interval)
    shares = user_state.matched_shares.get(order_id, 0.0) or float(requested_shares)
    price = user_state.avg_price.get(order_id, 0.0) or fallback_price
    log.warning(
        "Fill reconciliation timed out  order=%s  ws_shares=%.4f  ws_price=%.4f  — using fallback",
        order_id, user_state.matched_shares.get(order_id, 0.0), user_state.avg_price.get(order_id, 0.0),
    )
    return shares, price


def _confirm_fill(pb, shares: int, entry_price: float) -> None:
    pos_store.open(
        condition_id=pb.condition_id,
        token_id=pb.token_id,
        direction=pb.direction,
        shares=shares,
        entry_price=entry_price,
        entry_time=time.time(),
        entry_edge=pb.edge,
        entry_p_up=pb.p_up,
        entry_seconds_left=pb.seconds_left,
    )
    # Latency arb strategy: hold to expiry. The edge is at entry time,
    # not from active exit management. Let the binary resolve.
    if _strategy.entry_hold_to_expiry() and pos_store.position:
        pos_store.position.hold_to_expiry = True
        log.info(
            "Hold-to-expiry set on fill  dir=%s  shares=%d  price=%.4f  edge=%.4f",
            pb.direction, shares, entry_price, pb.edge,
        )
    pos_store.clear_pending_buy()
    _write_training_event(
        "position_opened",
        direction=pb.direction,
        token_id=pb.token_id,
        shares=shares,
        entry_price=round(entry_price, 4),
        entry_edge=round(pb.edge, 4),
        entry_p_up=round(pb.p_up, 4),
        entry_seconds_left=pb.seconds_left,
        hold_to_expiry=_strategy.entry_hold_to_expiry(),
        dry_run=DRY_RUN,
    )


def _exit_target_price(current_bid: float, reason: str) -> float:
    # FAK floor = min acceptable fill. Wider slippage doesn't worsen fill price
    # (FAK walks top-of-book down), it only improves fill probability when the
    # book reprices during the ~300ms order flight. Apply uniformly to all exits.
    return max(MIN_EXIT_BID, current_bid - AGGRESSIVE_EXIT_SLIPPAGE)


async def _manage_position(clob) -> None:
    global _sell_cancel_cooldown_until
    pos = pos_store.position
    if pos is None:
        return

    if pos.condition_id != pm_state.condition_id and pm_state.condition_id:
        if pos.sell_order_id and not DRY_RUN:
            status, sold_shares, avg_price = user_state.get_order_fill_info(
                pos.sell_order_id, pos.sell_price, pos.shares
            )
            if status == "filled":
                exit_price = avg_price or pos.sell_price
                realized_shares = float(sold_shares or pos.shares)
                remaining_balance = user_state.get_token_balance(pos.token_id)
                if remaining_balance > 0:
                    realized_shares = max(0.0, float(pos.shares) - float(remaining_balance))
                    residual_whole = int(math.floor(remaining_balance))
                    if residual_whole >= 5:
                        retry_key = pos.sell_order_id or ""
                        retry_count = _sell_residual_retries.get(retry_key, 0)
                        if retry_count < 1:
                            _sell_residual_retries[retry_key] = retry_count + 1
                            _sell_cancel_cooldown_until = time.time() + 12.0
                            log.warning(
                                "Old-market sell marked filled but residual may be settlement lag — "
                                "cooldown 12s  residual=%.6f (whole=%d) order=%s",
                                remaining_balance, residual_whole, retry_key,
                            )
                            return
                        log.warning(
                            "Old-market sell marked filled — confirmed residual after settlement wait  "
                            "residual=%.6f (whole=%d) — keeping residual open",
                            remaining_balance,
                            residual_whole,
                        )
                        _sell_residual_retries.pop(retry_key, None)
                        pos_store.position.shares = residual_whole
                        pos_store.clear_sell_order()
                        return
                    if remaining_balance >= 0.01:
                        log.info(
                            "Old-market residual dust after sell fill  residual=%.6f — "
                            "cannot place new sell below min size",
                            remaining_balance,
                        )
                pnl = round((exit_price - pos.entry_price) * realized_shares, 2)
                log.info(
                    "Old-market sell FILLED  dir=%s  entry=%.4f  exit=%.4f  shares=%.4f  pnl=$%.2f  order=%s",
                    pos.direction, pos.entry_price, exit_price, realized_shares, pnl, pos.sell_order_id,
                )
                _write_training_event(
                    "position_closed",
                    direction=pos.direction,
                    shares=realized_shares,
                    entry_price=round(pos.entry_price, 4),
                    exit_price=round(exit_price, 4),
                    pnl=round(pnl, 2),
                    reason="market_rotated_filled",
                    order_id=pos.sell_order_id,
                    dry_run=False,
                )
                if pos.exit_reason == "stop_loss":
                    _stop_loss_reentry_guard[(pos.condition_id, pos.direction)] = pos.entry_edge
                    _market_stop_loss_count[pos.condition_id] = _market_stop_loss_count.get(pos.condition_id, 0) + 1
                pos_store.close()
                _balance_cache[1] = 0.0
                return
        if not pos.hold_to_expiry:
            log.info(
                "Market rotated while position still open — holding to expiry  dir=%s  market=%s",
                pos.direction,
                pos.condition_id[:16],
            )
            pos.hold_to_expiry = True
        log.info(
            "Parking old-market hold position  dir=%s shares=%d entry=%.4f market=%s",
            pos.direction,
            pos.shares,
            pos.entry_price,
            pos.condition_id[:16],
        )
        _write_position_parked_event(pos, reason="market_rotated_hold")
        pos_store.park_current_position()
        return

    if pos.hold_to_expiry:
        _log_feed_diag(reason="hold_to_expiry")
        return

    if pos.sell_order_id:
        if time.time() < _sell_cancel_cooldown_until:
            log.debug("Sell fill check in cooldown — skipping  order=%s", pos.sell_order_id)
            return
        if not DRY_RUN:
            status, sold_shares, avg_price = user_state.get_order_fill_info(
                pos.sell_order_id, pos.sell_price, pos.shares
            )
            if status == "filled":
                exit_price = avg_price or pos.sell_price
                realized_shares = float(sold_shares or pos.shares)
                remaining_balance = user_state.get_token_balance(pos.token_id)
                if remaining_balance > 0:
                    realized_shares = max(0.0, float(pos.shares) - float(remaining_balance))
                    residual_whole = int(math.floor(remaining_balance))
                    if residual_whole >= 5:
                        # May be settlement lag: the sell matched off-chain but the on-chain
                        # balance hasn't updated yet. On the first occurrence, wait 12s and
                        # re-check before treating it as a genuine residual.
                        retry_key = pos.sell_order_id or ""
                        retry_count = _sell_residual_retries.get(retry_key, 0)
                        if retry_count < 1:
                            _sell_residual_retries[retry_key] = retry_count + 1
                            _sell_cancel_cooldown_until = time.time() + 12.0
                            log.warning(
                                "Sell marked filled but residual may be settlement lag — "
                                "cooldown 12s before treating as genuine  "
                                "residual=%.6f (whole=%d) order=%s",
                                remaining_balance, residual_whole, retry_key,
                            )
                            return  # sell_order_id stays active; re-check after cooldown
                        # Second check: residual is real — keep it open.
                        log.warning(
                            "Sell marked filled — confirmed residual after settlement wait  "
                            "residual=%.6f (whole=%d) — keeping residual open",
                            remaining_balance,
                            residual_whole,
                        )
                        _sell_residual_retries.pop(retry_key, None)
                        pos_store.position.shares = residual_whole
                        pos_store.clear_sell_order()
                        return
                    if remaining_balance >= 0.01:
                        log.info(
                            "Residual dust after sell fill  residual=%.6f — "
                            "cannot place new sell below min size",
                            remaining_balance,
                        )
                _sell_residual_retries.pop(pos.sell_order_id or "", None)
                pnl = round((exit_price - pos.entry_price) * realized_shares, 2)
                log.info(
                    "Sell FILLED  dir=%s  entry=%.4f  exit=%.4f  shares=%.4f  pnl=$%.2f  order=%s",
                    pos.direction, pos.entry_price, exit_price, realized_shares, pnl, pos.sell_order_id,
                )
                tg(
                    f"✅ <b>Position closed</b>\n"
                    f"Direction: {pos.direction}\n"
                    f"Entry: {pos.entry_price:.4f}  Exit: {exit_price:.4f}\n"
                    f"Shares: {realized_shares:.4f}\n"
                    f"PnL: ${pnl:+.2f}"
                )
                _write_training_event(
                    "position_closed",
                    direction=pos.direction,
                    shares=realized_shares,
                    entry_price=round(pos.entry_price, 4),
                    exit_price=round(exit_price, 4),
                    pnl=round(pnl, 2),
                    reason=pos.exit_reason or "sell_filled",
                    order_id=pos.sell_order_id,
                    dry_run=False,
                )
                if pos.exit_reason == "stop_loss":
                    _stop_loss_reentry_guard[(pos.condition_id, pos.direction)] = pos.entry_edge
                    _market_stop_loss_count[pos.condition_id] = _market_stop_loss_count.get(pos.condition_id, 0) + 1
                pos_store.close()
                _balance_cache[1] = 0.0
                return
            elif status == "cancelled":
                log.info("Sell order cancelled externally — will re-post")
                pos_store.clear_sell_order()

    current_bid = _current_bid_for_position()
    pos.peak_bid = max(pos.peak_bid, current_bid)
    unrealized = current_bid - pos.entry_price
    seconds_left = _seconds_left_in_bar()

    # Periodic position status heartbeat (every 10s)
    global _pos_heartbeat_ts
    now = time.time()
    if now - _pos_heartbeat_ts >= 10.0:
        _pos_heartbeat_ts = now
        _btc_dist = math.log(btc_state.current_price / btc_state.bar_open) if btc_state.bar_open > 0 else 0.0
        _bar_side = "winning" if (
            (pos.direction == "DOWN" and _btc_dist < -THESIS_MIN_BTC_DISTANCE)
            or (pos.direction == "UP"  and _btc_dist >  THESIS_MIN_BTC_DISTANCE)
        ) else "neutral" if abs(_btc_dist) < THESIS_MIN_BTC_DISTANCE else "losing"
        log.info(
            "Position  dir=%s  entry=%.4f  bid=%.4f  pnl=%.4f  peak=%.4f  shares=%d  secs_left=%d  btc_dist=%+.4f  bar=%s",
            pos.direction, pos.entry_price, current_bid, unrealized,
            pos.peak_bid, pos.shares, seconds_left, _btc_dist, _bar_side,
        )

    # Exit logic mirrors backtest.simulate_active_exits. Two branches:
    #   - profit_1      : trailing_stop → take_profit → stop_loss → signal_flip → late_bar_cut
    #   - pm_btc_ml-entry / pm_btc_ml-entry-v2: all exits live inside the ML entry strategy
    # Each check is the minimum logic required; no arming, no floors, no
    # stale-order cancellation. If a sell order is already resting, a later
    # check will just reprice it below.
    strategy_name = getattr(_strategy, "name", "")
    ml_entry_active = strategy_name in {"pm_btc_ml-entry", "pm_btc_ml-entry-v2", "math_smart"}

    if not ml_entry_active:
        # 1. Trailing stop — fires whenever peak_bid exceeded arm gain and bid
        #    has pulled back by TRAILING_STOP_GAP.
        if (
            pos.peak_bid >= pos.entry_price + TRAILING_ARM_GAIN
            and current_bid <= pos.peak_bid - TRAILING_STOP_GAP
            and not pos.sell_order_id
        ):
            log.info(
                "TRAILING_STOP  bid=%.4f  peak=%.4f  entry=%.4f  drawdown=%.4f",
                current_bid, pos.peak_bid, pos.entry_price, pos.peak_bid - current_bid,
            )
            await _exit_position(clob, pos, current_bid, reason="trailing_stop")
            return

        # 2. Take profit — simple threshold, no arming/floor.
        if unrealized >= TAKE_PROFIT and not (pos.sell_order_id and pos.exit_reason == "take_profit"):
            log.info(
                "TAKE_PROFIT  bid=%.4f  entry=%.4f  pnl=%.4f  threshold=%.4f",
                current_bid, pos.entry_price, unrealized, TAKE_PROFIT,
            )
            await _exit_position(clob, pos, current_bid, reason="take_profit")
            return

        # 3. Stop loss with BTC-adverse-move gate.
        stop_loss_gap = STOP_LOSS * (0.75 if seconds_left <= 90 else 1.0)
        time_held = time.time() - pos.entry_time
        is_ultra_cheap = pos.entry_price <= ULTRA_CHEAP_TAIL_PRICE
        sl_delay = ULTRA_CHEAP_SL_DELAY_SECS if is_ultra_cheap else SL_ARM_DELAY_SECS
        sl_armed = time_held >= sl_delay
        if current_bid <= pos.entry_price - stop_loss_gap and sl_armed:
            btc_distance = math.log(btc_state.current_price / btc_state.bar_open) if btc_state.bar_open > 0 else 0.0
            adverse_move = btc_distance if pos.direction == "DOWN" else -btc_distance
            bid_collapse = current_bid <= pos.entry_price - 2 * stop_loss_gap
            gate_active = (
                adverse_move < SL_MIN_ADVERSE_BTC
                and seconds_left > 60
                and not bid_collapse
            )
            if gate_active:
                log.info(
                    "STOP_LOSS suppressed — BTC not adverse enough  bid=%.4f  entry=%.4f  adverse_btc=%.4f  required=%.4f  secs_left=%d",
                    current_bid, pos.entry_price, adverse_move, SL_MIN_ADVERSE_BTC, seconds_left,
                )
            else:
                log.info(
                    "STOP_LOSS  bid=%.4f  entry=%.4f  loss=%.4f  threshold=%.4f  held=%.0fs  adverse_btc=%.4f  late_bar=%s  bid_collapse=%s",
                    current_bid, pos.entry_price, pos.entry_price - current_bid, stop_loss_gap, time_held, adverse_move,
                    seconds_left <= 60, bid_collapse,
                )
                await _exit_position(clob, pos, current_bid, reason="stop_loss")
                return

    # Strategy-level exits. For profit_1 this is only signal_flip; for
    # pm_btc_ml-entry* strategies own SL / trailing / thesis_decay /
    # late_bar_cut / late_bar_fade / force_close (mirrors backtest).
    ml_snapshot = _build_ml_snapshot(seconds_left)
    ml_p_up = _combined_ml_probability(seconds_left, ml_snapshot)
    strategy_decision = _strategy.evaluate_position(
        _build_strategy_context(0.0, seconds_left, ml_p_up),
        pos,
        current_bid,
        now,
    )
    if strategy_decision.signal is not None:
        _log_signal_debug("manage_position", strategy_decision.signal, cash_amount=0, seconds_left=seconds_left)
    if strategy_decision.exit_reason:
        log.info(
            "STRATEGY_EXIT  reason=%s  bid=%.4f  entry=%.4f  pnl=%.4f  secs_left=%d",
            strategy_decision.exit_reason, current_bid, pos.entry_price, unrealized, seconds_left,
        )
        await _exit_position(clob, pos, current_bid, reason=strategy_decision.exit_reason)
        return
    current_side_edge = strategy_decision.current_side_edge

    # Late-bar cut — last-ditch exit if underwater near bar end. profit_1 only;
    # pm_btc_ml-entry* strategies already have their own late_bar_cut.
    if not ml_entry_active and seconds_left <= 45 and unrealized <= -0.05 and not pos.sell_order_id:
        log.info(
            "LATE_BAR_CUT  secs_left=%d  bid=%.4f  entry=%.4f  pnl=%.4f",
            seconds_left, current_bid, pos.entry_price, unrealized,
        )
        await _exit_position(clob, pos, current_bid, reason="late_bar_cut")
        return

    log.debug(
        "Holding position  dir=%s  entry=%.4f  bid=%.4f  peak=%.4f  edge_now=%.4f  secs_left=%d",
        pos.direction, pos.entry_price, current_bid, pos.peak_bid, current_side_edge, _seconds_left_in_bar(),
    )


async def _exit_position(clob, pos, current_bid: float, reason: str) -> None:
    if pos.sell_order_id and not DRY_RUN:
        old_order_id = pos.sell_order_id
        canceled = await asyncio.to_thread(cancel_order, clob, old_order_id)
        if canceled:
            pos_store.clear_sell_order()
        else:
            log.info(
                "Exit skip repost — existing sell remains active  order=%s  reason=%s",
                old_order_id,
                pos.exit_reason or reason,
            )
            global _sell_cancel_cooldown_until
            _sell_cancel_cooldown_until = time.time() + 3.0
            return
    sell_price = _exit_target_price(current_bid, reason)
    await _post_sell_order(clob, pos, sell_price, reason=reason)


async def _post_sell_order(clob, pos, price: float, reason: str = "") -> None:
    label = f" ({reason})" if reason else ""
    if DRY_RUN:
        pnl = round((price - pos.entry_price) * pos.shares, 2)
        log.info(
            "DRY_RUN — simulated sell  dir=%s  shares=%d  entry=%.4f  price=%.4f  pnl=$%.2f%s",
            pos.direction,
            pos.shares,
            pos.entry_price,
            price,
            pnl,
            label,
        )
        _write_training_event(
            "position_closed",
            direction=pos.direction,
            shares=pos.shares,
            entry_price=round(pos.entry_price, 4),
            exit_price=round(price, 4),
            pnl=round(pnl, 2),
            reason=reason or "dry_run_exit",
            dry_run=True,
        )
        if reason == "stop_loss":
            _stop_loss_reentry_guard[(pos.condition_id, pos.direction)] = pos.entry_edge
            _market_stop_loss_count[pos.condition_id] = _market_stop_loss_count.get(pos.condition_id, 0) + 1
        pos_store.close()
        _balance_cache[1] = 0.0
        return

    # Authoritative share count comes from user_ws token_shares (on-chain truth),
    # not pos.shares. This eliminates both failure modes:
    #   - over-fill drift (stored 13, actually own 13.70 → 0.70 left as dust)
    #   - under-fill drift (stored 35, actually own 33.67 → FAK rejects "not enough balance")
    onchain = user_state.get_token_balance(pos.token_id)
    # Round DOWN to 0.01 to avoid over-selling due to float precision.
    requested_shares = math.floor(onchain * 100) / 100
    if requested_shares < 1.0:
        log.warning(
            "Sell skipped — on-chain balance too small to trade  token_shares=%.4f  pos.shares=%.4f%s",
            onchain, pos.shares, label,
        )
        if pos_store.position:
            pos_store.position.hold_to_expiry = True
        return

    # Pre-sign the FAK sell in background. Overlaps EIP-712 signing (~100-300ms)
    # with the sync work above and, on salvage exits into a crashing book, shaves
    # enough latency to catch the bid before it drops further.
    sign_task = asyncio.create_task(
        asyncio.to_thread(
            sign_sell_order, clob, pos.token_id, requested_shares, price, pm_state.taker_fee,
        ),
        name="sell_sign",
    )

    try:
        signed = await sign_task
    except Exception as exc:
        log.warning("Market sell signing raised — will retry next tick%s: %s", label, exc)
        return

    try:
        order_id, is_matched = await asyncio.to_thread(post_signed_sell_fak, clob, signed)
    except Exception as exc:
        exc_str = str(exc)
        match = re.search(r"balance:\s*(\d+)", exc_str)
        if match and "not enough balance" in exc_str.lower():
            chain_balance = int(match.group(1)) / 1_000_000.0
            prev = user_state.token_shares.get(pos.token_id, 0.0)
            user_state.token_shares[pos.token_id] = chain_balance
            log.warning(
                "USER_WS token_shares WRITE src=sell_error  token=%s  prev=%.6f  onchain=%.6f  "
                "delta=%+.6f  requested=%.4f  pos.shares=%.4f%s",
                pos.token_id[:16], prev, chain_balance, chain_balance - prev,
                requested_shares, pos.shares, label,
            )
            asyncio.create_task(
                _schedule_fast_retry("sell_balance_corrected"),
                name="fast_retry_sell_balance",
            )
            return
        log.warning("Market sell post raised — will retry next tick%s: %s", label, exc)
        return

    if not order_id or not is_matched:
        # FAK killed without a fill (book floor too high or no bids at price).
        # Schedule a fast-retry so we don't wait a full 1s tick while the book
        # keeps moving against us (critical for salvage exits).
        log.info(
            "FAK sell unfilled — fast-retry scheduled  order=%s  matched=%s  price=%.4f%s",
            order_id, is_matched, price, label,
        )
        asyncio.create_task(
            _schedule_fast_retry("fak_sell_no_match"),
            name="fast_retry_fak_sell",
        )
        return

    actual_shares, actual_price = await _await_fill_reconciliation(
        order_id, requested_shares, price
    )
    if actual_shares <= 0:
        log.warning("FAK sell matched=True but ws reports 0 shares — retry next tick%s", label)
        return

    exit_price = actual_price or price
    remaining = max(0.0, requested_shares - actual_shares)
    realized_shares = float(actual_shares)
    pnl = round((exit_price - pos.entry_price) * realized_shares, 2)

    if remaining < 0.01:
        log.info(
            "FAK sell FILLED — closing position  dir=%s  entry=%.4f  exit=%.4f  "
            "shares=%.0f  pnl=$%.2f  order=%s%s",
            pos.direction, pos.entry_price, exit_price, realized_shares, pnl, order_id, label,
        )
        tg(
            f"✅ <b>Position closed</b>\n"
            f"Direction: {pos.direction}\n"
            f"Entry: {pos.entry_price:.4f}  Exit: {exit_price:.4f}\n"
            f"Shares: {realized_shares:.0f}\n"
            f"PnL: ${pnl:+.2f}"
        )
        _write_training_event(
            "position_closed",
            direction=pos.direction,
            shares=realized_shares,
            entry_price=round(pos.entry_price, 4),
            exit_price=round(exit_price, 4),
            pnl=round(pnl, 2),
            reason=reason or "fak_sell_filled",
            order_id=order_id,
            dry_run=False,
        )
        if reason == "stop_loss":
            _stop_loss_reentry_guard[(pos.condition_id, pos.direction)] = pos.entry_edge
            _market_stop_loss_count[pos.condition_id] = _market_stop_loss_count.get(pos.condition_id, 0) + 1
        pos_store.close()
        _balance_cache[1] = 0.0
        return

    # Partial fill: shrink position, record, let next tick retry remainder.
    log.info(
        "FAK sell PARTIAL — filled=%.4f remaining=%.4f  entry=%.4f  exit=%.4f  pnl=$%.2f  order=%s%s",
        realized_shares, remaining, pos.entry_price, exit_price, pnl, order_id, label,
    )
    _write_training_event(
        "position_partial_close",
        direction=pos.direction,
        shares=realized_shares,
        remaining=remaining,
        entry_price=round(pos.entry_price, 4),
        exit_price=round(exit_price, 4),
        pnl=round(pnl, 2),
        reason=reason or "fak_sell_partial",
        order_id=order_id,
        dry_run=False,
    )
    if pos_store.position:
        pos_store.position.shares = remaining
        if remaining < MIN_POSITION_SHARES:
            pos_store.position.hold_to_expiry = True
            _write_position_parked_event(
                pos_store.position, reason=f"fak_partial_below_min:{reason or 'sell'}"
            )


async def _try_enter(clob, balance: float) -> None:
    if not pm_state.ready or not btc_state.ready:
        _log_feed_diag(reason="entry_blocked:not_ready")
        return

    if not _feeds_are_fresh():
        await _refresh_pm_quotes_if_stale("entry")
    if not _feeds_are_fresh():
        _log_feed_diag(force=True, reason="entry_blocked:stale_feeds")
        return

    seconds_left = _seconds_left_in_bar()
    if seconds_left < ENTRY_MIN_SECONDS_LEFT:
        return

    ml_snapshot = _build_ml_snapshot(seconds_left)
    ml_p_up = _combined_ml_probability(seconds_left, ml_snapshot)
    signal = _strategy.evaluate_entry(_build_strategy_context(balance, seconds_left, ml_p_up))
    _log_signal_debug("try_enter", signal, cash_amount=balance, seconds_left=seconds_left)

    log.info("Signal: %s  p_up=%.3f  edge=%.4f  %s", signal.action, signal.p_up, signal.edge, signal.reason)

    if signal.action == "NO_TRADE":
        _entry_confirmation["condition_id"] = ""
        _entry_confirmation["action"] = ""
        _entry_confirmation["count"] = 0
        _entry_confirmation["edge"] = 0.0
        return

    direction = "UP" if signal.action == "BUY_UP" else "DOWN"
    depth_capped_size = _depth_capped_entry_size(direction, signal.size)
    if depth_capped_size < signal.size:
        top_ask_size = _entry_top_ask_size(direction)
        if depth_capped_size < MIN_POSITION_SHARES:
            log.info(
                "Entry blocked by top-book liquidity  dir=%s requested=%d top_ask=%.2f cap_fraction=%.2f capped=%d",
                direction,
                signal.size,
                top_ask_size,
                ENTRY_BOOK_MAX_TAKE_FRACTION,
                depth_capped_size,
            )
            _entry_confirmation["condition_id"] = ""
            _entry_confirmation["action"] = ""
            _entry_confirmation["count"] = 0
            _entry_confirmation["edge"] = 0.0
            return
        log.info(
            "Entry size capped by top-book liquidity  dir=%s requested=%d top_ask=%.2f cap_fraction=%.2f capped=%d",
            direction,
            signal.size,
            top_ask_size,
            ENTRY_BOOK_MAX_TAKE_FRACTION,
            depth_capped_size,
        )
        signal.size = depth_capped_size

    reentry_floor = _stop_loss_reentry_guard.get((pm_state.condition_id, direction))
    if reentry_floor is not None and signal.edge < reentry_floor + REENTRY_EDGE_PENALTY:
        log.info(
            "Signal blocked by stop-loss reentry guard  dir=%s  edge=%.4f  required=%.4f",
            direction,
            signal.edge,
            reentry_floor + REENTRY_EDGE_PENALTY,
        )
        _entry_confirmation["condition_id"] = ""
        _entry_confirmation["action"] = ""
        _entry_confirmation["count"] = 0
        _entry_confirmation["edge"] = 0.0
        return

    market_stop_losses = _market_stop_loss_count.get(pm_state.condition_id, 0)
    if market_stop_losses >= STOP_LOSS_MARKET_LIMIT:
        log.info(
            "Signal blocked by market stop-loss cap  market=%s  count=%d  limit=%d",
            pm_state.condition_id[:16],
            market_stop_losses,
            STOP_LOSS_MARKET_LIMIT,
        )
        _entry_confirmation["condition_id"] = ""
        _entry_confirmation["action"] = ""
        _entry_confirmation["count"] = 0
        _entry_confirmation["edge"] = 0.0
        return

    if (
        _entry_confirmation["condition_id"] == pm_state.condition_id
        and _entry_confirmation["action"] == signal.action
    ):
        _entry_confirmation["count"] += 1
        _entry_confirmation["edge"] = signal.edge
    else:
        _entry_confirmation["condition_id"] = pm_state.condition_id
        _entry_confirmation["action"] = signal.action
        _entry_confirmation["count"] = 1
        _entry_confirmation["edge"] = signal.edge

    if _entry_confirmation["count"] < ENTRY_CONFIRMATION_TICKS:
        log.info(
            "Entry confirmation pending  action=%s  count=%d/%d  edge=%.4f",
            signal.action,
            _entry_confirmation["count"],
            ENTRY_CONFIRMATION_TICKS,
            signal.edge,
        )
        return

    token_id = pm_state.token_id_up if direction == "UP" else pm_state.token_id_down

    entry_mode = _strategy.entry_order_mode()

    # Maker entry: post below the ask to avoid crossing the spread immediately.
    # Re-derive size from the same dollar budget at the new (lower) price.
    if entry_mode == "gtc" and ENTRY_MAKER_OFFSET > 0:
        maker_price = round(max(0.01, signal.price - ENTRY_MAKER_OFFSET), 2)
        if maker_price < MIN_ENTRY_PRICE or maker_price > MAX_ENTRY_PRICE:
            log.info(
                "Maker entry outside configured band  dir=%s  ask=%.4f  maker=%.4f  band=%.2f-%.2f",
                direction,
                signal.price,
                maker_price,
                MIN_ENTRY_PRICE,
                MAX_ENTRY_PRICE,
            )
            _entry_confirmation["count"] = 0
            return
        maker_budget = min(signal.size * signal.price, BET_SIZE_MAX)
        maker_size = math.floor(maker_budget / maker_price)
        if maker_size < MIN_POSITION_SHARES:
            log.info(
                "Maker entry size below minimum after offset  dir=%s  ask=%.4f  maker=%.4f  size=%d",
                direction, signal.price, maker_price, maker_size,
            )
            _entry_confirmation["count"] = 0
            return
        if maker_price != signal.price or maker_size != signal.size:
            log.info(
                "Maker entry  dir=%s  ask=%.4f → maker=%.4f  shares=%d → %d  offset=%.3f",
                direction, signal.price, maker_price, signal.size, maker_size, ENTRY_MAKER_OFFSET,
            )
        entry_price = maker_price
        entry_size = maker_size
    else:
        entry_price = signal.price
        entry_size = signal.size

    cid = pm_state.condition_id
    spend = round(entry_size * entry_price, 2)

    if DRY_RUN:
        log.info(
            "DRY_RUN — would buy %s  mode=%s  price=%.4f  shares=%d  spend=$%.2f  market=%s  hold=%s",
            signal.action, entry_mode, entry_price, entry_size, spend, pm_state.question[:60], _strategy.entry_hold_to_expiry(),
        )
        pos_store.open(
            condition_id=pm_state.condition_id,
            token_id=token_id,
            direction=direction,
            shares=entry_size,
            entry_price=entry_price,
            entry_time=time.time(),
            entry_edge=signal.edge,
            entry_p_up=signal.p_up,
            entry_seconds_left=seconds_left,
        )
        if _strategy.entry_hold_to_expiry() and pos_store.position:
            pos_store.position.hold_to_expiry = True
        _write_training_event(
            "position_opened",
            direction=direction,
            token_id=token_id,
            shares=entry_size,
            entry_price=round(entry_price, 4),
            entry_edge=round(signal.edge, 4),
            entry_p_up=round(signal.p_up, 4),
            entry_seconds_left=seconds_left,
            spend=round(spend, 2),
            hold_to_expiry=_strategy.entry_hold_to_expiry(),
            source=f"dry_run_{entry_mode}_entry",
            dry_run=True,
        )
        _entry_confirmation["count"] = 0
        return

    if not _feeds_are_fresh():
        await _refresh_pm_quotes_if_stale("pre_order_revalidate")
    if not _feeds_are_fresh():
        log.info("Entry aborted before order submit — feeds went stale")
        _entry_confirmation["count"] = 0
        return
    if pm_state.condition_id != cid:
        log.info("Entry aborted before order submit — market changed  old=%s new=%s", cid[:16], pm_state.condition_id[:16])
        _entry_confirmation["count"] = 0
        return
    still_valid, reason = _entry_price_still_valid(direction, entry_price)
    if not still_valid:
        log.info(
            "Entry aborted before order submit — live book changed  dir=%s  price=%.4f  reason=%s  up=%.3f/%.3f  down=%.3f/%.3f",
            direction,
            entry_price,
            reason,
            pm_state.up_bid,
            pm_state.up_ask,
            pm_state.down_bid,
            pm_state.down_ask,
        )
        _entry_confirmation["count"] = 0
        return

    # Pre-sign the order in a background task so EIP-712 signing (~100-300ms)
    # overlaps with the approval check + post-approval revalidation. On the first
    # entry per market (pre-warm pending), this also hides the approval RPC.
    sign_task = None
    if entry_mode == "market":
        sign_price = round(min(0.99, entry_price + ENTRY_SLIPPAGE_CAP), 3)
        sign_task = asyncio.create_task(
            asyncio.to_thread(
                sign_buy_order, clob, token_id, entry_size, sign_price, pm_state.taker_fee,
            ),
            name="entry_sign",
        )

    async def _abort_signing() -> None:
        if sign_task is not None and not sign_task.done():
            sign_task.cancel()
            try:
                await sign_task
            except BaseException:
                pass

    await _ensure_ctf_approval_for_token(clob, token_id)

    if not _feeds_are_fresh():
        await _refresh_pm_quotes_if_stale("post_approval_revalidate")
    if not _feeds_are_fresh():
        log.info("Entry aborted after approval — feeds went stale")
        _entry_confirmation["count"] = 0
        await _abort_signing()
        return
    if pm_state.condition_id != cid:
        log.info("Entry aborted after approval — market changed  old=%s new=%s", cid[:16], pm_state.condition_id[:16])
        _entry_confirmation["count"] = 0
        await _abort_signing()
        return
    still_valid, reason = _entry_price_still_valid(direction, entry_price)
    if not still_valid:
        log.info(
            "Entry aborted after approval — live book changed  dir=%s  price=%.4f  reason=%s  up=%.3f/%.3f  down=%.3f/%.3f",
            direction,
            entry_price,
            reason,
            pm_state.up_bid,
            pm_state.up_ask,
            pm_state.down_bid,
            pm_state.down_ask,
        )
        _entry_confirmation["count"] = 0
        await _abort_signing()
        return

    try:
        if entry_mode == "market":
            try:
                signed = await sign_task
            except Exception as exc:
                if "does not exist" in str(exc).lower() or "no orderbook" in str(exc).lower():
                    log.warning("Token orderbook gone — skipping market %s", pm_state.condition_id[:16])
                    pm_state.ready = False
                else:
                    log.error("Order signing failed: %s", exc)
                _entry_confirmation["count"] = 0
                return
            order_id, is_matched = await asyncio.to_thread(post_signed_buy_fak, clob, signed)
        else:
            order_id = await asyncio.to_thread(
                place_bet, clob, token_id, entry_size, entry_price, pm_state.condition_id, pm_state.taker_fee
            )
            is_matched = False
    except Exception as exc:
        if "does not exist" in str(exc).lower() or "no orderbook" in str(exc).lower():
            log.warning("Token orderbook gone — skipping market %s", pm_state.condition_id[:16])
            pm_state.ready = False
        else:
            log.error("Order failed: %s", exc)
        return

    if entry_mode == "market" and order_id and is_matched:
        actual_shares, actual_price = await _await_fill_reconciliation(
            order_id, entry_size, entry_price
        )
        actual_spend = round(actual_shares * actual_price, 2)
        log.info(
            "Market buy IMMEDIATELY MATCHED  order=%s  dir=%s  req_price=%.4f  fill_price=%.4f  req_shares=%d  filled=%.4f  spend=$%.2f",
            order_id, direction, entry_price, actual_price, entry_size, actual_shares, actual_spend,
        )
        pos_store.open(
            condition_id=pm_state.condition_id,
            token_id=token_id,
            direction=direction,
            shares=actual_shares,
            entry_price=actual_price,
            entry_time=time.time(),
            entry_edge=signal.edge,
            entry_p_up=signal.p_up,
            entry_seconds_left=seconds_left,
        )
        if _strategy.entry_hold_to_expiry() and pos_store.position:
            pos_store.position.hold_to_expiry = True
        _write_training_event(
            "position_opened",
            direction=direction,
            token_id=token_id,
            shares=actual_shares,
            entry_price=round(actual_price, 4),
            quoted_price=round(entry_price, 4),
            requested_shares=entry_size,
            entry_edge=round(signal.edge, 4),
            entry_p_up=round(signal.p_up, 4),
            entry_seconds_left=seconds_left,
            spend=actual_spend,
            hold_to_expiry=_strategy.entry_hold_to_expiry(),
            order_id=order_id,
            source="market_buy",
            dry_run=False,
        )
        tg(
            f"✅ <b>BTC 5m Position opened</b>\n"
            f"Market: {pm_state.question[:80]}\n"
            f"Direction: {direction}\n"
            f"P(UP)={signal.p_up:.2%}  price={actual_price:.3f}  edge={signal.edge:.3f}\n"
            f"Shares: {actual_shares}/{entry_size}  Spend: ${actual_spend:.2f}\n"
            f"Order: {order_id}"
        )
        _entry_confirmation["count"] = 0
        _balance_cache[1] = 0.0
        return

    if order_id:
        if entry_mode == "market":
            log.warning(
                "Market buy returned order without matched status  order=%s  dir=%s  price=%.4f  shares=%d",
                order_id, direction, entry_price, entry_size,
            )
        else:
            log.info(
                "GTC buy placed  order=%s  dir=%s  price=%.4f  shares=%d  spend=$%.2f",
                order_id, direction, entry_price, entry_size, spend,
            )
            _write_training_event(
                "buy_order_posted",
                direction=direction,
                token_id=token_id,
                shares=entry_size,
                entry_price=round(entry_price, 4),
                spend=round(spend, 2),
                order_id=order_id,
                dry_run=False,
            )
            pos_store.open_pending_buy(
                order_id=order_id,
                condition_id=pm_state.condition_id,
                token_id=token_id,
                direction=direction,
                shares=entry_size,
                price=entry_price,
                edge=signal.edge,
                p_up=signal.p_up,
                seconds_left=seconds_left,
            )
            tg(
                f"📋 <b>BTC 5m Order placed</b>\n"
                f"Market: {pm_state.question[:80]}\n"
                f"Direction: {direction}\n"
                f"P(UP)={signal.p_up:.2%}  price={entry_price:.3f}  edge={signal.edge:.3f}\n"
                f"Shares: {entry_size}  Spend: ${spend:.2f}\n"
                f"Order: {order_id}"
            )
            _balance_cache[1] = 0.0
    else:
        log.error("%s buy order failed", entry_mode.capitalize())
        if entry_mode == "market":
            # FAK got killed (book moved against us during order flight). Schedule
            # a fast-retry instead of waiting the full 1s tick — a short settle
            # lets the WS cache absorb the book update that killed us.
            asyncio.create_task(
                _schedule_fast_retry("fak_no_match"),
                name="fast_retry_fak",
            )
    _entry_confirmation["count"] = 0


async def _tick(clob) -> None:
    log.debug(
        "Tick  settle=$%.2f  up=%.3f/%.3f  down=%.3f/%.3f  pos=%s  pending=%s",
        btc_state.current_price,
        pm_state.up_bid, pm_state.up_ask,
        pm_state.down_bid, pm_state.down_ask,
        pos_store.position.direction if pos_store.position else "none",
        pos_store.pending_buy.order_id[:10] if pos_store.pending_buy else "none",
    )
    _log_feed_diag()

    if pos_store.has_position():
        await _manage_position(clob)
        return

    if pos_store.has_pending_buy():
        await _check_pending_buy(clob)
        return

    if DRY_RUN:
        balance = float(os.getenv("DRY_RUN_BALANCE", "100.0"))
    else:
        if not pm_state.ready or not btc_state.ready:
            _log_feed_diag(reason="skip_balance:not_ready")
            return
        if not _feeds_are_fresh():
            await _refresh_pm_quotes_if_stale("pre_balance")
        if not _feeds_are_fresh():
            _log_feed_diag(force=True, reason="skip_balance:stale_feeds")
            return
        balance = await _get_balance(clob)
        if balance < BET_SIZE_MIN:
            log.info("Balance $%.2f below minimum — skipping entry", balance)
            return

    await _try_enter(clob, balance)


async def main() -> None:
    log.info("=" * 60)
    log.info("Polymarket BTC Bot")
    log.info("  DRY_RUN=%s  MIN_EDGE=%.3f  EVAL_INTERVAL=%dms", DRY_RUN, MIN_EDGE, EVAL_INTERVAL_MS)
    log.info("  ENTRY_HOLD_TO_EXPIRY=%s  MAX_ENTRY_PRICE=%.2f  ENTRY_MIN_SECS=%d", _strategy.entry_hold_to_expiry(), MAX_ENTRY_PRICE, ENTRY_MIN_SECONDS_LEFT)
    log.info("  BINANCE_WS=%s  BINANCE_STALE=%.1fs", bool(BINANCE_WS_URL), BINANCE_STALE_SECS)
    log.info("  CONFIRMATION_TICKS=%d  ENTRY_MAKER_OFFSET=%.3f", ENTRY_CONFIRMATION_TICKS, ENTRY_MAKER_OFFSET)
    for detail in _strategy.startup_details():
        log.info("  %s", detail)
    log.info("=" * 60)

    if not POLYMARKET_PK and not DRY_RUN:
        raise RuntimeError("POLYMARKET_PK not set and DRY_RUN=false — refusing to start")

    global _retry_now_event
    _retry_now_event = asyncio.Event()

    asyncio.create_task(run_binance_ws(), name="binance_ws")
    asyncio.create_task(run_btc_ws(), name="btc_ws")
    asyncio.create_task(run_pm_ws(), name="pm_ws")
    if not DRY_RUN:
        asyncio.create_task(run_user_ws(), name="user_ws")

    log.info("Waiting for WebSocket feeds …")
    ready = await _wait_for_ready(timeout=60)
    if not ready:
        log.warning("Feeds not ready after 60s — trading stays blocked until feeds recover")
    else:
        log.info("Feeds ready  Chainlink BTC=$%.2f  PM=%s", btc_state.current_price, pm_state.question[:50])

    clob = None
    if not DRY_RUN and ready:
        try:
            clob = await _init_clob()
        except Exception as exc:
            log.error("CLOB client init failed: %s", exc)
            raise

    last_cleanup_boundary = 0.0
    last_snapshot_condition_id = ""

    while True:
        tick_start = time.time()
        try:
            if not DRY_RUN and clob is None and btc_state.ready and pm_state.ready and _feeds_are_fresh():
                log.info("Feeds recovered — initializing trading client")
                clob = await _init_clob()
            current_cid = pm_state.condition_id
            if clob is not None and current_cid and current_cid != last_snapshot_condition_id:
                last_snapshot_condition_id = current_cid
                asyncio.create_task(
                    _write_balance_snapshot(clob, reason="new_market"),
                    name="balance_snapshot",
                )
                asyncio.create_task(
                    _sweep_redemptions(reason="new_market"),
                    name="redemption_sweep",
                )
                asyncio.create_task(
                    _prewarm_ctf_approvals(clob),
                    name="ctf_prewarm",
                )
            await _tick(clob)
        except Exception as exc:
            log.exception("Tick error: %s", exc)

        now = time.time()
        current_boundary = _next_bar_boundary()
        if current_boundary > 0 and now >= current_boundary and current_boundary > last_cleanup_boundary:
            last_cleanup_boundary = current_boundary
            stale_keys = [key for key in _stop_loss_reentry_guard if key[0] != pm_state.condition_id]
            for key in stale_keys:
                _stop_loss_reentry_guard.pop(key, None)

        elapsed = time.time() - tick_start
        remaining = max(0, EVAL_INTERVAL_SECS - elapsed)
        if remaining > 0 and _retry_now_event is not None:
            try:
                await asyncio.wait_for(_retry_now_event.wait(), timeout=remaining)
            except asyncio.TimeoutError:
                pass
            _retry_now_event.clear()
        elif remaining > 0:
            await asyncio.sleep(remaining)


if __name__ == "__main__":
    asyncio.run(main())
