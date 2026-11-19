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
    assert sizing.choose(wr(75, 30, 0.8), c)["risk_pct"] == 35
    assert sizing.choose(wr(65, 30, 0.5), c)["risk_pct"] == 15
    assert sizing.choose(wr(55, 30, 0.2), c)["risk_pct"] == 12
    assert sizing.choose(wr(45, 30, 0.05), c)["risk_pct"] == 10
    assert sizing.choose(wr(35, 30, 0.01), c)["risk_pct"] == 5


def test_negative_low_sample_and_skip():
    c = get_config()
    assert sizing.choose(wr(55, 30, -0.1), c)["risk_pct"] == 5             # negative expectancy
    z = sizing.choose(wr(30, 60, -0.4), c)
    assert z["skip"] and z["risk_pct"] == 0                               # strongly negative, big sample
    assert not sizing.choose(wr(30, 30, -0.4), c)["skip"]                 # same but n < 50 -> 3%, not skipped
    low = sizing.choose(wr(90, 8, 2.0), c)
    assert low["risk_pct"] == 7 and "low sample" in low["reason"]
    assert sizing.choose({"status": "computing"}, c)["risk_pct"] == 7
    assert "computing" in sizing.choose({"status": "computing"}, c)["reason"]


def test_setup_history_preferred_when_big_enough():
    c = get_config()
    z = sizing.choose(wr(45, 100, 0.1, {"setup": "HVN Absorption", "n": 25, "win_rate": 66, "avg_r": 0.6}), c)
    assert z["risk_pct"] == 15 and "HVN Absorption" in z["reason"]
    z = sizing.choose(wr(45, 100, 0.1, {"setup": "HVN Absorption", "n": 5, "win_rate": 90, "avg_r": 2}), c)
    assert z["risk_pct"] == 10 and "HVN" not in z["reason"]          # falls back to the overall 45% tier


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
    assert c["broker"]["max_positions"] >= 15 and c["broker"]["max_open_risk_pct"] == 60 and c["broker"]["daily_loss_limit_pct"] == 30
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
    assert "5-35%" in t and "7%" in t


def test_open_risk_cap_from_config_60pct():
    from flowdesk.api import _plan
    c = get_config()["broker"]
    assert float(c["max_open_risk_pct"]) == 60 and float(c["max_same_direction_risk_pct"]) == 45
    assert int(c["max_same_direction_per_group"]) == 2
    p = _plan()
    assert any("60% of equity" in x for x in p) and any("45% of equity" in x and "max 2" in x for x in p)
    b = PaperBroker(Journal(":memory:"), dict(CFG, starting_balance=100, max_open_risk_pct=60, max_leverage=5000))
    assert b.open("EURUSD=X", "LONG", 100, 99, 101, 102, risk_pct=35)["risk_pct"] == 35   # a single 35% trade fits
    t = b.open("GC=F", "LONG", 100, 99, 101, 102, risk_pct=35)                            # cut to the remaining 25%
    assert t and abs(t["risk_pct"] - 25) < 0.5


LIVE_CAPS = dict(CFG, starting_balance=50, max_open_risk_pct=60, max_same_direction_risk_pct=45,
                 max_same_direction_per_group=2, max_leverage=5000)


def test_correlated_shorts_blocked_after_two():
    """The 19 Nov blow-up: YM, RTY, BTC, AUDJPY all SHORT = 4x the same risk-off bet. Only 2 may be open."""
    b = PaperBroker(Journal(":memory:"), LIVE_CAPS)
    assert b.open("YM=F", "SHORT", 100, 101, 99, 98, risk_pct=10)
    assert b.open("RTY=F", "SHORT", 100, 101, 99, 98, risk_pct=10)
    for s in ("BTC-USD", "AUDJPY=X", "NQ=F"):
        assert b.can_open(s, None, "SHORT")[0] is False
        assert b.open(s, "SHORT", 100, 101, 99, 98, risk_pct=10) is None
        assert "move together" in b.last_reject and "sell" in b.last_reject
    assert b.open("NQ=F", "LONG", 100, 99, 101, 102, risk_pct=10)        # opposite way is a different bet
    assert b.open("EURGBP=X", "SHORT", 100, 101, 99, 98, risk_pct=5)     # uncorrelated short still fine


def test_usd_and_yen_groups_use_currency_direction():
    b = PaperBroker(Journal(":memory:"), LIVE_CAPS)
    assert b.open("EURUSD=X", "SHORT", 100, 101, 99, 98, risk_pct=5)     # long USD
    assert b.open("USDCAD=X", "LONG", 100, 99, 101, 102, risk_pct=5)     # long USD
    assert b.can_open("USDCHF=X", None, "LONG")[0] is False             # 3rd long-USD bet
    assert b.can_open("GBPUSD=X", None, "SHORT")[0] is False
    assert "US dollar" in b.can_open("GBPUSD=X", None, "SHORT")[1]
    assert b.can_open("GBPUSD=X", None, "LONG")[0]                      # short USD is the other way


def test_same_direction_total_cap_45pct():
    b = PaperBroker(Journal(":memory:"), LIVE_CAPS)
    assert b.open("EURGBP=X", "SHORT", 100, 101, 99, 98, risk_pct=35)["risk_pct"] == 35
    t = b.open("GC=F", "SHORT", 100, 101, 99, 98, risk_pct=35)          # only 10% short room left
    assert t and abs(t["risk_pct"] - 10) < 0.1 and "same-direction" in t["risk_reason"]
    assert b.open("CL=F", "SHORT", 100, 101, 99, 98, risk_pct=5) is None
    assert "sell trades already risk 45%" in b.last_reject
    t = b.open("CL=F", "LONG", 100, 99, 101, 102, risk_pct=35)          # longs: limited by the 60% total cap
    assert t and abs(t["risk_pct"] - 15) < 0.1


def test_paper_reset_fresh_baseline_keeps_history():
    import time as _t
    from flowdesk.stats import performance
    j = Journal(":memory:")
    b = PaperBroker(j, dict(LIVE_CAPS, daily_loss_limit_pct=50))
    for s in ("YM=F", "RTY=F"):
        t = b.open(s, "SHORT", 100, 101, 99, 98, risk_pct=35)
        b.close(t["id"], 101, ts=int(_t.time()) - 60)
    assert b.balance < 25 and b.daily_limit_hit()
    rec = b.reset_paper(50, "test")
    assert b.balance == 50 and rec["from_balance"] < 25 and not b.daily_limit_hit() and b.realized_today() == 0
    p = performance(j, 50)
    assert p["trades"] == 2 and p["win_rate"] == 0            # history kept for stats
    assert p["net"] == 0 and p["equity_curve"] == [] and p["reset"]["balance"] == 50 and p["all_time"]["net"] < -25
    t = b.open("EURGBP=X", "LONG", 100, 99, 101, 102, risk_pct=7)
    b.close(t["id"], 101)
    p = performance(j, 50)
    assert p["equity_curve"][0] == {"time": rec["ts"], "value": 50} and p["equity_curve"][-1]["value"] > 50 and p["net"] > 0
