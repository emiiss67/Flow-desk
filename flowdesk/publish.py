"""Publish the current tunnel address (URL only - never the desk key) to docs/endpoint.json in the desk repo, so a
saved desk follows the API when the quick-tunnel URL changes. Pushes with the repo's deploy key; never force-pushes."""
from __future__ import annotations
import json
import logging
import os
import subprocess
import threading
import time
from pathlib import Path

from .config import get_config

log = logging.getLogger("flowdesk.publish")
_lock = threading.Lock()


def _cfg() -> dict:
    c = get_config().get("endpoint_publish", {}) or {}
    return {"enabled": bool(c.get("enabled", False)) and os.environ.get("FLOWDESK_PUBLISH", "1") != "0", "repo_dir": os.path.expanduser(c.get("repo_dir", "~/flowdesk-repo")),
            "ssh_key": os.path.expanduser(c.get("ssh_key", "~/.ssh/flowdesk_deploy")),
            "remote": c.get("remote", "git@github.com:emiiss67/Flow-desk.git"), "branch": c.get("branch", "main"),
            "path": c.get("path", "docs/endpoint.json")}


def _git(c: dict, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    env = dict(os.environ, GIT_SSH_COMMAND=f"ssh -i {c['ssh_key']} -o IdentitiesOnly=yes -o BatchMode=yes -o ConnectTimeout=20",
               GIT_AUTHOR_NAME="FlowDesk", GIT_AUTHOR_EMAIL="flowdesk@users.noreply.github.com",
               GIT_COMMITTER_NAME="FlowDesk", GIT_COMMITTER_EMAIL="flowdesk@users.noreply.github.com")
    return subprocess.run(["git", "-C", c["repo_dir"], *args], env=env, capture_output=True, text=True, timeout=120, check=check)


def endpoint_doc(url: str) -> str:
    return json.dumps({"api": url, "updated": int(time.time()), "note": "FlowDesk API address only; the desk key is never published."}, indent=1) + "\n"


def publish(url: str, c: dict | None = None) -> str:
    """Returns 'pushed', 'unchanged' or raises. Safe to call repeatedly."""
    c = c or _cfg()
    with _lock:
        f = Path(c["repo_dir"]) / c["path"]
        _git(c, "fetch", "-q", c["remote"], c["branch"])
        ff = _git(c, "merge", "-q", "--ff-only", "FETCH_HEAD", check=False)
        if ff.returncode != 0:
            log.warning("endpoint repo not fast-forwardable (%s); publishing on top of local HEAD", ff.stderr.strip()[:200])
        try:
            if json.loads(f.read_text()).get("api") == url:
                ahead = _git(c, "rev-list", "--count", "FETCH_HEAD..HEAD", check=False).stdout.strip()
                if ahead in ("0", ""):
                    return "unchanged"
        except (OSError, ValueError):
            pass
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(endpoint_doc(url))
        _git(c, "add", c["path"])
        if _git(c, "diff", "--cached", "--quiet", check=False).returncode != 0:
            _git(c, "commit", "-q", "-m", "Desk endpoint: current API tunnel address (URL only)", "--", c["path"])
        _git(c, "push", "-q", c["remote"], f"HEAD:{c['branch']}")
        return "pushed"


def publish_async(url: str, retries: int = 6) -> threading.Thread | None:
    c = _cfg()
    if not c["enabled"]:
        return None

    def run():
        for i in range(retries):
            try:
                log.info("endpoint.json %s", publish(url, c))
                return
            except Exception as e:
                msg = getattr(e, "stderr", "") or str(e)
                log.warning("endpoint publish failed (try %d): %s", i + 1, str(msg).strip()[:300])
                time.sleep(min(300, 15 * 2 ** i))
    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t
