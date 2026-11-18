#!/usr/bin/env bash
# FlowDesk installer for a Debian/Ubuntu VM. Run as user grokbot from the repo checkout:
#   bash deploy/install.sh
# Installs to /home/grokbot/flowdesk with a venv and systemd units. Does not start anything unless --start.
set -euo pipefail
DEST=/home/grokbot/flowdesk
SRC="$(cd "$(dirname "$0")/.." && pwd)"
echo "==> FlowDesk install: $SRC -> $DEST"
sudo apt-get update -qq
sudo apt-get install -y -qq python3 python3-venv python3-pip rsync curl >/dev/null
mkdir -p "$DEST"
rsync -a --delete --exclude venv --exclude data --exclude .env --exclude .git --exclude docs "$SRC/" "$DEST/"
cd "$DEST"
[ -d venv ] || python3 -m venv venv
venv/bin/pip install -q --upgrade pip
venv/bin/pip install -q -r requirements.txt
mkdir -p data && chmod 700 data
if [ ! -f .env ]; then cp .env.example .env; chmod 600 .env; echo "==> Created .env - fill in FLOWDESK_TELEGRAM_TOKEN / FLOWDESK_TELEGRAM_CHAT_ID"; fi
if ! command -v cloudflared >/dev/null; then
  echo "==> Installing cloudflared"
  ARCH=$(dpkg --print-architecture)
  curl -fsSL -o /tmp/cloudflared.deb "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${ARCH}.deb"
  sudo dpkg -i /tmp/cloudflared.deb >/dev/null
fi
sudo cp deploy/flowdesk-bot.service deploy/flowdesk-api.service deploy/flowdesk-tunnel.service /etc/systemd/system/
sudo systemctl daemon-reload
venv/bin/python -m pytest -q tests -k "not live" || { echo "tests failed"; exit 1; }
if [ "${1:-}" = "--start" ]; then
  sudo systemctl enable --now flowdesk-api flowdesk-bot flowdesk-tunnel
  sleep 3; systemctl --no-pager status flowdesk-api flowdesk-bot flowdesk-tunnel | grep -E "Active|●"
else
  echo "==> Installed. Start with: sudo systemctl enable --now flowdesk-api flowdesk-bot flowdesk-tunnel"
fi
