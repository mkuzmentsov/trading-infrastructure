"""Persistent JSON caches: seen-markets cooldown + cycle history."""
from __future__ import annotations

import json
import logging

from config import CYCLE_LOG_PATH, DATA_DIR, SEEN_MARKETS_PATH

logger = logging.getLogger(__name__)


def load_seen_markets() -> dict:
    """Return {condition_id: last_checked_epoch} from persistent cache."""
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        if not SEEN_MARKETS_PATH.exists():
            return {}
        raw = json.loads(SEEN_MARKETS_PATH.read_text())
        return {str(k): float(v) for k, v in raw.items() if isinstance(v, (int, float))}
    except Exception as e:
        logger.warning(f"  load_seen_markets failed: {e}")
        return {}


def save_seen_markets(seen: dict) -> None:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        SEEN_MARKETS_PATH.write_text(json.dumps(seen))
    except Exception as e:
        logger.warning(f"  save_seen_markets failed: {e}")


def log_cycle_jsonl(record: dict) -> None:
    """Append a cycle summary to cycles.jsonl for later analysis."""
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with CYCLE_LOG_PATH.open("a") as f:
            f.write(json.dumps(record, default=str) + "\n")
    except Exception as e:
        logger.warning(f"  log_cycle_jsonl failed: {e}")
