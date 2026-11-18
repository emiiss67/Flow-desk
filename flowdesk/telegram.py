"""Minimal Telegram Bot API client (long polling). The token is read from env and never logged."""
from __future__ import annotations
import html
import logging
import time

import httpx

from .config import secret

log = logging.getLogger("flowdesk.telegram")


class Telegram:
    def __init__(self, token: str | None = None, chat_id: str | None = None):
        self.token = token or secret("FLOWDESK_TELEGRAM_TOKEN")
        self.chat_id = str(chat_id or secret("FLOWDESK_TELEGRAM_CHAT_ID") or "")
        self.offset = 0

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.chat_id)

    def _url(self, method: str) -> str:
        return f"https://api.telegram.org/bot{self.token}/{method}"

    def call(self, method: str, _tries: int = 3, **params):
        for k in range(_tries):
            try:
                r = httpx.post(self._url(method), json=params, timeout=20)
                data = r.json()
                if not data.get("ok"):
                    log.warning("telegram %s failed: %s", method, data.get("description"))
                return data
            except Exception as e:  # never include the URL (it contains the token)
                log.warning("telegram %s error: %s (try %d/%d)", method, type(e).__name__, k + 1, _tries)
                time.sleep(1.5 * (k + 1))
        return {"ok": False}

    def send(self, text: str, chat_id: str | None = None, buttons: list | None = None) -> bool:
        if not self.token:
            return False
        params = {"chat_id": chat_id or self.chat_id, "text": text[:4000], "parse_mode": "HTML",
                  "disable_web_page_preview": True}
        if buttons:
            params["reply_markup"] = {"inline_keyboard": buttons}
        return bool(self.call("sendMessage", **params).get("ok"))

    def updates(self, timeout: int = 25) -> list[dict]:
        try:
            r = httpx.post(self._url("getUpdates"), json={"offset": self.offset, "timeout": timeout,
                                                         "allowed_updates": ["message", "callback_query"]},
                           timeout=timeout + 10)
            data = r.json()
        except Exception as e:
            log.warning("getUpdates error: %s", type(e).__name__)
            time.sleep(3)
            return []
        res = data.get("result", []) if data.get("ok") else []
        if res:
            self.offset = res[-1]["update_id"] + 1
        return res


def esc(s) -> str:
    return html.escape(str(s))
