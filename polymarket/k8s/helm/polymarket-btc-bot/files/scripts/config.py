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

BET_SIZE_MIN = float(os.getenv("BET_SIZE_MIN", "0.50"))
BET_SIZE_MAX = float(os.getenv("BET_SIZE_MAX", "5.00"))
MAX_BUDGET_FRACTION = float(os.getenv("MAX_BUDGET_FRACTION", "0.10"))
MIN_POSITION_SHARES = int(os.getenv("MIN_POSITION_SHARES", "6"))
SIGNAL_MODEL = os.getenv("SIGNAL_MODEL", "math").strip().lower()
ML_BLEND_WEIGHT = float(os.getenv("ML_BLEND_WEIGHT", "0.50"))
STRATEGY_NAME = os.getenv("STRATEGY_NAME", "latency_arb_hold").strip().lower()

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
ENTRY_ORDER_TIMEOUT_SECS = int(os.getenv("ENTRY_ORDER_TIMEOUT_SECS", "18"))
ENTRY_MAKER_OFFSET = float(os.getenv("ENTRY_MAKER_OFFSET", "0.0"))  # 0 = taker (current); >0 = post below ask
ENTRY_REPLACE_MIN_AGE_SECS = int(os.getenv("ENTRY_REPLACE_MIN_AGE_SECS", "6"))
ENTRY_REPLACE_GAP = float(os.getenv("ENTRY_REPLACE_GAP", "0.02"))
ENTRY_BOOK_MAX_TAKE_FRACTION = float(os.getenv("ENTRY_BOOK_MAX_TAKE_FRACTION", "0.35"))
MAX_ABS_DRIFT = float(os.getenv("MAX_ABS_DRIFT", "0.004"))
ENTRY_CONFIRMATION_TICKS = int(os.getenv("ENTRY_CONFIRMATION_TICKS", "1"))
CONTRARIAN_TAIL_MAX_PRICE = float(os.getenv("CONTRARIAN_TAIL_MAX_PRICE", "0.25"))
CONTRARIAN_MOVE_FILTER = float(os.getenv("CONTRARIAN_MOVE_FILTER", "0.0015"))
CHEAP_TAIL_EDGE_BONUS = float(os.getenv("CHEAP_TAIL_EDGE_BONUS", "0.05"))
LATE_BAR_EDGE_BONUS = float(os.getenv("LATE_BAR_EDGE_BONUS", "0.04"))
LATE_BAR_WINDOW_SECS = int(os.getenv("LATE_BAR_WINDOW_SECS", "75"))
ULTRA_CHEAP_TAIL_PRICE = float(os.getenv("ULTRA_CHEAP_TAIL_PRICE", "0.10"))
ULTRA_CHEAP_TAIL_EDGE = float(os.getenv("ULTRA_CHEAP_TAIL_EDGE", "0.20"))
ULTRA_CHEAP_TAIL_MIN_SECONDS_LEFT = int(os.getenv("ULTRA_CHEAP_TAIL_MIN_SECONDS_LEFT", "90"))
REENTRY_EDGE_PENALTY = float(os.getenv("REENTRY_EDGE_PENALTY", "0.05"))
STOP_LOSS_MARKET_LIMIT = int(os.getenv("STOP_LOSS_MARKET_LIMIT", "1"))
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
WS_HEARTBEAT_SECS = int(os.getenv("WS_HEARTBEAT_SECS", "30"))
FEED_STALE_SECS = int(os.getenv("FEED_STALE_SECS", "20"))

# ── On-chain / Polygon ────────────────────────────────────────────────────────
CHAIN_ID     = 137
CTF_CONTRACT = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
USDC_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
POLYGON_RPC  = os.getenv("POLYGON_RPC_URL", "https://rpc.ankr.com/polygon")
