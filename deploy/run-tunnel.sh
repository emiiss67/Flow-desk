#!/usr/bin/env bash
# Start a cloudflared quick tunnel and announce the desk link when the URL changes.
set -euo pipefail
cd /home/grokbot/flowdesk
mkdir -p data
LOG=data/tunnel.log
: > "$LOG"
/usr/local/bin/cloudflared tunnel --no-autoupdate --url http://127.0.0.1:8787 >>"$LOG" 2>&1 &
CPID=$!
/home/grokbot/flowdesk/.venv/bin/python -m flowdesk.tunnel --log "$LOG" --state data/tunnel_url.txt &
WPID=$!
cleanup() {
  kill "$CPID" "$WPID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM
wait -n "$CPID" "$WPID"
cleanup
wait || true
exit 1
