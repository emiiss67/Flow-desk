import sqlite3
import pytest
from flowdesk.journal import Journal
from flowdesk.broker import PaperBroker
from flowdesk import stake

CFG = {"starting_balance": 10000, "risk_pct": 1.0, "max_positions": 5, "daily_loss_limit_pct": 50.0,
       "tp1_close_pct": 50, "trail_atr": 0, "spread_bps": {"futures": 0, "forex": 0, "commodities": 0},
       "slippage_bps": 0}


def test_stake_persisted_at_entry_futures():
    b = PaperBroker(Journal(":memory:"), CFG)
    t = b.open("NQ=F", "LONG", 20000, 19990, 20015, 20030, usd_mult=0.9)
    # €100 risk (1% of 10k) / (10 pt x pv 20 x 0.9) = 0.5556 contracts; notional = qty x 20000 x 20 x 0.9 ~ €200k = 20x
    assert t["notional_eur"] == pytest.approx(t["qty"] * 20000 * 20 * 0.9, abs=0.01)
    assert t["equity_at_entry"] == pytest.approx(10000)
    assert t["leverage"] == pytest.approx(t["notional_eur"] / 10000, abs=0.01)
    s = stake.of_trade(t)
    assert s["size_unit"] == "contracts" and s["risk_eur"] == pytest.approx(100, abs=0.05)
    assert s["text"].startswith("Risk €100") and "(1%)" in s["text"] and "Notional €" in s["text"] and s["text"].endswith("20x")


def test_stake_forex_lots_and_pnl_pct_of_risk():
    b = PaperBroker(Journal(":memory:"), CFG)
    t = b.open("EURUSD=X", "LONG", 1.1000, 1.0950, 1.1050, 1.1100, usd_mult=1.0)
    s = stake.of_trade(t)
    assert s["size_unit"] == "lots" and s["size"] == pytest.approx(t["qty"] / 100000)
    b.update(t["id"], 1.0940, 1.0940, 1.0940)         # stopped out: -1R = -100% of risk
    c = b.j.trades("closed")[0]
    assert stake.of_trade(c)["pnl_pct_of_risk"] == pytest.approx(-100, abs=0.5)


def test_old_trades_backfilled(tmp_path):
    p = tmp_path / "j.db"
    j = Journal(str(p))
    b = PaperBroker(j, CFG)
    b.open("ES=F", "LONG", 6000, 5990, 6015, 6030)
    j.db.execute("UPDATE trades SET equity_at_entry=NULL, notional_eur=NULL, leverage=NULL")
    j.db.commit()
    t = Journal(str(p)).trades()[0]                       # migration recomputes from qty / pv / fx / risk %
    assert t["notional_eur"] == pytest.approx(t["qty"] * 6000 * 50)
    assert t["leverage"] == pytest.approx(t["notional_eur"] / t["equity_at_entry"])
