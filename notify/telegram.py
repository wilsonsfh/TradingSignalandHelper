"""Best-effort Telegram notifications.

No-op when unconfigured. Network I/O is dispatched on a daemon thread so a slow or
failing Telegram call can never block the trading lock or break execution.
"""
from __future__ import annotations

import json
import threading
import urllib.request


class TelegramNotifier:
    def __init__(self, bot_token: str = "", chat_id: str = "", timeout: float = 5.0) -> None:
        self.bot_token = (bot_token or "").strip()
        self.chat_id = (chat_id or "").strip()
        self.timeout = timeout

    @property
    def enabled(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    def _send_sync(self, text: str) -> bool:
        """Perform the HTTP POST. Returns True on 2xx; swallows all errors."""
        if not self.enabled:
            return False
        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            payload = json.dumps(
                {"chat_id": self.chat_id, "text": text, "disable_web_page_preview": True}
            ).encode("utf-8")
            request = urllib.request.Request(
                url, data=payload, headers={"Content-Type": "application/json"}, method="POST"
            )
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                status = getattr(response, "status", 200)
                return 200 <= int(status) < 300
        except Exception:
            return False

    def notify(self, text: str) -> None:
        """Fire-and-forget: dispatch the send on a daemon thread and return immediately."""
        if not self.enabled:
            return
        threading.Thread(
            target=self._send_sync, args=(text,), name="telegram-send", daemon=True
        ).start()
