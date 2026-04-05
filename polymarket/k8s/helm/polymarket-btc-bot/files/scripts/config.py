"""
Shared configuration — env vars, constants, logging.
"""
from __future__ import annotations

import logging
import os
import warnings

warnings.filterwarnings("ignore")

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("pm_btc")
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
MIN_EDGE    = float(os.getenv("MIN_EDGE",    "0.03"))   # net edge required to enter
COST_BUFFER = float(os.getenv("COST_BUFFER", "0.02"))   # fees + slippage allowance
KELLY_SCALE = float(os.getenv("KELLY_SCALE", "0.5"))    # fraction of full Kelly

# Drift estimation coefficients — hand-tuned; backtest to refine
DRIFT_A1 = float(os.getenv("DRIFT_A1", "1.8"))    # 30s momentum weight
DRIFT_A2 = float(os.getenv("DRIFT_A2", "1.2"))    # 60s momentum weight
DRIFT_A3 = float(os.getenv("DRIFT_A3", "0.003"))  # book imbalance weight
DRIFT_A4 = float(os.getenv("DRIFT_A4", "0.8"))    # distance-from-open weight

# ── Position management ───────────────────────────────────────────────────────
EVAL_INTERVAL_SECS = int(os.getenv("EVAL_INTERVAL_SECS", "5"))     # signal re-eval frequency
TAKE_PROFIT        = float(os.getenv("TAKE_PROFIT",      "0.15"))  # exit if bid > entry + this
STOP_LOSS          = float(os.getenv("STOP_LOSS",         "0.08"))  # exit if bid < entry - this
SIGNAL_EXIT_EDGE   = float(os.getenv("SIGNAL_EXIT_EDGE",  "0.05"))  # exit if opposite edge ≥ this
MIN_EXIT_BID       = float(os.getenv("MIN_EXIT_BID",      "0.03"))  # don't sell below this
ORDER_REPLACE_GAP  = float(os.getenv("ORDER_REPLACE_GAP", "0.02"))  # cancel+replace if bid drifts by this

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

MARKET_REFRESH_SECS = int(os.getenv("MARKET_REFRESH_SECS", "60"))

# ── On-chain / Polygon ────────────────────────────────────────────────────────
CHAIN_ID     = 137
CTF_CONTRACT = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
USDC_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
POLYGON_RPC  = os.getenv("POLYGON_RPC_URL", "https://rpc.ankr.com/polygon")
