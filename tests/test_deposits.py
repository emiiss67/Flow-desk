"""Paper top-up / withdraw: deposits are cash, not profit."""
import time

import pytest
from flowdesk.broker import PaperBroker
from flowdesk.commands import Commands
from flowdesk.journal import Journal
from flowdesk.stats import performance


CFG = {"starting_balance": 50, "risk_pct": 10, "max_positions": 5, "daily_loss_limit_pct": 30,
       "tp1_close_pct": 50, "trail_atr": 0, "spread_bps": {"futures": 0, "forex": 0, "commodities": 0},
       "slippage_bps": 0, "max_leverage": 1000}


def broker(start=50, daily=30):
    return PaperBroker(Journal(":memory:"), dict(CFG, starting_balance=start, daily_loss_limit_pct=daily))


def test_topup_raises_balance_not_net():
    b = broker()
    rec = b.topup(50)
    assert rec["kind"] == "topup" and rec["amount"] == 50 and rec["balance"] == 100
    assert b.balance == 100 and b.equity() == 100
    p = performance(b.j, 50)
    assert p["net"] == 0 and p["trades"] == 0 and p["win_rate"] == 0 and p["deposited"] == 50
    assert p["deposits"][-1]["kind"] == "topup" and p["deposits"][-1]["amount"] == 50
    assert p["equity_curve"][0]["value"] == 50 and p["equity_curve"][-1]["value"] == 100


def test_topup_does_not_change_win_stats():
    b = broker()
    t = b.open("NQ=F", "LONG", 20000, 19990, 20015, 20030, risk_pct=10)
    b.update(t["id"], high=20040, low=19995, close=20035)  # win
    before = performance(b.j, 50)
    net, wr, n = before["net"], before["win_rate"], before["trades"]
    assert net > 0 and wr == 100 and n == 1
    eq_before = b.balance
    b.topup(20)
    after = performance(b.j, 50)
    assert after["net"] == net and after["win_rate"] == wr and after["trades"] == n
    assert after["deposited"] == 20
    assert b.balance == pytest.approx(eq_before + 20)
    assert after["equity_curve"][-1]["value"] == pytest.approx(eq_before + 20)


def test_withdraw_and_insufficient_funds():
    b = broker()
    b.topup(10)
    rec = b.withdraw(7.5)
    assert rec["kind"] == "withdraw" and rec["amount"] == 7.5 and rec["balance"] == 52.5
    p = performance(b.j, 50)
    assert p["net"] == 0 and p["deposited"] == pytest.approx(2.5)
    with pytest.raises(ValueError, match="not enough"):
        b.withdraw(100)
    with pytest.raises(ValueError, match="greater than 0"):
        b.topup(0)
    with pytest.raises(ValueError, match="greater than 0"):
        b.topup(-5)
    assert b.balance == 52.5


def test_daily_limit_baseline_moves_with_deposit():
    b = broker(start=50, daily=20)  # stop after -20% of baseline
    base0 = b.daily_limit_baseline()
    assert base0 == pytest.approx(50)
    # lose 10 (20% of 50) -> hits the limit
    t = b.open("NQ=F", "LONG", 20000, 19990, 20015, 20030, risk_pct=20)
    # 20% of 50 = 10 risk; stop should lose ~10
    ev = b.update(t["id"], high=20000, low=19980, close=19985)
    assert ev and ev[0]["kind"] == "stop loss"
    assert b.daily_limit_hit()
    assert b.can_open("ES=F")[0] is False
    lost = 50 - b.balance
    rec = b.topup(50)
    # baseline moves up by the deposit: 50 + 50 = 100; lost is still ~10, 20% of 100 = 20, so not hit
    assert rec["baseline"] == pytest.approx(50 + 50, abs=0.05)
    assert b.daily_limit_baseline() == pytest.approx(100, abs=0.05)
    assert not b.daily_limit_hit()
    assert b.can_open("ES=F")[0]
    # realized today is still the trading loss, not the deposit
    assert b.realized_today() == pytest.approx(-lost, abs=0.05)


def test_withdrawal_does_not_inflate_drawdown():
    b = broker()
    t = b.open("NQ=F", "LONG", 20000, 19990, 20015, 20030, risk_pct=10)
    b.update(t["id"], high=20040, low=19995, close=20035)  # win, equity > 50
    mid = performance(b.j, 50)
    assert mid["net"] > 0 and mid["max_drawdown"] == 0
    b.withdraw(20)
    after = performance(b.j, 50)
    assert after["net"] == mid["net"]
    assert after["max_drawdown"] == pytest.approx(mid["max_drawdown"])
    assert after["equity_curve"][-1]["value"] == pytest.approx(b.balance)


def test_paper_reset_then_deposit():
    b = broker()
    t = b.open("NQ=F", "LONG", 20000, 19990, 20015, 20030, risk_pct=10, ts=int(time.time()) - 120)
    b.update(t["id"], high=20000, low=19980, close=19985, ts=int(time.time()) - 60)
    rec = b.reset_paper(50, "test")
    b.topup(25, ts=rec["ts"] + 10)
    p = performance(b.j, 50)
    assert p["net"] == 0 and p["deposited"] == 25
    assert p["reset"]["balance"] == 50
    assert p["equity_curve"][0] == {"time": rec["ts"], "value": 50}
    assert p["equity_curve"][-1]["value"] == pytest.approx(75)
    assert p["all_time"]["net"] < 0


class _TG:
    def send(self, *a, **k):
        return True


def test_telegram_topup_and_usage():
    j = Journal(":memory:")
    b = PaperBroker(j, CFG)
    c = Commands(j, b, provider=None, tg=_TG())
    help_txt = c.handle("/topup")
    assert "Usage: /topup 50" in help_txt and "deposit, not profit" in help_txt
    assert "50.00" in c.handle("/topup") or "€50" in help_txt or "50" in help_txt
    bad = c.handle("/topup nope")
    assert "Usage: /topup 50" in bad
    ok = c.handle("/topup 50")
    assert "Topped up" in ok and "deposit" in ok and b.balance == 100
    p = c.handle("/pnl")
    assert "Deposits" in p and "Net" in p
    # net should still be zero in the pnl text: "Net €0" or similar, with Deposits shown
    w = c.handle("/withdraw 10")
    assert "Withdrew" in w and b.balance == 90
    too = c.handle("/withdraw 1000")
    assert "not enough" in too and b.balance == 90
    # € and comma
    c.handle("/topup €5,5")
    assert b.balance == 95.5


def test_telegram_help_lists_topup():
    c = Commands(Journal(":memory:"), PaperBroker(Journal(":memory:"), CFG), None, _TG())
    h = c.handle("/help")
    assert "/topup" in h and "/withdraw" in h
