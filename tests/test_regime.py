import time
from flowdesk import learning, regime


def _t(day, r, **f):
    return {"t": 0, "day": day, "r": r, "win": r > 0, "f": dict({"symbol": "EURUSD=X", "session": "london", "trend": "trend"}, **f)}


def _rules():
    return {"strategies": {"core": {"enabled": True}, "setup_hvn": {"enabled": True}, "setup_klar": {"enabled": True},
                           "ema_pullback": {"enabled": False, "params": {}}, "orb": {"enabled": False, "params": {}}},
            "blocks": [], "symbols": {}}


def _data():
    days = ["2026-11-0%d" % d for d in (2, 3, 4, 5, 6)] + ["2026-11-%d" % d for d in (9, 10, 11, 12, 13)]
    return days


def test_evaluate_walk_forward(monkeypatch):
    days = _data()
    A, B = days[:6], days[6:]
    tr = {
        "core": [_t(d, -0.3) for d in A for _ in range(3)] + [_t(d, -0.4) for d in B for _ in range(3)],     # loses twice -> pause
        "setup_hvn": [_t(d, 0.2) for d in A for _ in range(2)] + [_t(d, 0.3) for d in B for _ in range(3)],
        "setup_klar": [],
        # good only in London, both windows -> on for London only
        "ema_pullback": [_t(d, 0.5) for d in A for _ in range(2)] + [_t(d, -0.6, session="asia") for d in A for _ in range(3)]
                        + [_t(d, 0.4) for d in B for _ in range(3)] + [_t(d, -0.5, session="asia") for d in B for _ in range(3)],
        # good before, bad now -> stays off
        "orb": [_t(d, 0.5) for d in A for _ in range(2)] + [_t(d, -0.5) for d in B for _ in range(3)],
    }
    monkeypatch.setattr(regime, "recent_trades", lambda data, rules: tr)
    monkeypatch.setattr(regime, "_days", lambda data: days)
    out = regime.evaluate([], _rules())
    s = out["strategies"]
    assert s["core"]["state"] == "paused" and "Paused" in s["core"]["reason"]
    assert s["setup_hvn"]["state"] == "on"
    assert s["ema_pullback"]["state"] == "on" and s["ema_pullback"]["scopes"][0]["scope"] == {"feature": "session", "bucket": "london"}
    assert "London" in s["ema_pullback"]["reason"] and "n=12" in s["ema_pullback"]["reason"]
    assert s["orb"]["state"] == "off" and "not in the last" in s["orb"]["reason"]


def test_entry_filter_uses_regime():
    r = _rules()
    r["regime"] = {"computed": int(time.time()), "strategies": {
        "core": {"name": "Confluence engine", "state": "paused", "reason": "Paused for now: lost"},
        "ema_pullback": {"name": "EMA pullback", "state": "on", "scopes": [{"scope": {"feature": "session", "bucket": "london"}, "text": "in London session"}]},
        "orb": {"name": "ORB", "state": "off"}}}
    assert not learning.allow(r, "core", "EURUSD=X", {"session": "london"}, 70)[0]
    assert regime.switched_on(r, "ema_pullback") and not regime.switched_on(r, "orb")
    assert learning.allow(r, "ema_pullback", "EURUSD=X", {"session": "london"})[0]
    ok, why = learning.allow(r, "ema_pullback", "EURUSD=X", {"session": "asia"})
    assert not ok and "only on in London" in why
    assert not learning.allow(r, "orb", "EURUSD=X", {"session": "london"})[0]
    r["regime"]["computed"] = int(time.time()) - 4 * 86400            # stale -> long-term settings only
    assert learning.allow(r, "core", "EURUSD=X", {"session": "london"}, 70)[0]
    assert not learning.allow(r, "ema_pullback", "EURUSD=X", {"session": "london"})[0]


def test_plan_line(monkeypatch):
    from flowdesk import api
    r = _rules()
    r["regime"] = {"computed": int(time.time()), "strategies": {
        "core": {"name": "Confluence engine", "state": "paused", "reason": "x"},
        "setup_hvn": {"name": "HVN Absorption", "state": "on"},
        "ema_pullback": {"name": "EMA pullback", "state": "on", "scopes": [{"scope": {"feature": "symbol", "bucket": "AUDUSD=X"}, "text": "on AUD/USD"}]}}}
    monkeypatch.setattr(learning, "load_rules", lambda: r)
    line = api._regime_plan()[0]
    assert "HVN Absorption" in line and "EMA pullback (on AUD/USD)" in line and "paused while losing recently: Confluence engine" in line
