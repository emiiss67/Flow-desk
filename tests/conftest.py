import os, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("FLOWDESK_DATA_DIR", tempfile.mkdtemp(prefix="flowdesk-test-"))
os.environ["FLOWDESK_PUBLISH"] = "0"   # never push endpoint.json from tests
