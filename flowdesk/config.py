"""Config loading. YAML for settings, environment for secrets."""
from __future__ import annotations
import os
from pathlib import Path
from functools import lru_cache
import yaml

ROOT = Path(__file__).resolve().parent.parent


def load_dotenv(path: Path | None = None) -> None:
    """Minimal .env loader (no extra dependency). Existing env vars win."""
    path = path or ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


@lru_cache(maxsize=1)
def get_config() -> dict:
    load_dotenv()
    p = Path(os.environ.get("FLOWDESK_CONFIG", ROOT / "config.yaml"))
    if not p.is_absolute():
        p = ROOT / p
    with open(p) as f:
        cfg = yaml.safe_load(f) or {}
    return cfg


def data_dir() -> Path:
    load_dotenv()
    d = Path(os.environ.get("FLOWDESK_DATA_DIR", ROOT / "data"))
    if not d.is_absolute():
        d = ROOT / d
    d.mkdir(parents=True, exist_ok=True)
    return d


def secret(name: str) -> str | None:
    load_dotenv()
    v = os.environ.get(name)
    return v if v else None
