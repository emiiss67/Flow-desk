import pytest
from flowdesk.journal import Journal
from flowdesk.broker import PaperBroker
from flowdesk.stats import performance

CFG = {"starting_balance": 10000, "risk_pct": 1.0, "max_positions": 2, "daily_loss_limit_pct": 2.0,
       "tp1_close_pct": 50, "trail_atr": 0, "spread_bps": {"futures": 0, "forex": 0, "commodities": 0},
       "slippage_bps": 0}


@pytest.fixture
def b():
    return PaperBroker(Journal(":memory:"), CFG)


def test_position_size_risk(b):
    # NQ: point value 20, 1% of 10k = 100 USD risk, 10 pt stop -> 0.5 contracts
    t = b.open("NQ=F", "LONG", 20000, 19990, 20015, 20030, tf="15m")
    assert t["qty"] == pytest.approx(0.5)
    assert t["risk_usd"] == pytest.approx(100)


def test_stop_loss_loses_one_r(b):
    t = b.open("NQ=F", "LONG", 20000, 19990, 20015, 20030)
    ev = b.update(t["id"], high=20005, low=19985, close=19988)
    assert ev[0]["kind"] == "stop loss"
    assert b.balance == pytest.approx(9900)
    assert b._get(t["id"])["r_multiple"] == pytest.approx(-1)


def test_tp1_then_breakeven(b):
    t = b.open("GC=F", "SHORT", 4000, 4010, 3985, 3970)    # pv 100, risk 100 -> qty 0.1
    ev = b.update(t["id"], high=4001, low=3984, close=3986)
    assert [e["kind"] for e in ev] == ["tp1"]
    assert ev[0]["pnl"] == pytest.approx(0.05 * 15 * 100)
    tr = b._get(t["id"])
    assert tr["sl"] == pytest.approx(4000) and tr["tp1_hit"] == 1
    ev = b.update(t["id"], high=4002, low=3990, close=4001)
    assert ev[0]["kind"] == "breakeven"
    assert b.balance == pytest.approx(10075)


def test_tp1_and_tp2_same_bar(b):
    t = b.open("NQ=F", "LONG", 20000, 19990, 20015, 20030)
    ev = b.update(t["id"], high=20040, low=19995, close=20035)
    assert [e["kind"] for e in ev] == ["tp1", "tp2"]
    assert b.balance == pytest.approx(10000 + 0.25 * 15 * 20 + 0.25 * 30 * 20)


def test_sl_wins_if_both_in_bar(b):
    t = b.open("NQ=F", "LONG", 20000, 19990, 20015, 20030)
    ev = b.update(t["id"], high=20020, low=19980, close=20000)
    assert ev[0]["kind"] == "stop loss"


def test_limits(b):
    assert b.open("NQ=F", "LONG", 20000, 19990, 20015, 20030)
    assert b.open("NQ=F", "LONG", 20000, 19990, 20015, 20030) is None      # one per symbol
    assert b.open("ES=F", "LONG", 6000, 5990, 6015, 6030)
    assert b.open("GC=F", "LONG", 4000, 3990, 4015, 4030) is None          # max positions
    b.j.set("paused", True)
    assert b.can_open("CL=F")[0] is False


def test_daily_loss_limit(b):
    for _ in range(2):
        t = b.open("NQ=F", "LONG", 20000, 19990, 20015, 20030)
        b.update(t["id"], high=20000, low=19980, close=19985)
    # -100 then -99 (1% of the reduced equity) = -1.99%: still allowed
    assert not b.daily_limit_hit()
    t = b.open("NQ=F", "LONG", 20000, 19990, 20015, 20030)
    b.update(t["id"], high=20000, low=19980, close=19985)
    assert b.daily_limit_hit()
    assert b.open("ES=F", "LONG", 6000, 5990, 6015, 6030) is None


def test_spread_costs():
    br = PaperBroker(Journal(":memory:"), dict(CFG, spread_bps={"forex": 1.0}, slippage_bps=0.5))
    px = br.fill_price("EURUSD=X", "LONG", 1.1, opening=True)
    assert px == pytest.approx(1.1 * (1 + 1.0e-4))
    assert br.fill_price("EURUSD=X", "LONG", 1.1, opening=False) < 1.1


def test_stats(b):
    t = b.open("NQ=F", "LONG", 20000, 19990, 20015, 20030)
    b.update(t["id"], high=20040, low=19995, close=20035)    # win
    t = b.open("NQ=F", "LONG", 20000, 19990, 20015, 20030)
    b.update(t["id"], high=20000, low=19980, close=19985)    # loss
    s = performance(b.j, 10000)
    assert s["trades"] == 2 and s["wins"] == 1 and s["win_rate"] == 50.0
    loss = 10225 * 0.01                      # second trade risks 1% of the grown equity
    assert s["profit_factor"] == pytest.approx(round(225 / loss, 2))
    assert s["max_drawdown"] == pytest.approx(loss)
    assert s["equity_curve"][-1]["value"] == pytest.approx(10225 - loss)
