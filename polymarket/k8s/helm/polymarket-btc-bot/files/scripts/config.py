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

# ── Signal parameters ─────────────────────────────────────────────────────────
MIN_EDGE    = float(os.getenv("MIN_EDGE",    "0.03"))
COST_BUFFER = float(os.getenv("COST_BUFFER", "0.02"))
KELLY_SCALE = float(os.getenv("KELLY_SCALE", "0.5"))

# Drift estimation coefficients — hand-tuned; keep configurable.
DRIFT_A1 = float(os.getenv("DRIFT_A1", "1.8"))
DRIFT_A2 = float(os.getenv("DRIFT_A2", "1.2"))
DRIFT_A3 = float(os.getenv("DRIFT_A3", "0.003"))
DRIFT_A4 = float(os.getenv("DRIFT_A4", "0.8"))

# Extra signal guards to reduce overtrading / overconfidence.
ENTRY_MIN_SECONDS_LEFT = int(os.getenv("ENTRY_MIN_SECONDS_LEFT", "45"))
MAX_ENTRY_SPREAD       = float(os.getenv("MAX_ENTRY_SPREAD", "0.03"))
SOURCE_MISMATCH_BUFFER = float(os.getenv("SOURCE_MISMATCH_BUFFER", "0.01"))
MODEL_PROB_SHRINK      = float(os.getenv("MODEL_PROB_SHRINK", "0.65"))
MODEL_PROB_FLOOR       = float(os.getenv("MODEL_PROB_FLOOR", "0.12"))
MODEL_PROB_CEIL        = float(os.getenv("MODEL_PROB_CEIL", "0.88"))
MAX_ABS_DRIFT          = float(os.getenv("MAX_ABS_DRIFT", "0.004"))
MIN_POSITION_SHARES    = int(os.getenv("MIN_POSITION_SHARES", "6"))
ENTRY_CONFIRMATION_TICKS = int(os.getenv("ENTRY_CONFIRMATION_TICKS", "2"))

# ── Position management ───────────────────────────────────────────────────────
EVAL_INTERVAL_SECS = int(os.getenv("EVAL_INTERVAL_SECS", "5"))
TAKE_PROFIT        = float(os.getenv("TAKE_PROFIT",      "0.15"))
STOP_LOSS          = float(os.getenv("STOP_LOSS",         "0.08"))
SIGNAL_EXIT_EDGE   = float(os.getenv("SIGNAL_EXIT_EDGE",  "0.05"))
MIN_EXIT_BID       = float(os.getenv("MIN_EXIT_BID",      "0.03"))
ORDER_REPLACE_GAP  = float(os.getenv("ORDER_REPLACE_GAP", "0.02"))

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
BINANCE_WS    = "wss://stream.binance.com:9443/stream?streams=btcusdt@depth20@100ms"

MARKET_REFRESH_SECS = int(os.getenv("MARKET_REFRESH_SECS", "60"))
WS_HEARTBEAT_SECS = int(os.getenv("WS_HEARTBEAT_SECS", "30"))
FEED_STALE_SECS = int(os.getenv("FEED_STALE_SECS", "20"))

# ── On-chain / Polygon ────────────────────────────────────────────────────────
CHAIN_ID     = 137
CTF_CONTRACT = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
USDC_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
POLYGON_RPC  = os.getenv("POLYGON_RPC_URL", "https://rpc.ankr.com/polygon")
