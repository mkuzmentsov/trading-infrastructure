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
SIGNAL_MODEL = os.getenv("SIGNAL_MODEL", "math").strip().lower()
ML_BLEND_WEIGHT = float(os.getenv("ML_BLEND_WEIGHT", "0.50"))
STRATEGY_NAME = os.getenv("STRATEGY_NAME", "latency_arb_hold").strip().lower()
ENTRY_GATE_THRESHOLD = float(os.getenv("ENTRY_GATE_THRESHOLD", "0.55"))
ENTRY_GATE_MIN_PRICE = float(os.getenv("ENTRY_GATE_MIN_PRICE", "0.30"))
ENTRY_GATE_CHEAP_OVERRIDE_SCORE = float(os.getenv("ENTRY_GATE_CHEAP_OVERRIDE_SCORE", "0.78"))
ENTRY_GATE_CHEAP_OVERRIDE_EDGE = float(os.getenv("ENTRY_GATE_CHEAP_OVERRIDE_EDGE", "0.20"))

# ── Signal parameters ─────────────────────────────────────────────────────────
MIN_EDGE = float(os.getenv("MIN_EDGE", "0.04"))
COST_BUFFER = float(os.getenv("COST_BUFFER", "0.02"))
KELLY_SCALE = float(os.getenv("KELLY_SCALE", "0.5"))
TAKER_FEE_BPS = float(os.getenv("TAKER_FEE_BPS", "0"))  # Polymarket taker fee in basis points

DRIFT_A1 = float(os.getenv("DRIFT_A1", "1.8"))
DRIFT_A2 = float(os.getenv("DRIFT_A2", "1.2"))
DRIFT_A3 = float(os.getenv("DRIFT_A3", "0.003"))
DRIFT_A4 = float(os.getenv("DRIFT_A4", "0.8"))

ENTRY_MIN_SECONDS_LEFT = int(os.getenv("ENTRY_MIN_SECONDS_LEFT", "60"))
MAX_ENTRY_SPREAD = float(os.getenv("MAX_ENTRY_SPREAD", "0.04"))
MIN_ENTRY_PRICE = float(os.getenv("MIN_ENTRY_PRICE", "0.05"))
MAX_ENTRY_PRICE = float(os.getenv("MAX_ENTRY_PRICE", "0.60"))
SOURCE_MISMATCH_BUFFER = float(os.getenv("SOURCE_MISMATCH_BUFFER", "0.01"))
MODEL_PROB_SHRINK = float(os.getenv("MODEL_PROB_SHRINK", "0.65"))
MODEL_PROB_FLOOR = float(os.getenv("MODEL_PROB_FLOOR", "0.05"))
MODEL_PROB_CEIL = float(os.getenv("MODEL_PROB_CEIL", "0.95"))
EARLY_BAR_MIN_CONFIDENCE = float(os.getenv("EARLY_BAR_MIN_CONFIDENCE", "0.35"))
EARLY_BAR_RAMP_SECS = int(os.getenv("EARLY_BAR_RAMP_SECS", "90"))
ENTRY_ORDER_MODE = os.getenv("ENTRY_ORDER_MODE", "market").strip().lower()  # "market" or "gtc"
ENTRY_ORDER_TIMEOUT_SECS = int(os.getenv("ENTRY_ORDER_TIMEOUT_SECS", "18"))
ENTRY_SLIPPAGE_CAP = float(os.getenv("ENTRY_SLIPPAGE_CAP", "0.06"))  # max extra above quoted ask for FAK limit
ENTRY_MAKER_OFFSET = float(os.getenv("ENTRY_MAKER_OFFSET", "0.0"))  # 0 = taker (current); >0 = post below ask
ENTRY_REPLACE_MIN_AGE_SECS = int(os.getenv("ENTRY_REPLACE_MIN_AGE_SECS", "6"))
ENTRY_REPLACE_GAP = float(os.getenv("ENTRY_REPLACE_GAP", "0.02"))
ENTRY_BOOK_MAX_TAKE_FRACTION = float(os.getenv("ENTRY_BOOK_MAX_TAKE_FRACTION", "0.35"))
MAX_ABS_DRIFT = float(os.getenv("MAX_ABS_DRIFT", "0.004"))
ENTRY_CONFIRMATION_TICKS = int(os.getenv("ENTRY_CONFIRMATION_TICKS", "1"))
CONTRARIAN_TAIL_MAX_PRICE = float(os.getenv("CONTRARIAN_TAIL_MAX_PRICE", "0.25"))
CONTRARIAN_MOVE_FILTER = float(os.getenv("CONTRARIAN_MOVE_FILTER", "0.0015"))
FILTER_CONTRARIAN_ENTRIES = os.getenv("FILTER_CONTRARIAN_ENTRIES", "false").lower() == "true"
CHEAP_TAIL_EDGE_BONUS = float(os.getenv("CHEAP_TAIL_EDGE_BONUS", "0.05"))
LATE_BAR_EDGE_BONUS = float(os.getenv("LATE_BAR_EDGE_BONUS", "0.04"))
LATE_BAR_WINDOW_SECS = int(os.getenv("LATE_BAR_WINDOW_SECS", "75"))
ULTRA_CHEAP_TAIL_PRICE = float(os.getenv("ULTRA_CHEAP_TAIL_PRICE", "0.10"))
ULTRA_CHEAP_TAIL_EDGE = float(os.getenv("ULTRA_CHEAP_TAIL_EDGE", "0.20"))
ULTRA_CHEAP_TAIL_MIN_SECONDS_LEFT = int(os.getenv("ULTRA_CHEAP_TAIL_MIN_SECONDS_LEFT", "90"))
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
AVERAGING_MIN_SECONDS_LEFT = int(os.getenv("AVERAGING_MIN_SECONDS_LEFT", "150"))
AVERAGING_MAX_BTC_MOVE = float(os.getenv("AVERAGING_MAX_BTC_MOVE", "0.003"))

# ── Smart entry filters ──────────────────────────────────────────────────────
MIN_BTC_DISTANCE = float(os.getenv("MIN_BTC_DISTANCE", "0.0004"))
MIN_BOOK_DIVERGENCE = float(os.getenv("MIN_BOOK_DIVERGENCE", "0.04"))
LATE_ENTRY_SECS = int(os.getenv("LATE_ENTRY_SECS", "90"))
LATE_ENTRY_EDGE_DISCOUNT = float(os.getenv("LATE_ENTRY_EDGE_DISCOUNT", "0.30"))

# ── Binance feed ─────────────────────────────────────────────────────────────
BINANCE_WS_URL = os.getenv("BINANCE_WS_URL", "wss://stream.binance.com:9443/ws/btcusdt@aggTrade")
BINANCE_STALE_SECS = float(os.getenv("BINANCE_STALE_SECS", "5.0"))

# ── Hold-to-expiry strategy ─────────────────────────────────────────────────
HOLD_TO_EXPIRY_DEFAULT = os.getenv("HOLD_TO_EXPIRY_DEFAULT", "true").lower() == "true"
# ── Position management ───────────────────────────────────────────────────────
EVAL_INTERVAL_MS = max(1, int(float(os.getenv("EVAL_INTERVAL_MS", "5000"))))
EVAL_INTERVAL_SECS = EVAL_INTERVAL_MS / 1000.0
TAKE_PROFIT = float(os.getenv("TAKE_PROFIT", "0.15"))
STOP_LOSS = float(os.getenv("STOP_LOSS", "0.08"))
SIGNAL_EXIT_EDGE = float(os.getenv("SIGNAL_EXIT_EDGE", "0.05"))
MIN_EXIT_BID = float(os.getenv("MIN_EXIT_BID", "0.03"))
ORDER_REPLACE_GAP = float(os.getenv("ORDER_REPLACE_GAP", "0.05"))
AGGRESSIVE_EXIT_SLIPPAGE = float(os.getenv("AGGRESSIVE_EXIT_SLIPPAGE", "0.02"))
TRAILING_ARM_GAIN = float(os.getenv("TRAILING_ARM_GAIN", "0.20"))
TRAILING_STOP_GAP = float(os.getenv("TRAILING_STOP_GAP", "0.03"))
THESIS_EDGE_FRACTION = float(os.getenv("THESIS_EDGE_FRACTION", "0.55"))
THESIS_MIN_EDGE = float(os.getenv("THESIS_MIN_EDGE", "0.02"))
THESIS_PROFIT_LOCK = float(os.getenv("THESIS_PROFIT_LOCK", "0.03"))
THESIS_MIN_BTC_DISTANCE = float(os.getenv("THESIS_MIN_BTC_DISTANCE", "0.002"))  # suppress thesis_decay when bar is already this far in our favor
ML_ENTRY_BASE_STOP_LOSS = float(os.getenv("ML_ENTRY_BASE_STOP_LOSS", "0.10"))
ML_ENTRY_LATE_STOP_LOSS = float(os.getenv("ML_ENTRY_LATE_STOP_LOSS", "0.08"))
ML_ENTRY_LATE_STOP_SECS = int(os.getenv("ML_ENTRY_LATE_STOP_SECS", "90"))
ML_ENTRY_TRAILING_ARM_GAIN = float(os.getenv("ML_ENTRY_TRAILING_ARM_GAIN", "0.08"))
ML_ENTRY_TRAILING_GAP = float(os.getenv("ML_ENTRY_TRAILING_GAP", "0.05"))
ML_ENTRY_THESIS_PROFIT_LOCK = float(os.getenv("ML_ENTRY_THESIS_PROFIT_LOCK", "0.04"))
ML_ENTRY_THESIS_FLOOR_MIN = float(os.getenv("ML_ENTRY_THESIS_FLOOR_MIN", "0.02"))
ML_ENTRY_THESIS_ENTRY_FRACTION = float(os.getenv("ML_ENTRY_THESIS_ENTRY_FRACTION", "0.35"))
ML_ENTRY_LATE_BAR_CUT_SECS = int(os.getenv("ML_ENTRY_LATE_BAR_CUT_SECS", "45"))
ML_ENTRY_LATE_BAR_POSITIVE_SECS = int(os.getenv("ML_ENTRY_LATE_BAR_POSITIVE_SECS", "25"))
ML_ENTRY_LATE_BAR_POSITIVE_FLOOR = float(os.getenv("ML_ENTRY_LATE_BAR_POSITIVE_FLOOR", "0.03"))
ML_ENTRY_DOMINANT_EDGE_FLOOR = float(os.getenv("ML_ENTRY_DOMINANT_EDGE_FLOOR", "0.08"))
ML_ENTRY_DOMINANT_ENTRY_FRACTION = float(os.getenv("ML_ENTRY_DOMINANT_ENTRY_FRACTION", "0.50"))
ML_ENTRY_FORCE_EXIT_SECS = int(os.getenv("ML_ENTRY_FORCE_EXIT_SECS", "10"))

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

MARKET_REFRESH_SECS = int(os.getenv("MARKET_REFRESH_SECS", "60"))
REDEMPTION_SWEEP_DELAY_SECS = int(os.getenv("REDEMPTION_SWEEP_DELAY_SECS", "30"))
WS_HEARTBEAT_SECS = int(os.getenv("WS_HEARTBEAT_SECS", "30"))
FEED_STALE_SECS = int(os.getenv("FEED_STALE_SECS", "20"))

# ── On-chain / Polygon ────────────────────────────────────────────────────────
CHAIN_ID     = 137
CTF_CONTRACT = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
USDC_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
POLYGON_RPC  = os.getenv("POLYGON_RPC_URL", "https://rpc.ankr.com/polygon")
