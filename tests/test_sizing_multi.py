from flowdesk import sizing
from flowdesk.broker import PaperBroker
from flowdesk.journal import Journal
from flowdesk.config import get_config


def wr(win, n, exp, setup_stats=None):
    d = {"status": "ok", "direction": "LONG", "band": [50, 70], "win_rate": win, "n": n, "avg_r": exp, "expectancy_r": exp}
    if setup_stats:
        d["setup_stats"] = setup_stats
    return d


def test_tiers():
    c = get_config()
    assert sizing.choose(wr(75, 30, 0.8), c)["risk_pct"] == 80
    assert sizing.choose(wr(65, 30, 0.5), c)["risk_pct"] == 65
    assert sizing.choose(wr(55, 30, 0.2), c)["risk_pct"] == 50
    assert sizing.choose(wr(45, 30, 0.05), c)["risk_pct"] == 35
    assert sizing.choose(wr(35, 30, 0.01), c)["risk_pct"] == 20


def test_negative_low_sample_and_skip():
    c = get_config()
    assert sizing.choose(wr(55, 30, -0.1), c)["risk_pct"] == 20            # negative expectancy
    z = sizing.choose(wr(30, 60, -0.4), c)
    assert z["skip"] and z["risk_pct"] == 0                               # strongly negative, big sample
    assert not sizing.choose(wr(30, 30, -0.4), c)["skip"]                 # same but n < 50 -> 3%, not skipped
    low = sizing.choose(wr(90, 8, 2.0), c)
    assert low["risk_pct"] == 35 and "low sample" in low["reason"]
    assert sizing.choose({"status": "computing"}, c)["risk_pct"] == 35
    assert "computing" in sizing.choose({"status": "computing"}, c)["reason"]


def test_setup_history_preferred_when_big_enough():
    c = get_config()
    z = sizing.choose(wr(45, 100, 0.1, {"setup": "HVN Absorption", "n": 25, "win_rate": 66, "avg_r": 0.6}), c)
    assert z["risk_pct"] == 65 and "HVN Absorption" in z["reason"]
    z = sizing.choose(wr(45, 100, 0.1, {"setup": "HVN Absorption", "n": 5, "win_rate": 90, "avg_r": 2}), c)
    assert z["risk_pct"] == 35 and "HVN" not in z["reason"]


CFG = {"starting_balance": 1000, "risk_pct": 10, "max_positions": 15, "max_per_symbol": 2, "max_open_risk_pct": 80,
       "daily_loss_limit_pct": 30, "tp1_close_pct": 50, "trail_atr": 0, "spread_bps": {"forex": 0, "futures": 0, "other": 0},
       "slippage_bps": 0, "max_leverage": 0}


def test_many_positions_and_per_symbol_rules():
    b = PaperBroker(Journal(":memory:"), CFG)
    syms = ["EURUSD=X", "GBPUSD=X", "USDJPY=X", "NQ=F", "ES=F", "GC=F", "CL=F"]
    for s in syms:                                     # several in one go
        assert b.open(s, "LONG", 100, 99, 101, 102, risk_pct=5)
    assert len(b.open_trades()) == 7
    assert b.open("EURUSD=X", "LONG", 100, 99, 101, 102, risk_pct=5) is None            # same setup (structure)
    assert "this setup" in b.last_reject
    assert b.open("EURUSD=X", "LONG", 100, 99, 101, 102, risk_pct=5, setup="HVN Absorption")   # different setup ok
    assert b.open("EURUSD=X", "SHORT", 100, 101, 99, 98, risk_pct=5, setup="Key Level Absorption Reversal") is None
    assert "max 2" in b.last_reject


def test_open_risk_cap_cuts_and_blocks():
    b = PaperBroker(Journal(":memory:"), CFG)
    for s in ["A=F", "B=F", "C=F"]:
        assert b.open(s, "LONG", 100, 99, 101, 102, risk_pct=20)      # 60% at risk
    t = b.open("D=F", "LONG", 100, 99, 101, 102, risk_pct=20, risk_reason="20% - test")
    assert t and abs(t["risk_pct"] - 20) < 0.01                       # 80% total, exactly at the cap
    assert abs(b.open_risk_usd() - 800) < 1
    assert b.open("E=F", "LONG", 100, 99, 101, 102, risk_pct=5) is None
    assert "open-risk cap" in b.last_reject


def test_open_risk_cap_partial():
    b = PaperBroker(Journal(":memory:"), CFG)
    for s in ["A=F", "B=F", "C=F", "D=F", "E=F", "F=F", "G=F"]:
        b.open(s, "LONG", 100, 99, 101, 102, risk_pct=10)              # 70%
    t = b.open("H=F", "LONG", 100, 99, 101, 102, risk_pct=20, risk_reason="20% - test")
    assert t and abs(t["risk_pct"] - 10) < 0.05 and "open-risk cap" in t["risk_reason"]


def test_no_unsolicited_telegram():
    from flowdesk.bot import Bot

    class TG:
        token, chat_id = "x", "1"
        enabled = True
        sent = []

        def send(self, text, chat_id=None, buttons=None):
            self.sent.append(text); return True

    tg = TG()
    bot = Bot(journal=Journal(":memory:"), tg=tg)
    assert get_config()["telegram"]["auto_alerts"] is False
    bot.alert("📥 Paper entry ...")
    assert tg.sent == []
    bot.cfg = dict(bot.cfg, telegram={"auto_alerts": True})
    bot.alert("x")
    assert tg.sent == ["x"]


def test_config_defaults():
    c = get_config()
    assert c["broker"]["max_positions"] >= 15 and c["broker"]["max_open_risk_pct"] == 200 and c["broker"]["daily_loss_limit_pct"] == 30
    syms = {w["symbol"] for w in c["watchlist"]}
    assert {"EURUSD=X", "GBPJPY=X", "NQ=F", "GC=F", "CL=F", "BTC-USD"} <= syms and len(syms) >= 15


def test_thirty_percent_not_cut_on_tight_forex_stop():
    from flowdesk.broker import PaperBroker as PB
    lev = get_config()["broker"]["max_leverage"]
    q = PB.position_size(50, 30.0, 1.1, 1.0994, 1.0, 1.0, max_leverage=lev)   # 6 pip stop
    assert abs(q * 0.0006 - 15.0) < 0.02


def test_80pct_risk_not_cut_by_leverage_on_tight_forex_stop():
    """80% risk on a 5-pip EURUSD stop needs ~1,900x notional; the configured leverage cap must not shrink it."""
    c = get_config()["broker"]
    q = PaperBroker.position_size(50, 80, 1.1600, 1.1595, 1.0, 0.86, c.get("max_leverage", 0))
    risk = q * 0.0005 * 0.86
    assert abs(risk - 40) < 0.05


def test_plan_shows_config_tier_range():
    from flowdesk.api import _risk_plan
    t = _risk_plan()
    assert "20-80%" in t and "35%" in t


def test_open_risk_cap_from_config_allows_200pct():
    from flowdesk.api import _plan
    c = get_config()["broker"]
    assert float(c["max_open_risk_pct"]) == 200
    assert any("200% of equity" in x for x in _plan())
    b = PaperBroker(Journal(":memory:"), dict(CFG, starting_balance=100, max_open_risk_pct=200, max_leverage=5000))
    for s in ("EURUSD=X", "GBPUSD=X"):
        assert b.open(s, "LONG", 100, 99, 101, 102, risk_pct=80)["risk_pct"] == 80
    t = b.open("NQ=F", "LONG", 100, 99, 101, 102, risk_pct=80)       # 160% open -> cut to the remaining 40%
    assert t and abs(t["risk_pct"] - 40) < 0.5
