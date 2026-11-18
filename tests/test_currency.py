"""Account currency (EUR): FX conversion of P&L/size and migration of a legacy USD journal."""
import time

import pandas as pd
import pytest

from flowdesk.broker import PaperBroker
from flowdesk.currency import FxConverter, migrate, quote_ccy, fmt_money, stored_ccy
from flowdesk.data import DataUnavailable
from flowdesk.journal import Journal

NOW = int(time.time())


class FakeFX:
    """EURUSD drifts from 1.05 (old) to 1.10 (now); USDJPY 150; GBPUSD 1.25."""
    def __init__(self, fail=False):
        self.fail = fail

    def candles(self, ticker, tf):
        if self.fail:
            raise DataUnavailable("down")
        idx = pd.date_range(end=pd.Timestamp(NOW, unit="s", tz="UTC"), periods=200, freq="1h")
        base = {"EURUSD=X": (1.05, 1.10), "USDJPY=X": (150.0, 150.0), "GBPUSD=X": (1.25, 1.25)}.get(ticker)
        if not base:
            raise DataUnavailable(ticker)
        vals = [base[0] + (base[1] - base[0]) * i / 199 for i in range(200)]
        return pd.DataFrame({"open": vals, "high": vals, "low": vals, "close": vals, "volume": 0.0}, index=idx)


def test_quote_currencies():
    assert quote_ccy("NQ=F") == "USD" and quote_ccy("GC=F") == "USD" and quote_ccy("BTC-USD") == "USD"
    assert quote_ccy("EURJPY=X") == "JPY" and quote_ccy("USDCHF=X") == "CHF" and quote_ccy("^GDAXI") == "EUR"


def test_rates_and_multipliers():
    fx = FxConverter(FakeFX(), Journal(":memory:"))
    assert fx.rate("USD", "EUR") == pytest.approx(1 / 1.10)
    assert fx.rate("EUR", "USD", NOW - 199 * 3600) == pytest.approx(1.05)          # at that time
    assert fx.rate("JPY", "EUR") == pytest.approx(1 / 150 / 1.10)                   # via USD cross
    assert fx.mult("NQ=F", 21000, "EUR") == pytest.approx(1 / 1.10)                 # USD futures -> EUR
    assert fx.mult("EURUSD=X", 1.08, "EUR") == pytest.approx(1 / 1.08)              # pair's own price
    assert fx.mult("EURJPY=X", 165, "EUR") == pytest.approx(1 / 165)
    assert fx.mult("^GDAXI", 24000, "EUR") == 1.0


def test_last_known_rate_fallback():
    j = Journal(":memory:")
    assert FxConverter(FakeFX(), j).rate("USD", "EUR") == pytest.approx(1 / 1.10)
    down = FxConverter(FakeFX(fail=True), j)
    assert down.rate("USD", "EUR") == pytest.approx(1 / 1.10)                       # stored last known
    assert FxConverter(FakeFX(fail=True), Journal(":memory:")).rate("USD", "EUR") is None


def test_eur_sizing_and_pnl():
    """€50 account, NQ (USD): risk 10% = €5 even though P&L is in USD."""
    b = PaperBroker(Journal(":memory:"), {"starting_balance": 50, "account_currency": "EUR", "risk_pct": 10,
                                          "max_leverage": 1000, "spread_bps": {"futures": 0}, "slippage_bps": 0})
    m = 1 / 1.10
    t = b.open("NQ=F", "LONG", 21000, 20990, 21010, 21020, usd_mult=m)
    assert t["risk_usd"] == pytest.approx(5.0, rel=1e-4)
    ev = b.close(t["id"], 20990)
    assert ev["pnl"] == pytest.approx(-5.0, rel=1e-3) and b.balance == pytest.approx(45.0, rel=1e-3)
    assert b.ccy == "EUR" and fmt_money(-5, "EUR") == "-€5.00" and fmt_money(50, "EUR", False) == "€50.00"


def test_migrate_usd_journal_to_eur():
    j = Journal(":memory:")
    b = PaperBroker(j, {"starting_balance": 50, "spread_bps": {"futures": 0}, "slippage_bps": 0, "max_leverage": 1000})
    old = NOW - 199 * 3600                                   # EURUSD 1.05 then
    t = b.open("NQ=F", "LONG", 21000, 20990, 21010, 21020, ts=old)
    b.close(t["id"], 21021, ts=old)                          # +$10.5 (5% risk of $50 = 2.5 per 1pt? computed below)
    usd_pnl = j.q("SELECT pnl_usd FROM trades")[0]["pnl_usd"]
    j.x("INSERT INTO equity(ts,balance,equity) VALUES(?,?,?)", (old + 10, 50 + usd_pnl, 50 + usd_pnl))
    assert stored_ccy(j) == "USD"
    s = migrate(j, FxConverter(FakeFX(), j), "EUR", 50)
    assert s and s["from"] == "USD" and s["to"] == "EUR"
    eur = j.q("SELECT pnl_usd, risk_usd FROM trades")[0]
    assert eur["pnl_usd"] == pytest.approx(usd_pnl / 1.05, rel=1e-3)               # rate at the trade's time
    assert float(j.get("balance")) == pytest.approx(50 + usd_pnl / 1.05, rel=1e-3)   # €50 start + converted P&L
    assert j.q("SELECT balance FROM equity")[0]["balance"] == pytest.approx(50 + usd_pnl / 1.05, rel=1e-3)
    assert j.get("account_currency") == "EUR" and stored_ccy(j) == "EUR"
    assert migrate(j, FxConverter(FakeFX(), j), "EUR", 50) is None                   # idempotent


def test_migrate_waits_without_rates():
    j = Journal(":memory:")
    b = PaperBroker(j, {"starting_balance": 50})
    b.open("NQ=F", "LONG", 21000, 20990, 21010, 21020)
    with pytest.raises(RuntimeError):
        migrate(j, FxConverter(FakeFX(fail=True), j), "EUR", 50)
    assert stored_ccy(j) == "USD"                                                    # untouched


def test_fresh_journal_marked_eur():
    j = Journal(":memory:")
    assert migrate(j, FxConverter(FakeFX(fail=True), j), "EUR", 50) is None
    assert j.get("account_currency") == "EUR"


def test_telegram_replies_in_eur():
    from flowdesk.commands import Commands
    j = Journal(":memory:")
    b = PaperBroker(j, {"starting_balance": 50, "account_currency": "EUR"})

    class P:
        name = "fake"
    c = Commands(j, b, P(), None)
    assert "€50.00" in c.handle("/pnl") and "€50.00" in c.handle("/status")
