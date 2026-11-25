"""Win-rate review 2026-11-25: closed-bar signals, quality gate, fill re-anchoring, same-direction cap."""
import pandas as pd
import pytest

from flowdesk import quality
from flowdesk.broker import PaperBroker
from flowdesk.data import closed_bars
from flowdesk.journal import Journal

CFG = {"broker": {"spread_bps": {"forex": 0.8, "futures": 1.0, "other": 2.0}, "slippage_bps": 0.5},
       "quality": {"enabled": True, "max_cost_r": 0.20, "block_streams": ["setup_hvn"], "block_atr_regime": ["low"],
                   "min_rr_at_fill": 1.0, "closed_bars_only": True,
                   "max_entry_drift_r": None}}


def frame(start, n, freq="15min"):
    idx = pd.date_range(start, periods=n, freq=freq, tz="UTC")
    return pd.DataFrame({"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 0.0}, index=idx)


def test_closed_bars_drops_forming_candle_forex_and_delayed_futures():
    df = frame("2026-11-25 08:00", 4)                                  # 08:00, 08:15, 08:30, 08:45
    now = pd.Timestamp("2026-11-25 08:52", tz="UTC").timestamp()
    assert list(closed_bars(df, "EURUSD=X", "15m", now).index.strftime("%H:%M")) == ["08:00", "08:15", "08:30"]
    # futures quotes are ~10 min late: the 08:30 bar is only complete in the feed after 08:56
    assert list(closed_bars(df, "NQ=F", "15m", now).index.strftime("%H:%M")) == ["08:00", "08:15"]


def test_quality_gate_rules():
    ok = lambda *a, **k: quality.check(*a, c=CFG, **k)[0]
    assert ok("core", "EURUSD=X", {"atr_regime": "normal"}, 1.1000, 1.0950)      # 50 pips stop: cost 0.04R
    assert not ok("core", "EURUSD=X", {"atr_regime": "normal"}, 1.1000, 1.0998)  # 2 pip stop: cost ~1R
    assert not ok("setup_hvn", "EURUSD=X", {"atr_regime": "normal"}, 1.1000, 1.0950)
    assert not ok("core", "EURUSD=X", {"atr_regime": "low"}, 1.1000, 1.0950)
    assert ok("core", "EURUSD=X", {"atr_regime": "low"}, 1.1000, 1.0950) is False
    assert quality.check("core", "X", {}, cost=0.25, c=dict(CFG, quality={"enabled": False}))[0]


def test_same_direction_cap_across_symbols():
    b = PaperBroker(Journal(":memory:"), {"starting_balance": 10000, "risk_pct": 1.0, "max_positions": 10,
                                          "max_same_direction_open": 2, "spread_bps": {}, "slippage_bps": 0})
    assert b.open("NQ=F", "SHORT", 20000, 20010, 19985, 19970)
    assert b.open("GC=F", "SHORT", 4000, 4010, 3985, 3970)
    assert b.open("ES=F", "SHORT", 6000, 6010, 5985, 5970) is None
    assert "2 open sell trades" in b.last_reject
    assert b.open("ES=F", "LONG", 6000, 5990, 6015, 6030)               # the other direction is still free


def test_fill_reanchored_to_live_price_and_min_rr():
    from flowdesk.bot import Bot
    bot = Bot.__new__(Bot)
    bot.cfg = CFG
    base = {"decision": "SHORT", "levels": {"entry": 1.1000, "sl": 1.1050, "tp1": 1.0925, "tp2": 1.0880}}
    r = dict(base, live_price=1.0990)
    ok, why = bot._quality(r, "EURUSD=X", "core", {"atr_regime": "normal"})
    assert ok and r["levels"]["entry"] == pytest.approx(1.0990)
    r = dict(base, live_price=1.0950)                                  # ran 50 pips: 0.25R left to TP1
    ok, why = bot._quality(r, "EURUSD=X", "core", {"atr_regime": "normal"})
    assert not ok and "left to TP1" in why
    r = dict(base, live_price=1.1060)                                  # already through the stop
    assert not bot._quality(r, "EURUSD=X", "core", {"atr_regime": "normal"})[0]
