import os, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("FLOWDESK_DATA_DIR", tempfile.mkdtemp(prefix="flowdesk-test-"))
os.environ["FLOWDESK_PUBLISH"] = "0"   # never push endpoint.json from tests


import pytest


@pytest.fixture(autouse=True)
def _fixed_eod_clock(monkeypatch):
    """Entry-time tests must not depend on the wall clock: pin the end-of-day clock to Tuesday 12:00 New York."""
    from flowdesk import eod
    from datetime import datetime
    from zoneinfo import ZoneInfo
    noon = datetime(2026, 11, 10, 12, 0, tzinfo=ZoneInfo("America/New_York")).timestamp()
    monkeypatch.setattr(eod, "_clock", lambda: noon)
    yield
