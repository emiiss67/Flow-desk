import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import stamp_version  # noqa: E402


def test_desk_build_is_stamped():
    """Run `python tools/stamp_version.py` after changing anything in docs/ (auto-update depends on it)."""
    v = stamp_version.content_hash()
    assert json.loads((ROOT / "docs/version.json").read_text())["version"] == v
    idx = (ROOT / "docs/index.html").read_text()
    assert f'<meta name="fd-version" content="{v}">' in idx
    assert set(re.findall(r"\?v=([0-9a-z]+)", idx)) == {v}
    assert "js/update.js?v=" in idx and (ROOT / "docs/sw.js").exists()


def test_desk_has_no_hardcoded_dollar_money():
    for p in (ROOT / "docs/js").glob("*.js"):
        if p.name == "lightweight-charts.js":
            continue
        s = p.read_text()
        assert "'-'}$${" not in s and "+ '$' +" not in s and "'$' +" not in s, p.name
        assert not re.search(r"[^\\$]\$\$\{", s), p.name


def test_names_json_matches_instruments():
    import json
    from pathlib import Path
    from flowdesk import instruments
    p = Path(__file__).resolve().parents[1] / "docs" / "names.json"
    assert json.loads(p.read_text()) == instruments.names(), "run python3 tools/stamp_version.py"
    for sym, v in instruments.names().items():
        assert not any(x in v["name"] for x in ("=X", "=F", "^", "-USD")), sym
