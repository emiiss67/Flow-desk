from fastapi.testclient import TestClient
from flowdesk.api import app
from flowdesk.auth import desk_key


def test_auth_required():
    c = TestClient(app)
    assert c.get("/health").status_code == 200
    assert c.get("/api/dashboard").status_code == 401
    r = c.get("/api/dashboard", headers={"X-Desk-Key": desk_key()})
    assert r.status_code == 200 and r.json()["paper"] is True
    assert c.get("/api/instruments?q=eur", params={"key": desk_key()}).json()["items"]
