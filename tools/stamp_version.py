#!/usr/bin/env python3
"""Stamp the desk build: content hash of every desk file -> docs/version.json, ?v= cache-bust on every asset URL in
index.html, and the version the running page compares against. Run before committing desk changes
(tests/test_desk_version.py fails if it was forgotten). endpoint.json / version.json are not part of the hash."""
from __future__ import annotations
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

DOCS = Path(os.environ.get("FD_DOCS") or Path(__file__).resolve().parent.parent / "docs")
SKIP = {"version.json", "endpoint.json", "index.html"}


def content_hash() -> str:
    h = hashlib.sha256()
    for p in sorted(DOCS.rglob("*")):
        if p.is_file() and p.name not in SKIP and "/assets/bg/" not in p.as_posix():
            h.update(p.relative_to(DOCS).as_posix().encode()); h.update(p.read_bytes())
    idx = re.sub(r'\?v=[0-9a-z]+', '?v=', (DOCS / "index.html").read_text())
    idx = re.sub(r'(<meta name="fd-version" content=")[^"]*', r'\1', idx)
    h.update(idx.encode())
    return h.hexdigest()[:12]


def write_names() -> None:
    """docs/names.json = instruments.names(), so demo/offline desk uses the same friendly names as the API."""
    if os.environ.get("FD_DOCS"):
        return
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from flowdesk import instruments
    txt = json.dumps(instruments.names(), ensure_ascii=False, separators=(",", ":"))
    p = DOCS / "names.json"
    if not p.exists() or p.read_text() != txt:
        p.write_text(txt)


def stamp() -> str:
    write_names()
    v = content_hash()
    idx = (DOCS / "index.html").read_text()
    idx = re.sub(r'\?v=[0-9a-z]+', f'?v={v}', idx)
    idx = re.sub(r'(<meta name="fd-version" content=")[^"]*', rf'\g<1>{v}', idx)
    (DOCS / "index.html").write_text(idx)
    old = {}
    try:
        old = json.loads((DOCS / "version.json").read_text())
    except Exception:
        pass
    if old.get("version") != v:
        (DOCS / "version.json").write_text(json.dumps({"version": v, "built": int(time.time())}, indent=1) + "\n")
    return v


if __name__ == "__main__":
    print(stamp() if "--check" not in sys.argv else content_hash())
