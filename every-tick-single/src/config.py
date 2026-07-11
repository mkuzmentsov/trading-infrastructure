"""
Shared configuration — env vars, constants, logging.
"""
from __future__ import annotations

import logging
import os
import warnings

warnings.filterwarnings("ignore")

# ── Logging ───────────────────────────────────────────────────────────────────
APP_LOG_LEVEL = os.getenv("APP_LOG_LEVEL", "INFO").strip().upper()
_LOG_LEVEL = getattr(logging, APP_LOG_LEVEL, logging.INFO)
logging.basicConfig(
    level=_LOG_LEVEL,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("pm_btc")
log.setLevel(_LOG_LEVEL)
logging.getLogger("websockets").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)

# ── Bot behaviour ─────────────────────────────────────────────────────────────
DRY_RUN       = os.getenv("DRY_RUN", "true").lower() == "true"
LOOP_INTERVAL = int(os.getenv("LOOP_INTERVAL_SECS", "300"))

# Coin the bot trades. Drives the gamma slug ({coin}-updown-5m-{ts}); the spot
# feeds (BINANCE_WS_URL / POLYMARKET_RTDS_SYMBOL) must be set consistently.
COIN = os.getenv("COIN", "btc").strip().lower()

# ── Paper mode / maker-rebate quoting (every-tick-trader) ─────────────────────
# PAPER_MODE=true → the maker_rebate strategy simulates resting quotes against
# the live feed; no CLOB calls are made anywhere on the maker path.
PAPER_MODE = os.getenv("PAPER_MODE", "true").lower() == "true"
QUOTE_HALF_SPREAD = float(os.getenv("QUOTE_HALF_SPREAD", "0.02"))   # bid = mid − halfSpread
QUOTE_FLOOR = float(os.getenv("QUOTE_FLOOR", "0.30"))               # high-rebate p(1−p) band
QUOTE_CEIL = float(os.getenv("QUOTE_CEIL", "0.70"))
QUOTE_SIZE = int(os.getenv("QUOTE_SIZE", "10"))                     # shares per quote (legacy fallback)
# USD-denominated per-bar entry budget (bracket mode, paper AND live):
# shares = QUOTE_NOTIONAL_USD / entry_price, floored to whole shares, then
# clamped UP to the market's orderMinSize (gamma payload; fallback 5).
# Unset/0 → legacy QUOTE_SIZE shares. Start 5, raise to 10 when ready.
QUOTE_NOTIONAL_USD = float(os.getenv("QUOTE_NOTIONAL_USD", "5.0"))
QUOTE_CUTOFF_SECS = int(os.getenv("QUOTE_CUTOFF_SECS", "60"))       # cancel all, no new quotes
QUOTE_WARMUP_SECS = int(os.getenv("QUOTE_WARMUP_SECS", "10"))       # wait after bar open
MIN_PAIR_EDGE = float(os.getenv("MIN_PAIR_EDGE", "0.01"))           # up_q + down_q < 1 − edge
# bracket (default): predict the side (math-signal p_up, momentum fallback),
# rest ONE maker BUY at min(mid − halfSpread, ENTRY_PRICE_CAP); on fill place a
# maker TP SELL at TAKE_PROFIT_PRICE and monitor a taker stop when the token's
# best bid <= STOP_LOSS_PRICE. Max MAX_FILLS_PER_BAR entry fills per bar; side
# locked once chosen; unexited inventory settles at expiry.
# one_sided: rest a single bid per bar (side per QUOTE_SIDE), hold fills to
# expiry, collect rebates — profitable iff fill win-rate stays within the
# rebate margin of the fill price (EV/share = q − p; see PLAN.md).
# two_sided: quote both tokens with the pair-lock constraint (backlog: A/B test).
QUOTE_MODE = os.getenv("QUOTE_MODE", "bracket").strip().lower()
ENTRY_PRICE_CAP = float(os.getenv("ENTRY_PRICE_CAP", "0.50"))       # bracket: never bid above (≤50c = max rebate weight)
# fixed (default since 2026-07-03): rest the entry AT ENTRY_PRICE_CAP (clamped
# to ask − tick if that would cross — always maker, never taker) and leave it
# alone until fill or cutoff: no mid-chasing, no repricing. Paper data showed
# chase fills below ~0.45 and repriced/late fills are adversely selected
# (q − p < 0); the only profitable segment was ~50c fills early in the bar.
# chase: the original behavior — bid min(mid − QUOTE_HALF_SPREAD, cap) and
# cancel/replace on REPRICE_TICKS / REPRICE_Z drift.
ENTRY_STYLE = os.getenv("ENTRY_STYLE", "fixed").strip().lower()
# one: rest the entry only on the predicted side (p_up estimate at bar open).
# both: rest the fixed entry on UP AND DOWN — a both-fill pair costs
# 2×ENTRY_PRICE_CAP < 1 and always settles at $1 (locked profit + double
# rebate weight); a single fill is the one-sided bet without needing the
# side prediction (which measured ~0 edge at bar open).
BRACKET_SIDES = os.getenv("BRACKET_SIDES", "one").strip().lower()
# Periodic in-bar book snapshot event (offline analysis: recovery curves,
# book-imbalance toxicity, fill-time conditioning). 0 disables.
BAR_SNAPSHOT_SECS = int(os.getenv("BAR_SNAPSHOT_SECS", "15"))
# Side picker for BRACKET_SIDES=one: "signal" (p_up estimate; measured
# degenerate ~always-UP at bar open) or "alternate" (flip each bar — clean
# control that removes drift bias and isolates maker economics).
BRACKET_SIDE_RULE = os.getenv("BRACKET_SIDE_RULE", "alternate").strip().lower()
TAKE_PROFIT_PRICE = float(os.getenv("TAKE_PROFIT_PRICE", "0.99"))   # bracket: resting maker SELL
STOP_LOSS_PRICE = float(os.getenv("STOP_LOSS_PRICE", "0.10"))       # bracket: taker SELL when best_bid <= this
MAX_FILLS_PER_BAR = int(os.getenv("MAX_FILLS_PER_BAR", "1"))        # bracket: entry fills per bar (no refill conveyor)
# QUOTE_SIDE for one_sided: "cheaper" (side with mid ≤ 0.5 — max p(1−p) rebate
# weight, least $ at risk), "up", "down", or "alternate" (flip each bar).
QUOTE_SIDE = os.getenv("QUOTE_SIDE", "cheaper").strip().lower()
REPRICE_TICKS = float(os.getenv("REPRICE_TICKS", "0.01"))           # mid drift → cancel/replace
REPRICE_Z = float(os.getenv("REPRICE_Z", "1.5"))                    # spot z-move → cancel/replace
MAX_INVENTORY_SHARES = int(os.getenv("MAX_INVENTORY_SHARES", "50")) # per side per bar
MAKER_FEE_RATE = float(os.getenv("MAKER_FEE_RATE", "0.07"))         # crypto taker feeRate (rebate weight)
# Trade feed considered live if a last_trade_price event arrived within this
# window; otherwise paper fills fall back to book-cross detection.
PAPER_TRADE_FEED_TIMEOUT_SECS = float(os.getenv("PAPER_TRADE_FEED_TIMEOUT_SECS", "600"))

# ── LIVE trading (maker_rebate real-order path) ───────────────────────────────
# All three gates must align or the bot refuses to start:
#   LIVE_TRADING=true  AND  PAPER_MODE=false  AND  DRY_RUN=false  AND creds set.
LIVE_TRADING = os.getenv("LIVE_TRADING", "false").lower() == "true"
# Per-order notional cap (USD). BUY quotes are clamped down to this.
LIVE_MAX_ORDER_USD = float(os.getenv("LIVE_MAX_ORDER_USD", "5"))
# Daily realized-loss kill switch (USD). When the UTC day's realized loss
# exceeds this, cancel everything and stop quoting until the next UTC day.
LIVE_MAX_DAILY_LOSS_USD = float(os.getenv("LIVE_MAX_DAILY_LOSS_USD", "25"))
# Live warmup default is 0 (place the entry the instant the bar rolls — the
# latency edge). Respected if explicitly set. Paper keeps QUOTE_WARMUP_SECS.
LIVE_QUOTE_WARMUP_SECS = int(os.getenv("LIVE_QUOTE_WARMUP_SECS", "0"))
# How long before bar end the NEXT bar's market is pre-discovered (gamma slug
# is deterministic, so at bar roll no gamma call is needed).
PREDISCOVERY_LEAD_SECS = float(os.getenv("PREDISCOVERY_LEAD_SECS", "30"))
# REST open-order reconciliation cadence (fallback when user_ws misses a fill).
LIVE_RECONCILE_SECS = float(os.getenv("LIVE_RECONCILE_SECS", "30"))

BET_SIZE_MIN = float(os.getenv("BET_SIZE_MIN", "0.50"))
BET_SIZE_MAX = float(os.getenv("BET_SIZE_MAX", "5.00"))
MAX_BUDGET_FRACTION = float(os.getenv("MAX_BUDGET_FRACTION", "0.10"))
MIN_POSITION_SHARES = int(os.getenv("MIN_POSITION_SHARES", "6"))
ML_BLEND_WEIGHT = float(os.getenv("ML_BLEND_WEIGHT", "0.50"))
STRATEGY_NAME = os.getenv("STRATEGY_NAME", "maker_rebate").strip().lower()

# ── Signal parameters ─────────────────────────────────────────────────────────
MIN_EDGE = float(os.getenv("MIN_EDGE", "0.04"))
KELLY_SCALE = float(os.getenv("KELLY_SCALE", "0.5"))
TAKER_FEE_BPS = float(os.getenv("TAKER_FEE_BPS", "0"))  # Polymarket taker fee in basis points

DRIFT_A3 = float(os.getenv("DRIFT_A3", "0.003"))

ENTRY_MIN_SECONDS_LEFT = int(os.getenv("ENTRY_MIN_SECONDS_LEFT", "60"))
MAX_ENTRY_SPREAD = float(os.getenv("MAX_ENTRY_SPREAD", "0.04"))
MIN_ENTRY_PRICE = float(os.getenv("MIN_ENTRY_PRICE", "0.05"))
MAX_ENTRY_PRICE = float(os.getenv("MAX_ENTRY_PRICE", "0.60"))
MODEL_PROB_FLOOR = float(os.getenv("MODEL_PROB_FLOOR", "0.05"))
MODEL_PROB_CEIL = float(os.getenv("MODEL_PROB_CEIL", "0.95"))
ENTRY_ORDER_TIMEOUT_SECS = int(os.getenv("ENTRY_ORDER_TIMEOUT_SECS", "18"))
ENTRY_SLIPPAGE_CAP = float(os.getenv("ENTRY_SLIPPAGE_CAP", "0.06"))  # max extra above quoted ask for FAK limit
ENTRY_MAKER_OFFSET = float(os.getenv("ENTRY_MAKER_OFFSET", "0.0"))  # 0 = taker (current); >0 = post below ask
ENTRY_REPLACE_MIN_AGE_SECS = int(os.getenv("ENTRY_REPLACE_MIN_AGE_SECS", "6"))
ENTRY_REPLACE_GAP = float(os.getenv("ENTRY_REPLACE_GAP", "0.02"))
ENTRY_BOOK_MAX_TAKE_FRACTION = float(os.getenv("ENTRY_BOOK_MAX_TAKE_FRACTION", "0.35"))
ENTRY_CONFIRMATION_TICKS = int(os.getenv("ENTRY_CONFIRMATION_TICKS", "1"))
CONTRARIAN_TAIL_MAX_PRICE = float(os.getenv("CONTRARIAN_TAIL_MAX_PRICE", "0.25"))
CONTRARIAN_MOVE_FILTER = float(os.getenv("CONTRARIAN_MOVE_FILTER", "0.0015"))
FILTER_CONTRARIAN_ENTRIES = os.getenv("FILTER_CONTRARIAN_ENTRIES", "false").lower() == "true"
ULTRA_CHEAP_TAIL_PRICE = float(os.getenv("ULTRA_CHEAP_TAIL_PRICE", "0.10"))
REENTRY_EDGE_PENALTY = float(os.getenv("REENTRY_EDGE_PENALTY", "0.05"))
STOP_LOSS_MARKET_LIMIT = int(os.getenv("STOP_LOSS_MARKET_LIMIT", "1"))
# Block re-entry on (cid, direction) if same-direction bid has dropped by more
# than this since the last exit on that pair (any exit reason). 0 disables.
# Calibrated 2026-04-23: 0.10 catches collapsing-bid cascades without breaking
# small-wobble re-entries that recover.
BLOCK_REENTRY_IF_BID_DROP_GT = float(os.getenv("BLOCK_REENTRY_IF_BID_DROP_GT", "0"))
# Comma-separated set of exit reasons after which re-entry on the same
# (condition_id, direction) is blocked for the rest of the bar. Empty disables.
# Replay 2026-04-24 on bundle 20260424_065920: setting to
# "late_bar_salvage,force_close" raised PnL +$95→+$112 (+18%) and WR 67%→74%.
BLOCK_REENTRY_AFTER_REASONS = {
    r.strip() for r in os.getenv("BLOCK_REENTRY_AFTER_REASONS", "").split(",") if r.strip()
}
# Global (cross-market) cooldown after a close with one of the matching reasons
# in BLOCK_REENTRY_AFTER_REASONS. Per-market guard above only blocks re-entry
# on the same (cid, direction); doesn't catch consecutive cross-market salvage
# cascades like bundle 20260427_075827 (Sun 19:24/29/34 lost $32 in 10 min on
# three sequential market bars, each a fresh cid). 0 disables.
BLOCK_GLOBAL_AFTER_REASONS_SECS = int(os.getenv("BLOCK_GLOBAL_AFTER_REASONS_SECS", "0"))
SL_ARM_DELAY_SECS = int(os.getenv("SL_ARM_DELAY_SECS", "60"))
ULTRA_CHEAP_SL_DELAY_SECS = int(os.getenv("ULTRA_CHEAP_SL_DELAY_SECS", "120"))
SL_MIN_ADVERSE_BTC = float(os.getenv("SL_MIN_ADVERSE_BTC", "0.0015"))

# ── Smart entry filters ──────────────────────────────────────────────────────
MIN_BTC_DISTANCE = float(os.getenv("MIN_BTC_DISTANCE", "0.0004"))
MIN_BOOK_DIVERGENCE = float(os.getenv("MIN_BOOK_DIVERGENCE", "0.04"))
LATE_ENTRY_SECS = int(os.getenv("LATE_ENTRY_SECS", "90"))
LATE_ENTRY_EDGE_DISCOUNT = float(os.getenv("LATE_ENTRY_EDGE_DISCOUNT", "0.30"))

# ── Fast reference feed (Binance or custom 5-venue aggregate) ─────────────────
# PRICE_LEAD_SOURCE: "binance" (single-venue, default) or "aggregate" (custom
# multi-exchange median from core.agg_ws). The aggregate feeds the SAME
# binance_state, so binance_price / price_divergence / best_price transparently
# use whichever source is selected.
PRICE_LEAD_SOURCE = os.getenv("PRICE_LEAD_SOURCE", "binance").strip().lower()
BINANCE_WS_URL = os.getenv("BINANCE_WS_URL", "wss://stream.binance.com:9443/ws/btcusdt@aggTrade")
BINANCE_STALE_SECS = float(os.getenv("BINANCE_STALE_SECS", "5.0"))

# ── Hold-to-expiry strategy ─────────────────────────────────────────────────
HOLD_TO_EXPIRY_DEFAULT = os.getenv("HOLD_TO_EXPIRY_DEFAULT", "true").lower() == "true"
# ── Position management ───────────────────────────────────────────────────────
EVAL_INTERVAL_MS = max(1, int(float(os.getenv("EVAL_INTERVAL_MS", "5000"))))
EVAL_INTERVAL_SECS = EVAL_INTERVAL_MS / 1000.0
TAKE_PROFIT = float(os.getenv("TAKE_PROFIT", "0.15"))
STOP_LOSS = float(os.getenv("STOP_LOSS", "0.08"))
MIN_EXIT_BID = float(os.getenv("MIN_EXIT_BID", "0.03"))
ORDER_REPLACE_GAP = float(os.getenv("ORDER_REPLACE_GAP", "0.05"))
AGGRESSIVE_EXIT_SLIPPAGE = float(os.getenv("AGGRESSIVE_EXIT_SLIPPAGE", "0.02"))
TRAILING_ARM_GAIN = float(os.getenv("TRAILING_ARM_GAIN", "0.20"))
TRAILING_STOP_GAP = float(os.getenv("TRAILING_STOP_GAP", "0.03"))
THESIS_MIN_BTC_DISTANCE = float(os.getenv("THESIS_MIN_BTC_DISTANCE", "0.002"))  # suppress thesis_decay when bar is already this far in our favor

# ── Polymarket credentials ────────────────────────────────────────────────────
POLYMARKET_PK               = os.getenv("POLYMARKET_PK",               "")
POLYMARKET_ADDRESS          = os.getenv("POLYMARKET_ADDRESS",           "")
POLYMARKET_API_KEY          = os.getenv("POLYMARKET_API_KEY",           "")
POLYMARKET_API_SECRET       = os.getenv("POLYMARKET_API_SECRET",        "")
POLYMARKET_API_PASSPHRASE   = os.getenv("POLYMARKET_API_PASSPHRASE",    "")
SIGNATURE_TYPE              = int(os.getenv("POLYMARKET_SIGNATURE_TYPE", "0"))
POLYMARKET_FUNDER           = os.getenv("POLYMARKET_FUNDER",            "")

# ── Telegram ──────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN",   "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ── API endpoints ─────────────────────────────────────────────────────────────
GAMMA_API     = "https://gamma-api.polymarket.com"
CLOB_HOST     = "https://clob.polymarket.com"
DATA_API      = "https://data-api.polymarket.com"
POLYMARKET_WS = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
POLYMARKET_RTDS_WS = os.getenv("POLYMARKET_RTDS_WS", "wss://ws-live-data.polymarket.com")
POLYMARKET_RTDS_SYMBOL = os.getenv("POLYMARKET_RTDS_SYMBOL", "btc/usd")
TRAINING_LOG_PATH = os.getenv("TRAINING_LOG_PATH", "").strip()
TRAINING_EVENT_LOG_PATH = os.getenv("TRAINING_EVENT_LOG_PATH", "").strip()

WS_HEARTBEAT_SECS = int(os.getenv("WS_HEARTBEAT_SECS", "30"))
FEED_STALE_SECS = int(os.getenv("FEED_STALE_SECS", "20"))

# ── On-chain / Polygon ────────────────────────────────────────────────────────
CHAIN_ID     = 137
CTF_CONTRACT = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
USDC_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
POLYGON_RPC  = os.getenv("POLYGON_RPC_URL", "https://rpc.ankr.com/polygon")

# ── Polymarket Relayer (gasless on-chain submission; Gnosis Safe) ──────────────
# When USE_RELAYER=true, on-chain Safe txs (redemptions) are submitted through
# Polymarket's relayer-v2 instead of self-signed eth_sendRawTransaction (no gas,
# no MATIC balance needed). Requires SIGNATURE_TYPE=2 + a funder (the Safe).
USE_RELAYER             = os.getenv("POLYMARKET_USE_RELAYER", "false").lower() in ("true", "1", "yes")
RELAYER_URL             = os.getenv("POLYMARKET_RELAYER_URL", "https://relayer-v2.polymarket.com")
RELAYER_API_KEY         = os.getenv("POLYMARKET_RELAYER_API_KEY", "")
RELAYER_API_KEY_ADDRESS = os.getenv("POLYMARKET_RELAYER_API_KEY_ADDRESS", "")


# ── Startup validation ────────────────────────────────────────────────────────
# Fail fast on numerically insane values; warn on unknown enum-ish values
# (unknown values historically fell through to a default branch — warning
# keeps that behavior visible without changing it).

def _validate() -> None:
    def _die(msg: str) -> None:
        raise ValueError(f"config: {msg}")

    if not (0 < ENTRY_PRICE_CAP < 1):
        _die(f"ENTRY_PRICE_CAP={ENTRY_PRICE_CAP} must be in (0, 1)")
    if not (0 <= QUOTE_FLOOR < QUOTE_CEIL <= 1):
        _die(f"QUOTE_FLOOR/QUOTE_CEIL=({QUOTE_FLOOR}, {QUOTE_CEIL}) must satisfy 0<=floor<ceil<=1")
    if not (0 < TAKE_PROFIT_PRICE <= 1):
        _die(f"TAKE_PROFIT_PRICE={TAKE_PROFIT_PRICE} must be in (0, 1]")
    if not (0 <= STOP_LOSS_PRICE < 1):
        _die(f"STOP_LOSS_PRICE={STOP_LOSS_PRICE} must be in [0, 1) (0 disables)")
    if QUOTE_NOTIONAL_USD < 0:
        _die(f"QUOTE_NOTIONAL_USD={QUOTE_NOTIONAL_USD} must be >= 0 (0 = legacy QUOTE_SIZE)")
    if LOOP_INTERVAL <= 0:
        _die(f"LOOP_INTERVAL_SECS={LOOP_INTERVAL} must be > 0")
    if BAR_SNAPSHOT_SECS < 0:
        _die(f"BAR_SNAPSHOT_SECS={BAR_SNAPSHOT_SECS} must be >= 0 (0 disables)")
    if MAX_FILLS_PER_BAR < 1:
        _die(f"MAX_FILLS_PER_BAR={MAX_FILLS_PER_BAR} must be >= 1")
    for name, val, allowed in (
        ("QUOTE_MODE", QUOTE_MODE, {"bracket", "one_sided", "two_sided"}),
        ("BRACKET_SIDES", BRACKET_SIDES, {"one", "both"}),
        ("BRACKET_SIDE_RULE", BRACKET_SIDE_RULE, {"alternate", "signal"}),
        ("ENTRY_STYLE", ENTRY_STYLE, {"fixed", "chase"}),
    ):
        if val not in allowed:
            log.warning("config: %s=%r not in %s — falls through to default behavior", name, val, allowed)


_validate()
