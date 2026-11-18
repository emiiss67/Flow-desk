#!/usr/bin/env python3
"""Find the owner's Telegram chat id after they pressed Start on the bot.

Reads getUpdates (token from FLOWDESK_TELEGRAM_TOKEN, never printed). Prints chat ids seen.
Optional: --write  stores FLOWDESK_TELEGRAM_CHAT_ID in .env
          --hello  sends a single 'FlowDesk connected' message to that chat
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import httpx  # noqa: E402
from flowdesk.config import secret, ROOT  # noqa: E402

tok = secret("FLOWDESK_TELEGRAM_TOKEN")
if not tok:
    sys.exit("FLOWDESK_TELEGRAM_TOKEN is not set")
r = None
for _ in range(4):
    try:
        r = httpx.get(f"https://api.telegram.org/bot{tok}/getUpdates", timeout=20).json()
        break
    except Exception as e:  # never print the URL (contains the token)
        err = type(e).__name__
        import time; time.sleep(3)
if r is None:
    sys.exit(f"getUpdates error: {err}")
if not r.get("ok"):
    sys.exit(f"getUpdates failed: {r.get('description')}")
chats = {}
for u in r.get("result", []):
    m = u.get("message") or u.get("my_chat_member") or {}
    c = m.get("chat") or {}
    if c.get("type") == "private":
        chats[str(c["id"])] = c.get("username") or c.get("first_name") or ""
if not chats:
    sys.exit("No private chats yet. Open the bot in Telegram and press Start, then run again.")
for cid, name in chats.items():
    print(f"chat_id={cid} user={name}")
cid = list(chats)[-1]
if "--write" in sys.argv:
    env = ROOT / ".env"
    lines = env.read_text().splitlines() if env.exists() else []
    lines = [l for l in lines if not l.startswith("FLOWDESK_TELEGRAM_CHAT_ID=")] + [f"FLOWDESK_TELEGRAM_CHAT_ID={cid}"]
    env.write_text("\n".join(lines) + "\n")
    env.chmod(0o600)
    print("written to .env")
if "--hello" in sys.argv:
    httpx.post(f"https://api.telegram.org/bot{tok}/sendMessage",
               json={"chat_id": cid, "text": "✅ FlowDesk connected (paper trading). Send /help for commands."}, timeout=20)
    print("hello sent")
