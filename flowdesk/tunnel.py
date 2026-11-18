"""Runs a cloudflared quick tunnel to the local API and, whenever the public URL changes,
sends the owner the desk link via Telegram. Run: python -m flowdesk.tunnel"""
from __future__ import annotations
import logging
import os
import re
import shutil
import subprocess
import sys
import time

from .auth import desk_key
from .config import get_config
from .journal import Journal
from .telegram import Telegram

log = logging.getLogger("flowdesk.tunnel")
URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


def desk_link(url: str) -> str:
    base = get_config().get("desk_url", "https://emiiss67.github.io/Flow-desk/")
    return f"{base}#api={url}&key={desk_key()}"


def on_url(url: str, j: Journal, tg: Telegram) -> bool:
    if j.get("tunnel_url") == url:
        return False
    j.set("tunnel_url", url)
    if tg.enabled:
        tg.send(f"🖥 <b>FlowDesk desk link</b> (new tunnel)\n{desk_link(url)}")
    return True


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cf = shutil.which("cloudflared") or "/usr/local/bin/cloudflared"
    port = get_config().get("api", {}).get("port", 8790)
    j, tg = Journal(), Telegram()
    while True:
        p = subprocess.Popen([cf, "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{port}"],
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for line in p.stdout:
            sys.stdout.write(line)
            m = URL_RE.search(line)
            if m and not m.group(0).startswith("https://api."):
                if on_url(m.group(0), j, tg):
                    log.info("tunnel url changed; desk link sent")
        p.wait()
        log.warning("cloudflared exited (%s); restarting in 10s", p.returncode)
        time.sleep(10)


if __name__ == "__main__":
    main()
