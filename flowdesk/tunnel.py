"""Watch a cloudflared quick-tunnel log and tell the owner when the URL changes."""

from __future__ import annotations

import argparse
import logging
import re
import time
from pathlib import Path

from flowdesk.config import load_settings
from flowdesk.server import ensure_desk_key

log = logging.getLogger("flowdesk.tunnel")

TUNNEL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


def extract_tunnel_url(text: str) -> str | None:
    found = TUNNEL_RE.findall(text or "")
    if not found:
        return None
    return found[-1]


def desk_link(tunnel_url: str, key: str, pages_base: str = "https://emiiss67.github.io/Flow-desk/") -> str:
    base = pages_base if pages_base.endswith("/") else pages_base + "/"
    # Hash form requested by the desk: #api=<tunnel>&key=<key>
    return f"{base}#api={tunnel_url}&key={key}"


def announce(token: str, chat_id: str, tunnel_url: str, key: str, pages_base: str) -> str:
    link = desk_link(tunnel_url, key, pages_base)
    text = (
        "FlowDesk desk link (private)\n\n"
        f"{link}\n\n"
        "Paper only. This quick-tunnel URL changes when cloudflared restarts."
    )
    if token and chat_id:
        from flowdesk.bot import send_message

        send_message(token, chat_id, text)
    return link


def watch(log_path: Path, state_path: Path, token: str, chat_id: str, key: str, pages_base: str, interval: float = 5.0) -> None:
    last = state_path.read_text(encoding="utf-8").strip() if state_path.exists() else ""
    while True:
        try:
            text = log_path.read_text(encoding="utf-8", errors="ignore") if log_path.exists() else ""
        except OSError:
            text = ""
        url = extract_tunnel_url(text[-30000:])
        if url and url != last:
            try:
                link = announce(token, chat_id, url, key, pages_base)
                state_path.write_text(url + "\n", encoding="utf-8")
                last = url
                log.info("tunnel url updated: %s", link.split("#")[0])
            except Exception:
                log.exception("could not announce tunnel url")
        time.sleep(interval)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(description="Announce FlowDesk cloudflared URLs on Telegram")
    parser.add_argument("--log", default="data/tunnel.log")
    parser.add_argument("--state", default="data/tunnel_url.txt")
    args = parser.parse_args()
    settings = load_settings()
    key = ensure_desk_key(settings.desk_key_file)
    chat = settings.telegram_chat_id
    if not chat:
        chat_file = Path(settings.database).parent / "telegram_chat_id"
        if chat_file.exists():
            chat = chat_file.read_text(encoding="utf-8").strip()
    watch(
        Path(args.log),
        Path(args.state),
        settings.telegram_token,
        chat,
        key,
        settings.pages_base,
    )


if __name__ == "__main__":
    main()
