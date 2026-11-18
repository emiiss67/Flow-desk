#!/usr/bin/env bash
# Install FlowDesk on a Debian VM under user grokbot at /home/grokbot/flowdesk.
# Run as root from a checkout of this repo: sudo ./install.sh
set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run as root: sudo ./install.sh" >&2
  exit 1
fi

if ! id grokbot >/dev/null 2>&1; then
  useradd --create-home --shell /bin/bash grokbot
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y python3 python3-venv python3-pip ca-certificates curl

SRC="$(cd "$(dirname "$0")" && pwd)"
DEST=/home/grokbot/flowdesk
mkdir -p "$DEST"
rsync -a --delete \
  --exclude .git \
  --exclude .venv \
  --exclude data \
  --exclude .env \
  --exclude __pycache__ \
  --exclude .pytest_cache \
  "$SRC"/ "$DEST"/

python3 -m venv "$DEST/.venv"
"$DEST/.venv/bin/pip" install --upgrade pip
"$DEST/.venv/bin/pip" install -r "$DEST/requirements.txt"

if [[ ! -f "$DEST/.env" ]]; then
  cp "$DEST/.env.example" "$DEST/.env"
fi
chmod 600 "$DEST/.env"
chown -R grokbot:grokbot "$DEST"
chmod 755 "$DEST/deploy/run-tunnel.sh"

install -m 0644 "$DEST/deploy/flowdesk-api.service" /etc/systemd/system/flowdesk-api.service
install -m 0644 "$DEST/deploy/flowdesk-bot.service" /etc/systemd/system/flowdesk-bot.service
install -m 0644 "$DEST/deploy/flowdesk-tunnel.service" /etc/systemd/system/flowdesk-tunnel.service

if [[ ! -x /usr/local/bin/cloudflared ]]; then
  curl -fsSL -o /usr/local/bin/cloudflared \
    https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64
  chmod 0755 /usr/local/bin/cloudflared
fi

systemctl daemon-reload
systemctl enable flowdesk-api flowdesk-bot flowdesk-tunnel
systemctl restart flowdesk-api
systemctl restart flowdesk-bot
systemctl restart flowdesk-tunnel || true

echo
echo "FlowDesk is installed at $DEST"
echo "Edit $DEST/.env and add FLOWDESK_TELEGRAM_TOKEN, then: systemctl restart flowdesk-bot flowdesk-tunnel"
echo "Discover your chat id with: sudo -u grokbot env FLOWDESK_TELEGRAM_TOKEN=... $DEST/.venv/bin/python -m flowdesk.discover_chat --save"
echo "The API listens on 127.0.0.1:8787. The desk key is created on first API start:"
echo "  sudo -u grokbot cat $DEST/data/desk.key"
echo "GitHub Pages desk: https://emiiss67.github.io/Flow-desk/"
