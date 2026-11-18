"""Strategy scoring, level math, paper fills, and the read-only check API."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from flowdesk.bot import BotContext, handle_text
from flowdesk.broker import PaperBroker
from flowdesk.catalog import load_catalog
from flowdesk.config import load_settings
from flowdesk.engine import Runtime
from flowdesk.events import headline_score, parse_calendar_payload, parse_feed
from flowdesk.market import OANDA_HOST, bars_from_yahoo_frame, parse_oanda_time, resample_h4
from flowdesk.models import (
    AccountState,
    Bar,
    CalendarEvent,
    DataUnavailable,
    FairValueGap,
    MarketSnapshot,
    Structure,
    Swing,
)
from flowdesk.orderflow import candle_delta, detect_absorption, estimate_orderflow
from flowdesk.server import create_app
from flowdesk.strategy import Facts, build_levels, evaluate_setup, score_facts
from flowdesk.structure import average_true_range, fair_value_gaps, find_swings
from flowdesk.tunnel import desk_link, extract_tunnel_url

UTC = timezone.utc
ROOT = Path(__file__).resolve().parents[1]


def bar(i, o, h, l, c, v=1000.0, minutes=15):
    start = datetime(2026, 1, 5, 8, 0, tzinfo=UTC)
    return Bar(start + timedelta(minutes=minutes * i), o, h, l, c, v)


def rising(n=60, volume=1000.0):
    bars = []
    price = 1.10
    for i in range(n):
        o = price
        c = price + 0.0004
        bars.append(bar(i, o, c + 0.0001, o - 0.0001, c, volume))
        price = c
    return bars


def account(balance=10000.0, realized=0.0, paused=False, day=None):
    moment = datetime(2026, 1, 6, 15, 0, tzinfo=UTC)
    return AccountState(
        balance=balance,
        starting_balance=balance,
        day=day or moment.date(),
        day_start=balance,
        realized_today=realized,
        paused=paused,
    )


NOW = datetime(2026, 1, 6, 15, 0, tzinfo=UTC)


def test_catalog_keys_do_not_collide():
    seen = {}
    for inst in load_catalog():
        keys = [inst.id, *inst.aliases]
        for key in keys:
            assert key.upper() not in seen, key
            seen[key.upper()] = inst.id
        assert inst.category in {"forex", "indices", "futures", "commodities", "crypto"}


def test_config_is_loopback_and_has_no_secrets():
    settings = load_settings(str(ROOT / "config.yaml"))
    assert settings.host == "127.0.0.1"
    assert "https://emiiss67.github.io" in settings.cors_origins
    text = (ROOT / "config.yaml").read_text(encoding="utf-8")
    assert "FLOWDESK_TELEGRAM_TOKEN=" not in text
    assert "OANDA_API_KEY=" not in text
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "FLOWDESK_TELEGRAM_TOKEN=" in example
    assert "OANDA_API_KEY=" in example


def test_oanda_is_practice_only_and_has_no_order_route():
    source = (ROOT / "flowdesk" / "market.py").read_text(encoding="utf-8")
    assert OANDA_HOST == "https://api-fxpractice.oanda.com"
    assert "fxtrade" not in source
    assert "/orders" not in source


def test_swings_and_bullish_fvg():
    bars = [
        bar(0, 10, 11, 9.5, 10.4),
        bar(1, 10.4, 10.6, 9.8, 10.0),
        bar(2, 10.0, 10.2, 8.0, 9.0),
        bar(3, 9.0, 9.4, 8.4, 8.8),
        bar(4, 8.8, 9.2, 8.6, 9.1),
    ]
    swings = find_swings(bars, left=2, right=2)
    lows = [item for item in swings if item.kind == "low"]
    assert any(item.index == 2 and item.price == 8.0 for item in lows)
    gap_bars = [
        bar(0, 10, 11, 9.5, 10.5),
        bar(1, 10.5, 13, 10.4, 12.8),
        bar(2, 12.8, 14, 12.2, 13.6),
    ]
    gaps = fair_value_gaps(gap_bars, min_gap=0.1)
    assert len(gaps) == 1
    assert gaps[0].direction == "bullish"
    assert gaps[0].bottom == pytest.approx(11)
    assert gaps[0].top == pytest.approx(12.2)
    assert gaps[0].mitigated is False
    filled = gap_bars + [bar(3, 13.6, 13.7, 10.5, 11.2)]
    assert fair_value_gaps(filled, min_gap=0.1)[0].mitigated is True


def test_candle_delta_and_missing_volume():
    assert candle_delta(bar(0, 10, 12, 10, 12, 100)) == pytest.approx(100)
    assert candle_delta(bar(0, 12, 12, 10, 10, 100)) == pytest.approx(-100)
    assert candle_delta(bar(0, 10, 10, 10, 10, 5)) is None
    wick = Bar(datetime(2026, 1, 5, tzinfo=UTC), 10.2, 10.4, 9.0, 10.3, 500)
    assert detect_absorption(wick, True) == "bullish"
    assert detect_absorption(wick, False) is None
    empty = estimate_orderflow(rising(10, volume=0))
    assert empty.available is False
    assert empty.cumulative_delta is None
    assert "volume" in empty.reason
    live = estimate_orderflow(rising(30, volume=1000))
    assert live.available is True
    assert live.kind == "estimate"
    assert live.cumulative_delta is not None and live.cumulative_delta > 0
    assert "not" in live.note.lower() and "footprint" in live.note.lower()


def test_score_long_confluence_and_conflict():
    facts = Facts(
        bias="bullish",
        bos="bullish",
        zone="discount",
        ote="long",
        killzone="London",
        htf_bias="bullish",
        htf_name="H1",
        flow_available=True,
        delta_ratio=0.2,
        timeframe="M15",
    )
    call, confidence, long_pts, short_pts, reasons, tags, clear = score_facts(facts, min_score=55)
    # 18 bias + 12 BOS + 8 discount + 8 OTE + 10 HTF + 10 delta + 4 killzone
    assert long_pts == pytest.approx(70)
    assert short_pts == 0
    assert call == "LONG"
    assert clear == "LONG"
    assert confidence == 70
    assert "Structure" in tags and "Delta" in tags
    assert any("not tick" in reason.text for reason in reasons)

    conflict = Facts(bias="bullish", htf_bias="bearish", htf_name="H1", flow_available=False, flow_reason="volume not provided by this feed", timeframe="M15")
    call, confidence, long_pts, short_pts, reasons, _tags, clear = score_facts(conflict, min_score=55)
    assert call == "NO TRADE"
    assert clear == "LONG"
    assert long_pts == pytest.approx(18)
    assert short_pts == pytest.approx(10)
    assert confidence == 8
    assert any("unavailable" in reason.text.lower() for reason in reasons)


def test_long_stop_is_derived_from_the_swing():
    bars = [bar(0, 100, 101, 99, 100)]
    when = bars[0].time
    structure = Structure(
        bias="bullish",
        last_swing_low=Swing(0, when, "low", 97),
        last_swing_high=Swing(0, when, "high", 106),
        atr=2,
        liquidity=[],
    )
    levels = build_levels("long", bars, structure)
    assert levels.entry == pytest.approx(100)
    assert levels.stop == pytest.approx(97 - 0.15 * 2)
    assert levels.stop < 97
    assert levels.tp1 == pytest.approx(106)
    assert "swing low" in levels.basis["stop"]
    assert "swing high" in levels.basis["tp1"]
    risk = levels.entry - levels.stop
    assert levels.rr1 == pytest.approx((levels.tp1 - levels.entry) / risk)

    short_structure = Structure(
        bias="bearish",
        last_swing_high=Swing(0, when, "high", 103),
        last_swing_low=Swing(0, when, "low", 94),
        atr=2,
    )
    short_levels = build_levels("short", [bar(0, 100, 101, 99, 100)], short_structure)
    assert short_levels.stop == pytest.approx(103 + 0.3)
    assert short_levels.stop > 103
    assert short_levels.tp1 == pytest.approx(94)


def test_flat_market_stop_falls_back_to_atr_and_says_so():
    bars = rising(50)
    structure = Structure(bias="unclear", atr=average_true_range(bars), fvgs=[], order_blocks=[], sweeps=[], liquidity=[])
    levels = build_levels("long", bars, structure)
    assert "1.2 ATR" in levels.basis["stop"]
    assert levels.stop < bars[-1].close
    assert levels.tp1 > bars[-1].close
    assert levels.tp2 > levels.tp1


def test_event_blackout_forces_no_trade_and_zero_volume_is_not_invented():
    eurusd = next(inst for inst in load_catalog() if inst.id == "EURUSD")
    bars = rising(50, volume=0)
    event = CalendarEvent("CPI m/m", "USD", "High", bars[-1].time + timedelta(minutes=10), "0.3%", "0.2%")
    result = evaluate_setup(
        bars,
        instrument=eurusd,
        timeframe="M15",
        now=bars[-1].time,
        events=[event],
        min_score=55,
        blackout_minutes=30,
        min_bars=40,
    )
    assert result.call == "NO TRADE"
    assert result.blocked_by_event is True
    assert any("CPI" in warning for warning in result.warnings)
    assert result.order_flow["available"] is False
    assert result.order_flow["cumulative_delta"] is None
    assert result.to_dict()["placed_trade"] is False
    # A currency that is not in the pair does not block it.
    other = CalendarEvent("BOJ rate", "JPY", "High", bars[-1].time + timedelta(minutes=5), "", "")
    clear = evaluate_setup(
        bars,
        instrument=eurusd,
        timeframe="M15",
        now=bars[-1].time,
        events=[other],
        min_bars=40,
        blackout_minutes=30,
    )
    assert clear.blocked_by_event is False


def test_paper_stop_risks_one_percent_including_slippage():
    broker = PaperBroker(1.0, 3, 3.0)
    state = account()
    opened = broker.open_position(
        state,
        symbol="EURUSD",
        side="long",
        mid=1.1,
        sl=1.098,
        tp1=1.11,
        tp2=1.12,
        spread=0.0002,
        slippage=0.0001,
        now=NOW,
    )
    assert opened.kind == "open"
    assert opened.position.entry == pytest.approx(1.1002)
    stop_exit = 1.0979
    assert opened.position.qty == pytest.approx(100 / (1.1002 - stop_exit))
    stop_bar = bar(1, 1.1002, 1.101, 1.09, 1.095)
    events = broker.on_bar(state, "EURUSD", stop_bar, stop_bar.time, 0.0001)
    assert events[-1].message == "stop-loss"
    assert events[-1].position.exit_price == pytest.approx(stop_exit)
    assert events[-1].pnl == pytest.approx(-100)
    assert state.balance == pytest.approx(9900)


def test_same_bar_stop_beats_target_and_both_targets_fill():
    broker = PaperBroker(1.0, 3, 50.0)
    state = account()
    broker.open_position(
        state,
        symbol="ES",
        side="long",
        mid=100,
        sl=95,
        tp1=110,
        tp2=120,
        spread=0,
        slippage=0,
        now=NOW,
    )
    both = bar(1, 100, 121, 96, 120)
    events = broker.on_bar(state, "ES", both, both.time, 0)
    assert [event.kind for event in events] == ["partial", "close"]
    # Half at 110, half at 120. qty = 100 / 5 = 20.
    assert events[0].pnl == pytest.approx((110 - 100) * 10)
    assert events[1].pnl == pytest.approx((120 - 100) * 10)
    assert state.balance == pytest.approx(10000 + 100 + 200)

    state = account()
    broker.open_position(
        state,
        symbol="ES",
        side="long",
        mid=100,
        sl=95,
        tp1=110,
        tp2=120,
        spread=0,
        slippage=0,
        now=NOW,
    )
    clash = bar(2, 100, 121, 94, 100)
    events = broker.on_bar(state, "ES", clash, clash.time, 0)
    assert len(events) == 1
    assert events[0].message == "stop-loss"
    assert events[0].pnl == pytest.approx(-100)


def test_trailing_stop_only_ratchets_forward():
    broker = PaperBroker(1.0, 3, 50.0)
    state = account()
    opened = broker.open_position(
        state,
        symbol="ES",
        side="long",
        mid=100,
        sl=95,
        tp1=130,
        tp2=140,
        spread=0,
        slippage=0,
        now=NOW,
        trail_distance=4,
    )
    assert opened.position.qty == pytest.approx(20)
    first = bar(1, 100, 108, 101, 107)
    assert broker.on_bar(state, "ES", first, first.time, 0) == []
    assert opened.position.sl == pytest.approx(104)
    assert opened.position.sl_kind == "trail"
    # A pullback above the old stop but through the trailed stop.
    second = bar(2, 107, 108, 104, 105)
    events = broker.on_bar(state, "ES", second, second.time, 0)
    assert events[-1].message == "trailing stop"
    assert events[-1].position.exit_price == pytest.approx(104)
    assert events[-1].pnl == pytest.approx(80)


def test_partial_then_breakeven_and_short_stop():
    broker = PaperBroker(1.0, 3, 50.0)
    state = account()
    opened = broker.open_position(
        state,
        symbol="ES",
        side="long",
        mid=100,
        sl=95,
        tp1=110,
        tp2=130,
        spread=0,
        slippage=0,
        now=NOW,
    )
    hit = bar(1, 100, 110, 99, 110)
    events = broker.on_bar(state, "ES", hit, hit.time, 0)
    assert events[0].message == "take-profit 1"
    assert opened.position.sl == pytest.approx(100)
    assert opened.position.sl_kind == "breakeven"
    assert opened.position.qty == pytest.approx(10)
    back = bar(2, 110, 111, 100, 101)
    stopped = broker.on_bar(state, "ES", back, back.time, 0)
    assert stopped[-1].message == "breakeven stop"
    assert stopped[-1].pnl == pytest.approx(0)

    state = account()
    short = broker.open_position(
        state,
        symbol="ES",
        side="short",
        mid=100,
        sl=105,
        tp1=90,
        tp2=80,
        spread=0.2,
        slippage=0.1,
        now=NOW,
    )
    # Short entry is worsened: 100 - 0.1 - 0.1 = 99.8
    assert short.position.entry == pytest.approx(99.8)
    # Stop fill 105 + 0.1 = 105.1, distance 5.3, risk budget 100.
    spike = bar(3, 100, 106, 99, 104)
    events = broker.on_bar(state, "ES", spike, spike.time, 0.1)
    assert events[-1].message == "stop-loss"
    assert events[-1].pnl == pytest.approx(-100)


def test_limits_block_new_trades_but_stops_still_run():
    broker = PaperBroker(1.0, 2, 3.0)
    state = account(realized=-300)
    blocked = broker.open_position(
        state, symbol="EURUSD", side="long", mid=1.1, sl=1.09, tp1=1.12, tp2=1.13, spread=0, slippage=0, now=NOW
    )
    assert blocked.message == "daily loss limit"
    state = account()
    state.paused = True
    assert broker.open_position(
        state, symbol="EURUSD", side="long", mid=1.1, sl=1.09, tp1=1.12, tp2=1.13, spread=0, slippage=0, now=NOW
    ).message == "paused"
    state = account()
    for name, mid in (("EURUSD", 1.1), ("GBPUSD", 1.2)):
        assert broker.open_position(
            state, symbol=name, side="long", mid=mid, sl=mid - 0.01, tp1=mid + 0.02, tp2=mid + 0.03, spread=0, slippage=0, now=NOW
        ).kind == "open"
    third = broker.open_position(
        state, symbol="USDJPY", side="long", mid=150, sl=149, tp1=152, tp2=153, spread=0, slippage=0, now=NOW
    )
    assert third.message == "max positions"
    # An open book still obeys its stop while new entries are blocked.
    state.realized_today = -10_000
    stop_bar = bar(4, 1.1, 1.11, 1.0, 1.05)
    events = broker.on_bar(state, "EURUSD", stop_bar, stop_bar.time, 0)
    assert events[-1].message == "stop-loss"


def test_calendar_news_and_tunnel_link():
    events = parse_calendar_payload(
        [{"title": "CPI m/m", "country": "USD", "date": "2026-11-18T08:30:00-05:00", "impact": "High", "forecast": "0.3%", "previous": "0.2%"}]
    )
    assert events[0].currency == "USD"
    assert events[0].time.hour == 13
    eurusd = next(inst for inst in load_catalog() if inst.id == "EURUSD")
    assert headline_score("Fed holds rates, dollar slips", eurusd) >= 2
    assert headline_score("Local bakery opens a new shop", eurusd) == 0
    items = parse_feed(
        """<?xml version="1.0"?><rss><channel><item><title>ECB speaker on euro</title><link>https://example.com/a</link></item></channel></rss>""",
        "example.com",
    )
    assert items[0]["title"] == "ECB speaker on euro"
    log = "2026 something https://odd-unit.trycloudflare.com more https://later-one.trycloudflare.com tail"
    assert extract_tunnel_url(log) == "https://later-one.trycloudflare.com"
    assert extract_tunnel_url("no tunnel") is None
    link = desk_link("https://later-one.trycloudflare.com", "abc")
    assert link == "https://emiiss67.github.io/Flow-desk/#api=https://later-one.trycloudflare.com&key=abc"


def test_yahoo_frame_resample_and_oanda_time():
    import pandas as pd

    index = pd.date_range("2026-01-05", periods=8, freq="h", tz="UTC")
    frame = pd.DataFrame(
        {
            "Open": [float(i) for i in range(8)],
            "High": [float(i) + 1 for i in range(8)],
            "Low": [float(i) - 0.2 for i in range(8)],
            "Close": [float(i) + 0.4 for i in range(8)],
            "Volume": [10.0] * 8,
        },
        index=index,
    )
    bars = bars_from_yahoo_frame(frame)
    assert len(bars) == 8
    assert len(resample_h4(bars)) == 2
    with pytest.raises(DataUnavailable):
        bars_from_yahoo_frame(frame.iloc[0:0])
    parsed = parse_oanda_time("2026-11-18T12:00:00.000000000Z")
    assert parsed == datetime(2026, 11, 18, 12, 0, tzinfo=UTC)


class _Market:
    def __init__(self, bars, fail=False):
        self._bars = bars
        self.fail = fail
        self.oanda = type("O", (), {"enabled": False})()

    def oanda_enabled(self):
        return False

    def fetch(self, instrument, timeframe, limit=300):
        if self.fail:
            raise DataUnavailable("Yahoo Finance returned no candles")
        return MarketSnapshot(self._bars, "Test feed", instrument.yahoo, "test delay note", self._bars[-1].time)


class _Calendar:
    def __init__(self, events=None, available=True):
        self._events = events or []
        self._available = available

    def typed_events(self):
        return (self._events, self._available)

    def load(self):
        if not self._available:
            return {"available": False, "error": "data unavailable", "detail": "down", "events": [], "stale": False, "as_of": None}
        return {
            "available": True,
            "error": None,
            "detail": None,
            "stale": False,
            "as_of": "2026-01-05T00:00:00+00:00",
            "events": [
                {
                    "title": event.title,
                    "currency": event.currency,
                    "impact": event.impact,
                    "time": event.time.isoformat(),
                    "forecast": event.forecast,
                    "previous": event.previous,
                }
                for event in self._events
            ],
        }


def _client(tmp_path, fail=False):
    settings = load_settings(str(ROOT / "config.yaml"))
    settings.database = str(tmp_path / "book.sqlite")
    settings.desk_key_file = str(tmp_path / "desk.key")
    settings.min_bars = 40
    runtime = Runtime(settings, market=_Market(rising(80), fail=fail), calendar=_Calendar())
    app = create_app(runtime, "desk-key")
    return TestClient(app), runtime


def test_check_never_opens_and_missing_data_is_not_faked(tmp_path, monkeypatch):
    client, runtime = _client(tmp_path)
    calls = {"n": 0}
    original = PaperBroker.open_position

    def wrapped(self, *args, **kwargs):
        calls["n"] += 1
        return original(self, *args, **kwargs)

    monkeypatch.setattr(PaperBroker, "open_position", wrapped)
    denied = client.get("/api/check", params={"symbol": "EURUSD"})
    assert denied.status_code == 401
    before = runtime.store.load_state().balance
    response = client.get("/api/check", params={"symbol": "EURUSD", "timeframe": "M15", "key": "desk-key"})
    assert response.status_code == 200
    body = response.json()
    assert body["placed_trade"] is False
    assert body["call"] in {"LONG", "SHORT", "NO TRADE"}
    assert body["paper_only"] is True
    assert body["data"]["source"] == "Test feed"
    assert "probability" in body["confidence_note"]
    assert calls["n"] == 0
    state = runtime.store.load_state()
    assert state.balance == before
    assert state.open_positions() == []
    posted = client.post("/api/check", params={"key": "desk-key"}, json={"symbol": "EURUSD", "timeframe": "H1"})
    assert posted.status_code == 200
    assert posted.json()["placed_trade"] is False

    dead_client, _dead = _client(tmp_path / "dead", fail=True)
    missing = dead_client.get("/api/check", params={"symbol": "EURUSD", "key": "desk-key"})
    assert missing.status_code == 503
    assert missing.json()["error"] == "data unavailable"
    assert "cumulative_delta" not in missing.json()


def test_routes_are_read_only_except_check(tmp_path):
    client, runtime = _client(tmp_path)
    app = client.app
    mutating = []
    for route in app.routes:
        methods = set(getattr(route, "methods", set()) or set())
        path = getattr(route, "path", "")
        if methods & {"POST", "PUT", "PATCH", "DELETE"}:
            mutating.append(path)
    assert mutating == ["/api/check"]
    health = client.get("/api/health", params={"key": "desk-key"})
    assert health.status_code == 200
    assert health.json()["paper"] is True
    positions = client.get("/api/positions", params={"key": "desk-key"})
    assert positions.json()["positions"] == []
    instruments = client.get("/api/instruments", params={"key": "desk-key", "q": "gold"})
    ids = [item["id"] for item in instruments.json()["instruments"]]
    assert "GC" in ids or "XAUUSD" in ids


def test_desk_page_is_labeled_and_static():
    html = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "docs" / "js" / "desk.js").read_text(encoding="utf-8")
    assert "FlowDesk" in html
    assert ">Paper<" in html
    assert "DEMO – sample data" in html
    assert "lightweight-charts" in html
    assert "data unavailable" in js
    assert "Sample confluence" in js
    # Relative asset paths so GitHub Pages project sites work.
    assert 'href="css/desk.css"' in html
    assert 'src="js/desk.js"' in html


def test_telegram_ignores_other_chats(tmp_path):
    client, runtime = _client(tmp_path)
    ctx = BotContext(runtime, None, str(tmp_path / "telegram_chat_id"))
    assert handle_text("/positions", 111, ctx) is None
    claimed = handle_text("/start", 111, ctx)
    assert "111" in claimed
    assert handle_text("/pnl", 222, ctx) is None
    assert "Balance" in handle_text("/pnl", 111, ctx)
    assert "paused" in handle_text("/pause", 111, ctx).lower()
    assert runtime.store.is_paused() is True
