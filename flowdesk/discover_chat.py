"""Print Telegram chat ids from pending updates so the owner can lock the bot.

Usage:
    FLOWDESK_TELEGRAM_TOKEN=... python -m flowdesk.discover_chat
    FLOWDESK_TELEGRAM_TOKEN=... python -m flowdesk.discover_chat --save
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import httpx


def main() -> None:
    parser = argparse.ArgumentParser(description="Discover a Telegram chat id for FlowDesk")
    parser.add_argument("--save", action="store_true", help="Write the first chat id to data/telegram_chat_id")
    parser.add_argument("--path", default="data/telegram_chat_id")
    args = parser.parse_args()
    token = os.environ.get("FLOWDESK_TELEGRAM_TOKEN", "").strip()
    if not token:
        print("Set FLOWDESK_TELEGRAM_TOKEN first.", file=sys.stderr)
        sys.exit(1)
    response = httpx.get(
        f"https://api.telegram.org/bot{token}/getUpdates",
        params={"timeout": 1, "allowed_updates": '["message"]'},
        timeout=15,
    )
    response.raise_for_status()
    body = response.json()
    if not body.get("ok"):
        print("Telegram did not accept the token.", file=sys.stderr)
        sys.exit(1)
    seen: list[str] = []
    for update in body.get("result") or []:
        message = update.get("message") or {}
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        if chat_id is None:
            continue
        label = chat.get("username") or chat.get("first_name") or ""
        line = f"{chat_id}\t{label}\t{(message.get('text') or '')[:80]}"
        if line not in seen:
            seen.append(line)
            print(line)
    if not seen:
        print("No messages yet. Open the bot in Telegram and send /start, then run this again.")
        sys.exit(2)
    if args.save:
        first = seen[0].split("\t", 1)[0]
        path = Path(args.path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(first + "\n", encoding="utf-8")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        print(f"Saved {first} to {path}")


if __name__ == "__main__":
    main()
