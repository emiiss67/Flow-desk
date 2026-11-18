"""Tunnel URL publishing (docs/endpoint.json, URL only) against a local bare repo."""
import json
import subprocess

from flowdesk import publish


def _sh(*a, cwd=None):
    subprocess.run(a, cwd=cwd, check=True, capture_output=True)


def test_publish_endpoint(tmp_path):
    bare, work, other = tmp_path / "remote.git", tmp_path / "work", tmp_path / "other"
    _sh("git", "init", "-q", "--bare", "-b", "main", str(bare))
    _sh("git", "clone", "-q", str(bare), str(work))
    (work / "README.md").write_text("x\n")
    _sh("git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "init", cwd=work)
    _sh("git", "add", "README.md", cwd=work)
    _sh("git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "readme", cwd=work)
    _sh("git", "push", "-q", "origin", "HEAD:main", cwd=work)
    c = {"enabled": True, "repo_dir": str(work), "ssh_key": "/dev/null", "remote": str(bare), "branch": "main",
         "path": "docs/endpoint.json"}
    assert publish.publish("https://a-b.trycloudflare.com", c) == "pushed"
    assert publish.publish("https://a-b.trycloudflare.com", c) == "unchanged"
    assert publish.publish("https://c-d.trycloudflare.com", c) == "pushed"
    _sh("git", "clone", "-q", str(bare), str(other))
    doc = json.loads((other / "docs" / "endpoint.json").read_text())
    assert doc["api"] == "https://c-d.trycloudflare.com"
    assert "key" not in {k.lower() for k in doc} and "#" not in doc["api"]


def test_publish_disabled_in_tests():
    assert publish.publish_async("https://x.trycloudflare.com") is None
