"""
Shared configuration: env vars, constants, and logging setup.
All other modules import from here.
"""
from __future__ import annotations

import logging
import os
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("pm_btc")

logging.getLogger("ccxt").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)

# ── Config from env ───────────────────────────────────────────────────────────
MODEL_PATH         = os.getenv("MODEL_PATH",         "/app/data/model.txt")
DATA_DIR           = Path(os.getenv("DATA_DIR",      "/app/data"))
DRY_RUN            = os.getenv("DRY_RUN",            "true").lower() == "true"
MIN_EDGE           = float(os.getenv("MIN_EDGE",     "0.05"))
BET_SIZE_MIN       = float(os.getenv("BET_SIZE_MIN", "0.50"))
BET_SIZE_MAX       = float(os.getenv("BET_SIZE_MAX", "5.00"))
LOOP_INTERVAL      = int(os.getenv("LOOP_INTERVAL_SECS", "300"))

POLYMARKET_PK               = os.getenv("POLYMARKET_PK",               "")
POLYMARKET_ADDRESS          = os.getenv("POLYMARKET_ADDRESS",           "")
POLYMARKET_API_KEY          = os.getenv("POLYMARKET_API_KEY",           "")
POLYMARKET_API_SECRET       = os.getenv("POLYMARKET_API_SECRET",        "")
POLYMARKET_API_PASSPHRASE   = os.getenv("POLYMARKET_API_PASSPHRASE",    "")
SIGNATURE_TYPE              = int(os.getenv("POLYMARKET_SIGNATURE_TYPE", "0"))
POLYMARKET_FUNDER           = os.getenv("POLYMARKET_FUNDER",            "")

TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN",   "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

GAMMA_API  = "https://gamma-api.polymarket.com"
CLOB_HOST  = "https://clob.polymarket.com"
DATA_API   = "https://data-api.polymarket.com"
CHAIN_ID   = 137   # Polygon

CTF_CONTRACT = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"  # ConditionalTokens on Polygon
USDC_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"  # USDC.e on Polygon
POLYGON_RPC  = os.getenv("POLYGON_RPC_URL", "https://rpc.ankr.com/polygon")

CANDLES_NEEDED = 350  # warm-up buffer for longest indicator lookbacks
