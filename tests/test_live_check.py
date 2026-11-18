"""Smoke test against live Yahoo data. Skipped when the network is unavailable."""
import pytest
from flowdesk.strategy import check


@pytest.mark.parametrize("sym", ["EURUSD=X", "NQ=F", "GC=F"])
def test_live_check(sym):
    r = check(sym, "15m")
    if not r.get("ok"):
        pytest.skip(f"live data unavailable: {r.get('detail')}")
    assert r["decision"] in ("LONG", "SHORT", "NO TRADE")
    assert 0 <= r["confluence"] <= 100
    assert r["chart"]["candles"] and r["orderflow_estimated"] is True
    if r["decision"] == "LONG":
        lv = r["levels"]
        assert lv["sl"] < lv["entry"] < lv["tp1"] < lv["tp2"]
    if r["decision"] == "SHORT":
        lv = r["levels"]
        assert lv["sl"] > lv["entry"] > lv["tp1"] > lv["tp2"]
