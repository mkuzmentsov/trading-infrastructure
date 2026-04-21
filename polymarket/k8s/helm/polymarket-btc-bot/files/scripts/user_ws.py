"""
Polymarket authenticated User WebSocket — real-time fills and order lifecycle.

Replaces REST polling (get_order_fill_info, fetch_token_balance, has_trade_on_market)
with an event-driven state kept in `user_state`. One long-lived connection;
subscription is updated in place on each 5-minute market rollover (no reconnect).

Trade status progression (Polymarket docs):
    MATCHED -> MINED -> CONFIRMED    (success; off-chain match then on-chain settle)
    MATCHED -> RETRYING -> ...       (transient; eventually CONFIRMED or FAILED)
    MATCHED -> FAILED                (terminal failure; funds returned)

MATCHED is treated as terminal "filled" for position tracking: the off-chain match
commits the trade, matching the semantics of CLOB REST's status='matched'.
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Optional

import websockets

from config import (
    POLYMARKET_API_KEY,
    POLYMARKET_API_PASSPHRASE,
    POLYMARKET_API_SECRET,
    WS_HEARTBEAT_SECS,
    log,
)
from pm_ws import pm_state
from positions import pos_store

USER_WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/user"

_FILLED_STATUSES = {"matched", "mined", "confirmed"}
_CANCELED_STATUSES = {"canceled", "cancelled", "expired", "unmatched"}

# Runtime-provided creds (e.g. derived via ClobClient.create_or_derive_api_creds()).
# Populated by main.py after _init_clob(); takes precedence over env vars when set.
_runtime_creds: dict[str, str] | None = None


def set_runtime_creds(api_key: str, api_secret: str, api_passphrase: str) -> None:
    """Inject API creds at runtime (e.g. derived from the signing PK via CLOB).
    Called by main.py after the CLOB client is initialised. Safe to call repeatedly."""
    global _runtime_creds
    if not (api_key and api_secret and api_passphrase):
        return
    _runtime_creds = {
        "apiKey": api_key,
        "secret": api_secret,
        "passphrase": api_passphrase,
    }
    log.info("USER_WS runtime creds set (key=%s…)", api_key[:8])


def _current_creds() -> dict[str, str] | None:
    if _runtime_creds:
        return _runtime_creds
    if POLYMARKET_API_KEY and POLYMARKET_API_SECRET and POLYMARKET_API_PASSPHRASE:
        return {
            "apiKey": POLYMARKET_API_KEY,
            "secret": POLYMARKET_API_SECRET,
            "passphrase": POLYMARKET_API_PASSPHRASE,
        }
    return None


def _coerce_float(x: object, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default


class UserState:
    def __init__(self) -> None:
        # Per-order fill state populated from trade events
        self.order_status: dict[str, str] = {}       # order_id -> "filled"/"cancelled"/"open"/"unknown"
        self.matched_shares: dict[str, int] = {}     # order_id -> cumulative matched whole shares
        self.avg_price: dict[str, float] = {}        # order_id -> last observed avg/trade price

        # Per-token net holdings inferred from trade events (BUY +, SELL −).
        # Used as a source of truth for residuals / hold-to-expiry checks.
        self.token_shares: dict[str, float] = {}     # token_id -> net shares

        # Dedupe: Polymarket re-emits the same trade on each status transition.
        self._seen_events: set[tuple[str, str]] = set()

        # Session metadata
        self.subscribed_market: str = ""
        self.session_id: int = 0
        self.connect_count: int = 0
        self.last_ws_connect_at: float = 0.0
        self.last_ws_message_at: float = 0.0
        self.last_heartbeat_ts: float = 0.0
        self.trade_events: int = 0
        self.order_events: int = 0

    # ── Public API for main.py ───────────────────────────────────────────────
    def get_order_fill_info(
        self,
        order_id: str,
        fallback_price: float,
        fallback_shares: int,
    ) -> tuple[str, int, float]:
        """Drop-in replacement for the deleted clob.get_order_fill_info.

        Returns (status, matched_whole_shares, avg_price). Status is one of
        "filled" / "cancelled" / "open" / "unknown". "unknown" means we have
        not yet received any event for this order.
        """
        status = self.order_status.get(order_id, "unknown")
        shares = self.matched_shares.get(order_id, 0)
        price = self.avg_price.get(order_id, fallback_price)
        if status == "filled" and shares <= 0:
            shares = fallback_shares
        return status, shares, price

    def get_token_balance(self, token_id: str) -> float:
        return max(0.0, self.token_shares.get(token_id, 0.0))

    def is_ws_fresh(self, max_age_secs: float = 60.0) -> bool:
        if self.last_ws_message_at <= 0:
            return False
        return (time.time() - self.last_ws_message_at) <= max_age_secs


user_state = UserState()


# ── Event handlers ───────────────────────────────────────────────────────────
def _apply_trade(msg: dict) -> None:
    """Accumulate fills per order_id and per token_id from a trade event."""
    trade_id = str(msg.get("id") or "")
    raw_status = str(msg.get("status") or "").lower()
    if not trade_id or not raw_status:
        return

    key = (trade_id, raw_status)
    if key in user_state._seen_events:
        return
    user_state._seen_events.add(key)

    side = str(msg.get("side") or "").upper()
    size = _coerce_float(msg.get("size"), 0.0)
    price = _coerce_float(msg.get("price"), 0.0)
    asset_id = str(msg.get("asset_id") or "")

    order_ids: list[str] = []
    taker = str(msg.get("taker_order_id") or "")
    if taker:
        order_ids.append(taker)
    for m in msg.get("maker_orders") or []:
        if isinstance(m, dict):
            oid = str(m.get("order_id") or "")
            if oid:
                order_ids.append(oid)

    # Only count on-chain position deltas ONCE per trade, on first MATCHED event.
    is_first_seen = not any(
        (trade_id, s) in user_state._seen_events
        for s in _FILLED_STATUSES | _CANCELED_STATUSES
        if s != raw_status
    )

    user_state.trade_events += 1

    if raw_status in _FILLED_STATUSES:
        for oid in order_ids:
            user_state.order_status[oid] = "filled"
            if is_first_seen:
                user_state.matched_shares[oid] = user_state.matched_shares.get(oid, 0) + int(size)
            if price > 0:
                user_state.avg_price[oid] = price

        if is_first_seen and asset_id and size > 0:
            delta = size if side == "BUY" else -size
            user_state.token_shares[asset_id] = user_state.token_shares.get(asset_id, 0.0) + delta

        log.info(
            "USER_WS trade %s  id=%s side=%s size=%.2f price=%.4f order=%s",
            raw_status.upper(),
            trade_id[:10],
            side,
            size,
            price,
            (order_ids[0][:12] if order_ids else "?"),
        )
    elif raw_status in _CANCELED_STATUSES or raw_status == "failed":
        for oid in order_ids:
            user_state.order_status[oid] = "cancelled"
        log.info(
            "USER_WS trade %s  id=%s order=%s",
            raw_status.upper(),
            trade_id[:10],
            (order_ids[0][:12] if order_ids else "?"),
        )


def _apply_order(msg: dict) -> None:
    """Track order lifecycle events (placement, cancellation, full match)."""
    order_id = str(msg.get("id") or msg.get("order_id") or "")
    if not order_id:
        return
    raw_status = str(msg.get("status") or msg.get("type") or "").lower()
    size_matched = _coerce_float(msg.get("size_matched"), 0.0)
    price = _coerce_float(msg.get("price"), 0.0)

    user_state.order_events += 1

    if raw_status in _FILLED_STATUSES:
        user_state.order_status[order_id] = "filled"
        if size_matched > 0:
            user_state.matched_shares[order_id] = max(
                user_state.matched_shares.get(order_id, 0), int(size_matched)
            )
        if price > 0 and order_id not in user_state.avg_price:
            user_state.avg_price[order_id] = price
    elif raw_status in _CANCELED_STATUSES:
        user_state.order_status[order_id] = "cancelled"
    elif raw_status in ("placement", "update", "open", "live"):
        user_state.order_status.setdefault(order_id, "open")


async def _subscribe(ws, market: str, is_initial: bool) -> None:
    """Send auth+subscribe on first connect, or an incremental update on rollover."""
    if is_initial:
        creds = _current_creds() or {}
        payload = {
            "auth": creds,
            "markets": [market],
            "type": "user",
        }
    else:
        payload = {"operation": "subscribe", "markets": [market]}
    await ws.send(json.dumps(payload))


async def _unsubscribe(ws, market: str) -> None:
    await ws.send(json.dumps({"operation": "unsubscribe", "markets": [market]}))


async def _handle_rollover(ws) -> None:
    """If pm_state moved to a new market, shift our subscription in place."""
    current = pm_state.condition_id
    if not current or current == user_state.subscribed_market:
        return

    old = user_state.subscribed_market
    if old:
        try:
            await _unsubscribe(ws, old)
        except Exception as exc:
            log.warning("USER_WS unsubscribe failed  old=%s err=%s", old[:16], exc)
    await _subscribe(ws, current, is_initial=False)
    user_state.subscribed_market = current
    log.info(
        "USER_WS rolled subscription  session=%d  old=%s  new=%s",
        user_state.session_id,
        old[:16] if old else "-",
        current[:16],
    )


def _log_heartbeat(force: bool = False) -> None:
    now = time.time()
    if not force and now - user_state.last_heartbeat_ts < WS_HEARTBEAT_SECS:
        return
    user_state.last_heartbeat_ts = now
    pos_shares = pos_store.position.shares if pos_store.position else 0
    msg_age = now - user_state.last_ws_message_at if user_state.last_ws_message_at > 0 else -1
    log.info(
        "USER_WS heartbeat  session=%d market=%s trades=%d orders=%d pos_shares=%d msg_age=%.1fs",
        user_state.session_id,
        user_state.subscribed_market[:16] if user_state.subscribed_market else "-",
        user_state.trade_events,
        user_state.order_events,
        pos_shares,
        msg_age,
    )


def _dispatch_message(raw: str) -> None:
    stripped = raw.strip()
    if not stripped or stripped == "PONG" or stripped[0] not in "[{":
        return
    try:
        msgs = json.loads(stripped)
    except Exception as exc:
        log.error("USER_WS JSON parse error: %s  raw=%s", exc, stripped[:200])
        return
    if not isinstance(msgs, list):
        msgs = [msgs]
    for msg in msgs:
        if not isinstance(msg, dict):
            continue
        event_type = str(msg.get("event_type") or msg.get("type") or "").lower()
        if event_type == "trade":
            _apply_trade(msg)
        elif event_type == "order":
            _apply_order(msg)
        else:
            log.debug("USER_WS unknown event_type=%s msg=%s", event_type, str(msg)[:200])


async def run_user_ws() -> None:
    """Long-lived loop. Reconnects only on real socket failure; subscription
    changes use `operation: subscribe`/`unsubscribe` on the same connection.

    Waits for both (a) a pm_ws market to subscribe to, and (b) API creds —
    either from env or injected at runtime via `set_runtime_creds()` once the
    CLOB client has derived them from the signing key."""
    _creds_logged = False
    backoff = 1
    while True:
        try:
            if _current_creds() is None:
                if not _creds_logged:
                    log.info("USER_WS waiting for API creds (env or runtime-derived) …")
                    _creds_logged = True
                await asyncio.sleep(1.0)
                continue
            # Wait for pm_ws to publish a market so we have something to subscribe to
            if not pm_state.condition_id:
                await asyncio.sleep(1.0)
                continue

            log.info("Connecting to Polymarket User WS  market=%s", pm_state.condition_id[:16])
            async with websockets.connect(USER_WS_URL, ping_interval=20, ping_timeout=30) as ws:
                user_state.session_id += 1
                user_state.connect_count += 1
                user_state.last_ws_connect_at = time.time()
                initial_market = pm_state.condition_id
                await _subscribe(ws, initial_market, is_initial=True)
                user_state.subscribed_market = initial_market
                log.info(
                    "USER_WS subscribed  session=%d  market=%s",
                    user_state.session_id,
                    initial_market[:16],
                )
                backoff = 1

                while True:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                    except asyncio.TimeoutError:
                        raw = ""

                    if raw:
                        user_state.last_ws_message_at = time.time()
                        _dispatch_message(raw)

                    await _handle_rollover(ws)
                    _log_heartbeat()

        except (websockets.ConnectionClosed, ConnectionError, OSError) as exc:
            log.warning("USER_WS disconnected: %s — reconnect in %ds", exc, backoff)
        except Exception as exc:
            log.exception("USER_WS unexpected error: %s — reconnect in %ds", exc, backoff)

        user_state.subscribed_market = ""
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, 60)
