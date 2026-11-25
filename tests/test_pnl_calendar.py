"""P&L calendar reset: hide past days, keep trade history and the paper balance."""
from datetime import datetime
from zoneinfo import ZoneInfo

from flowdesk.broker import PaperBroker, start_of_vilnius_day
from flowdesk.commands import Commands
from flowdesk.journal import Journal
from flowdesk.stats import performance


CFG = {"starting_balance": 50, "risk_pct": 10, "max_positions": 5, "daily_loss_limit_pct": 30,
       "tp1_close_pct": 50, "trail_atr": 0, "spread_bps": {"futures": 0, "forex": 0, "commodities": 0},
       "slippage_bps": 0, "max_leverage": 1000}
TZ = ZoneInfo("Europe/Vilnius")


class _TG:
    def send(self, *a, **k):
        return True


def _broker():
    return PaperBroker(Journal(":memory:"), CFG)


def _close_at(b, symbol, side, entry, exit_px, ts, sl=None, tp1=None, tp2=None):
    sl = sl if sl is not None else (entry - 0.01 if side == "LONG" else entry + 0.01)
    tp1 = tp1 if tp1 is not None else (entry + 0.01 if side == "LONG" else entry - 0.01)
    tp2 = tp2 if tp2 is not None else (entry + 0.02 if side == "LONG" else entry - 0.02)
    t = b.open(symbol, side, entry, sl, tp1, tp2, risk_pct=10)
    assert t, b.last_reject
    ev = b.close(t["id"], exit_px, ts=ts)
    assert ev and ev["trade"]["status"] == "closed"
    return ev


def test_start_of_vilnius_day_is_midnight():
    ts = start_of_vilnius_day()
    dt = datetime.fromtimestamp(ts, TZ)
    assert dt.hour == dt.minute == dt.second == 0
    # a time just before midnight stays on the previous morning
    prev = start_of_vilnius_day(ts - 1)
    assert prev == ts - 86400


def test_calendar_reset_hides_past_days_keeps_history_and_balance():
    b = _broker()
    today0 = start_of_vilnius_day()
    _close_at(b, "EURUSD=X", "LONG", 1.10, 1.09, today0 - 2 * 86400 + 3600)
    _close_at(b, "GBPUSD=X", "LONG", 1.30, 1.29, today0 - 86400 + 3600)
    today_ev = _close_at(b, "AUDUSD=X", "LONG", 0.65, 0.64, today0 + 3600)
    opened = b.open("GC=F", "SHORT", 2600, 2610, 2590, 2580, risk_pct=10)
    assert opened and opened["status"] == "open"

    before = performance(b.j, 50)
    assert before["trades"] == 3
    assert before["net"] < 0
    past = [d for d in before["daily_30"] if d["date"] < datetime.fromtimestamp(today0, TZ).date().isoformat()]
    assert any(d["pnl"] < 0 for d in past)
    today_pnl = today_ev["pnl"]
    bal, open_ids = b.balance, [t["id"] for t in b.open_trades()]

    rec = b.reset_pnl_calendar(note="test")
    assert rec["ts"] == today0
    assert b.balance == bal
    assert [t["id"] for t in b.open_trades()] == open_ids
    assert b.j.trades(limit=1000)  # history still there
    assert len([t for t in b.j.trades(limit=1000) if t["status"] == "closed"]) == 3

    after = performance(b.j, 50)
    assert after["calendar_reset"]["ts"] == today0
    assert after["trades"] == 3 and after["win_rate"] == before["win_rate"]  # learning stats kept
    assert after["net"] == round(today_pnl, 2)
    days = after["daily_30"]
    assert days[0]["date"] == datetime.fromtimestamp(today0, TZ).date().isoformat()
    assert all(d["date"] >= days[0]["date"] for d in days)
    assert abs(sum(d["pnl"] for d in days) - today_pnl) < 1e-9
    assert b.balance == bal and [t["id"] for t in b.open_trades()] == open_ids


def test_calendar_reset_does_not_change_paper_baseline():
    b = _broker()
    b.reset_paper(50, "fresh")
    b.topup(50, ts=int(b.j.get("equity_reset")["ts"]) + 10)
    today0 = start_of_vilnius_day()
    _close_at(b, "EURUSD=X", "LONG", 1.10, 1.09, today0 - 86400 + 3600)
    bal = b.balance
    b.reset_pnl_calendar()
    assert b.balance == bal
    assert b.j.get("equity_reset")["balance"] == 50
    p = performance(b.j, 50)
    assert p["reset"]["balance"] == 50
    assert p["net"] == 0  # yesterday's loss hidden from the period
    assert p["calendar_reset"]["ts"] == today0
    assert p["deposited"] == 50


def test_telegram_resetpnl_and_help():
    b = _broker()
    c = Commands(b.j, b, provider=None, tg=_TG())
    h = c.handle("/help")
    assert "/resetpnl" in h
    today0 = start_of_vilnius_day()
    _close_at(b, "EURUSD=X", "LONG", 1.10, 1.09, today0 - 86400 + 3600)
    bal = b.balance
    msg = c.handle("/resetpnl")
    assert "calendar reset" in msg.lower() or "P&amp;L calendar reset" in msg
    assert b.balance == bal
    assert b.j.get("pnl_calendar_reset")["ts"] == today0
    pnl = c.handle("/pnl")
    assert "since" in pnl.lower() and "Net" in pnl
