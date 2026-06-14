"""Optional Telegram notifications for the pattern bot.

Disabled automatically if no bot_token/chat_id is configured, so it's a safe no-op
in dry-run or when unconfigured. Failures never crash the loop — they just log a
warning. Get a token from @BotFather; get your chat_id by messaging @userinfobot.
"""
from __future__ import annotations

import logging

log = logging.getLogger("pattern-bot.notify")


class Notifier:
    def __init__(self, token: str = "", chat_id: str = "", enabled: bool = True):
        self.token = (token or "").strip()
        self.chat_id = str(chat_id or "").strip()
        self.enabled = bool(enabled and self.token and self.chat_id)

    def send(self, text: str) -> None:
        if not self.enabled:
            return
        import requests
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{self.token}/sendMessage",
                json={"chat_id": self.chat_id, "text": text,
                      "disable_web_page_preview": True},
                timeout=10,
            )
            if r.status_code != 200:
                log.warning("telegram send non-200: %s %s", r.status_code, r.text[:200])
        except Exception as e:  # noqa: BLE001
            log.warning("telegram send failed: %s", e)
