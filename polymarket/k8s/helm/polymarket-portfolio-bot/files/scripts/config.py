"""Shared configuration and constants for the portfolio bot."""
from __future__ import annotations

import logging
import os
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# ── Credentials ───────────────────────────────────────────────────────────────

ANTHROPIC_API_KEY          = os.environ.get("ANTHROPIC_API_KEY", "")
POLYMARKET_PK              = os.environ.get("POLYMARKET_PK", "")
POLYMARKET_ADDRESS         = os.environ.get("POLYMARKET_ADDRESS", "")
POLYMARKET_SIGNATURE_TYPE  = int(os.environ.get("POLYMARKET_SIGNATURE_TYPE", "0"))
POLYMARKET_FUNDER          = os.environ.get("POLYMARKET_FUNDER", "")

# ── Trading knobs ─────────────────────────────────────────────────────────────

DRY_RUN                    = os.environ.get("DRY_RUN", "true").lower() == "true"
LOOP_INTERVAL_SECS         = int(os.environ.get("LOOP_INTERVAL_SECS", "3600"))
MIN_MARKET_VOLUME          = float(os.environ.get("MIN_MARKET_VOLUME", "10000"))
MAX_CANDIDATES             = int(os.environ.get("MAX_CANDIDATES", "50"))
MAX_DEPLOY_FRACTION        = float(os.environ.get("MAX_DEPLOY_FRACTION", "0.20"))
BET_SIZE_MIN               = float(os.environ.get("BET_SIZE_MIN", "1.0"))
MAX_ENTRY_PRICE            = float(os.environ.get("MAX_ENTRY_PRICE", "0.60"))
MIN_DAYS_TO_CLOSE          = int(os.environ.get("MIN_DAYS_TO_CLOSE", "30"))
MAX_OPEN_POSITIONS         = int(os.environ.get("MAX_OPEN_POSITIONS", "30"))
MARKET_COOLDOWN_SECS       = int(os.environ.get("MARKET_COOLDOWN_SECS", "21600"))  # 6h

# ── Claude ────────────────────────────────────────────────────────────────────

CLAUDE_ENABLED             = os.environ.get("CLAUDE_ENABLED", "true").lower() == "true"
CLAUDE_MODEL               = os.environ.get("CLAUDE_MODEL", "claude-opus-4-6")

# ── Telegram ──────────────────────────────────────────────────────────────────

TELEGRAM_TOKEN             = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID           = os.environ.get("TELEGRAM_CHAT_ID", "")

# ── Persistence ───────────────────────────────────────────────────────────────

DATA_DIR                   = Path(os.environ.get("DATA_DIR", "/app/data"))
CYCLE_LOG_PATH             = DATA_DIR / "cycles.jsonl"
SEEN_MARKETS_PATH          = DATA_DIR / "seen_markets.json"

# ── On-chain / APIs ───────────────────────────────────────────────────────────

GAMMA_API                  = "https://gamma-api.polymarket.com"
DATA_API                   = "https://data-api.polymarket.com"
CLOB_HOST                  = "https://clob.polymarket.com"
POLYGON_RPC                = os.environ.get("POLYGON_RPC_URL", "https://rpc.ankr.com/polygon")
CHAIN_ID                   = 137
CTF_CONTRACT               = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
USDC_ADDRESS               = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"

# For data-api: Gnosis Safe wallets are indexed by Safe (funder) address,
# EOA wallets by the main address.
PORTFOLIO_WALLET           = POLYMARKET_FUNDER if POLYMARKET_FUNDER else POLYMARKET_ADDRESS
