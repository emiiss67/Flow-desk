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


def test_desk_check_notifies_once(monkeypatch):
    import flowdesk.api as api
    calls = []
    monkeypatch.setattr(api, "run_check", lambda s, tf, winrate="async", closed_only=False: {"ok": True, "symbol": s, "tf": tf, "decision": "LONG", "chart": {}})
    monkeypatch.setattr(api, "_notify_check", lambda r: calls.append(r))
    api._last_notify.clear()
    c = TestClient(app)
    h = {"X-Desk-Key": desk_key()}
    assert c.get("/api/check?symbol=EURUSD%3DX&tf=15m", headers=h).json().get("telegram") is None   # no notify flag
    assert c.get("/api/check?symbol=EURUSD%3DX&tf=15m&notify=1", headers=h).json()["telegram"] == "sent"
    assert c.get("/api/check?symbol=EURUSD%3DX&tf=15m&notify=1", headers=h).json()["telegram"].startswith("skipped")
    assert len(calls) == 1 and "chart" not in calls[0]


def test_signal_endpoints(monkeypatch):
    from flowdesk import signalcall
    monkeypatch.setattr(signalcall, "get", lambda sym, *a, **k: {"ok": True, "symbol": sym, "call": "NO TRADE", "strategies": []})
    monkeypatch.setattr(signalcall, "top", lambda *a, **k: {"ok": True, "actionable": [], "n_actionable": 0, "near": [], "n_symbols": 19, "all": []})
    c = TestClient(app)
    h = {"X-Desk-Key": desk_key()}
    assert c.get("/api/signal?symbol=NAS100").status_code == 401
    assert c.get("/api/signal?symbol=NAS100", headers=h).json()["symbol"] == "NQ=F"
    assert c.get("/api/signal?symbol=zzzz-nope", headers=h).status_code == 400
    assert c.get("/api/signal/top", headers=h).json()["n_symbols"] == 19
