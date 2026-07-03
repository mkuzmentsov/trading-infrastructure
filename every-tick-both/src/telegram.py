"""
Telegram notification helper.
"""
from __future__ import annotations

import asyncio

import requests

from config import TELEGRAM_CHAT_ID, TELEGRAM_TOKEN


def tg(text: str) -> None:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"},
            timeout=5,
        )
    except Exception:
        pass


async def tg_async(text: str) -> None:
    """Non-blocking Telegram send for use from the asyncio event loop."""
    await asyncio.to_thread(tg, text)
