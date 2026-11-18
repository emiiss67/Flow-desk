#!/usr/bin/env bash
# FlowDesk auto-deploy (systemd timer, every 2 min): pull main from GitHub into ~/flowdesk-repo, and when the
# server code changed: run the tests on the new tree, install it into ~/flowdesk, restart api + bot, health-check,
# and roll back to the previous code if anything fails. Desk-only changes (docs/, incl. the server's own
# endpoint.json commits) never restart anything. Never force-pushes; never touches venv/, data/ or .env.
set -uo pipefail
REPO=${FLOWDESK_REPO:-$HOME/flowdesk-repo}
DEST=${FLOWDESK_DEST:-$HOME/flowdesk}
KEY=${FLOWDESK_DEPLOY_KEY:-$HOME/.ssh/flowdesk_deploy}
REMOTE=git@github.com:emiiss67/Flow-desk.git
STATE=$DEST/data/autodeploy.json
LOG=$DEST/data/autodeploy.log
export GIT_SSH_COMMAND="ssh -i $KEY -o IdentitiesOnly=yes -o BatchMode=yes -o ConnectTimeout=20"
export GIT_AUTHOR_NAME=FlowDesk GIT_AUTHOR_EMAIL=flowdesk@users.noreply.github.com GIT_COMMITTER_NAME=FlowDesk GIT_COMMITTER_EMAIL=flowdesk@users.noreply.github.com
log() { echo "$(date -u +%FT%TZ) $*" | tee -a "$LOG"; }
state() { printf '{"rev":"%s","status":"%s","ts":%s,"note":"%s"}\n' "$1" "$2" "$(date +%s)" "$3" > "$STATE"; }

exec 9>"$REPO/.git/flowdesk.lock"; flock -w 120 9 || { log "lock busy, skip"; exit 0; }   # shared with publish.py
cd "$REPO" || exit 1
git fetch -q "$REMOTE" main || { log "fetch failed"; exit 0; }
if ! git merge -q --ff-only FETCH_HEAD 2>/dev/null; then
  # local endpoint.json commit not on GitHub yet: put it on top of the new main (never force)
  git rebase -q FETCH_HEAD || { git rebase --abort; log "rebase conflict - manual check needed"; exit 0; }
  git push -q "$REMOTE" HEAD:main || log "push of local endpoint commit failed (will retry)"
fi
NEW=$(git rev-parse HEAD)
OLD=$(cat "$DEST/.deployed_rev" 2>/dev/null || echo "")
[ "$NEW" = "$OLD" ] && exit 0
FAILED=$(cat "$DEST/data/autodeploy.failed" 2>/dev/null || echo "")
[ "$NEW" = "$FAILED" ] && exit 0                                  # this revision already failed its tests
if [ -n "$OLD" ] && git cat-file -e "$OLD" 2>/dev/null && [ -z "$(git diff --name-only "$OLD" "$NEW" -- . ':!docs')" ]; then
  echo "$NEW" > "$DEST/.deployed_rev"; state "$NEW" "desk-only" "no server change"; exit 0
fi
log "deploying ${OLD:0:7} -> ${NEW:0:7}"
STAGE=$(mktemp -d /tmp/flowdesk-stage.XXXX); trap 'rm -rf "$STAGE"' EXIT
git archive "$NEW" | tar -x -C "$STAGE"
if ! git diff --quiet "${OLD:-$NEW}" "$NEW" -- requirements.txt 2>/dev/null || [ -z "$OLD" ]; then
  "$DEST/venv/bin/pip" install -q -r "$STAGE/requirements.txt" >>"$LOG" 2>&1 || log "pip install warning"
fi
if ! (cd "$STAGE" && FLOWDESK_PUBLISH=0 timeout 600 "$DEST/venv/bin/python" -m pytest -q -x -k "not live" -p no:cacheprovider >>"$LOG" 2>&1); then
  echo "$NEW" > "$DEST/data/autodeploy.failed"; state "$NEW" "tests-failed" "kept ${OLD:0:7} running"; log "tests FAILED for ${NEW:0:7}; nothing changed"; exit 1
fi
BK=$DEST/data/deploy-backup; rm -rf "$BK"; mkdir -p "$BK"
tar -C "$DEST" --exclude=./venv --exclude=./data --exclude=./.env -cf "$BK/code.tar" .
tar -x -C "$DEST" -f <(git archive "$NEW")
sudo -n systemctl restart flowdesk-api flowdesk-bot
ok=0; for i in $(seq 1 12); do sleep 5
  if systemctl is-active -q flowdesk-api && systemctl is-active -q flowdesk-bot && curl -fsS -m 5 "${FLOWDESK_HEALTH:-http://127.0.0.1:8795/health}" >/dev/null; then ok=1; break; fi; done
if [ $ok = 1 ]; then
  sleep 20                                                     # still alive after the first scan?
  systemctl is-active -q flowdesk-api && systemctl is-active -q flowdesk-bot || ok=0
fi
if [ $ok = 1 ]; then
  echo "$NEW" > "$DEST/.deployed_rev"; state "$NEW" "deployed" "from ${OLD:0:7}"; log "deployed ${NEW:0:7}"; exit 0
fi
log "health check FAILED for ${NEW:0:7} - rolling back to ${OLD:0:7}"
tar -x -C "$DEST" -f "$BK/code.tar"
sudo -n systemctl restart flowdesk-api flowdesk-bot
echo "$NEW" > "$DEST/data/autodeploy.failed"; state "$NEW" "rolled-back" "restored ${OLD:0:7}"; exit 1
