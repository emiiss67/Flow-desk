"""$50 paper account: sizing must stay sensible (fractional, capped, never zero/negative trades)."""
import math
import pytest
from flowdesk.journal import Journal
from flowdesk.broker import PaperBroker

CFG50 = {"starting_balance": 50, "risk_pct": 1.0, "max_positions": 4, "daily_loss_limit_pct": 5.0,
         "tp1_close_pct": 50, "trail_atr": 0, "spread_bps": {"forex": 0, "futures": 0, "other": 0},
         "slippage_bps": 0, "max_leverage": 30}
size = PaperBroker.position_size


@pytest.fixture
def b():
    return PaperBroker(Journal(":memory:"), CFG50)


def test_default_config_is_50_usd():
    from flowdesk.config import get_config
    assert get_config()["broker"]["starting_balance"] == 50
    assert PaperBroker(Journal(":memory:"), get_config()["broker"]).balance == 50


def test_eurusd_fractional_units_risk_50_cents(b):
    # 1% of $50 = $0.50 risk; 10-pip stop -> 500 units (0.005 lots)
    t = b.open("EURUSD=X", "LONG", 1.1000, 1.0990, 1.1015, 1.1030)
    assert t["qty"] == pytest.approx(500)
    assert t["risk_usd"] == pytest.approx(0.50)
    ev = b.update(t["id"], high=1.1001, low=1.0985, close=1.0986)
    assert ev[0]["kind"] == "stop loss" and b.balance == pytest.approx(49.50)


def test_futures_fractional_contracts(b):
    # NQ: $0.50 / (25 pts * $20) = 0.001 contracts - fractional (paper/CFD-style)
    t = b.open("NQ=F", "SHORT", 27000, 27025, 26960, 26900)
    assert t["qty"] == pytest.approx(0.001)
    assert t["risk_usd"] == pytest.approx(0.50)


def test_leverage_cap_reduces_size_never_increases():
    # 1-pip stop would need 5,000 units = $5,500 notional > 30x $50 = $1,500 -> capped
    q = size(50, 1.0, 1.1, 1.0999, 1.0, 1.0, max_leverage=30)
    assert q * 1.1 == pytest.approx(1500, rel=1e-4)
    assert q < size(50, 1.0, 1.1, 1.0999, 1.0, 1.0, max_leverage=0)


@pytest.mark.parametrize("args", [
    (0, 1, 1.1, 1.09, 1, 1), (-5, 1, 1.1, 1.09, 1, 1), (50, 0, 1.1, 1.09, 1, 1), (50, 1, 1.1, 1.1, 1, 1),
    (50, 1, 1.1, 1.09, 0, 1), (50, 1, float("nan"), 1.09, 1, 1), (50, 1, 1.1, 1.09, 1, 0), (50, 1, -1, -2, 1, 1)])
def test_invalid_inputs_give_zero(args):
    assert size(*args) == 0.0


def test_min_qty_and_step():
    assert size(50, 1.0, 27000, 26975, 20, 1.0, min_qty=0.01) == 0.0          # 0.001 < min 0.01 -> no trade
    assert size(50, 1.0, 1.1, 1.099, 1, 1, qty_step=100) == pytest.approx(500)
    assert size(50, 1.0, 1.1, 1.0987, 1, 1, qty_step=100) == pytest.approx(300)  # 384.6 -> rounded DOWN to 300


def test_broker_rejects_wrong_side_stop_and_tiny_size(b):
    assert b.open("EURUSD=X", "LONG", 1.1, 1.101, 1.102, 1.103) is None
    assert b.open("EURUSD=X", "SHORT", 1.1, 1.099, 1.098, 1.097) is None
    tiny = PaperBroker(Journal(":memory:"), dict(CFG50, min_qty=0.01))
    assert tiny.open("NQ=F", "LONG", 27000, 26975, 27040, 27100) is None
    assert tiny.open_trades() == []


def test_sizes_always_positive_finite(b):
    for entry, sl in ((1.1, 1.0999), (150.2, 150.1), (3770, 3765), (27000, 26990), (90000, 89500)):
        for pv in (1, 20, 100, 1000):
            q = size(50, 1.0, entry, sl, pv, 1.0, max_leverage=30)
            assert q > 0 and math.isfinite(q)
            assert q * entry * pv <= 50 * 30 * (1 + 1e-6)
            assert q * abs(entry - sl) * pv <= 0.5 + 1e-9


def test_ten_percent_risk_not_cut_at_200x():
    """10% risk on a tight EURUSD stop (6 pips) on $50: notional ~ $9.2k < 200x cap ($10k), so not reduced."""
    from flowdesk.config import get_config
    b = get_config()["broker"]
    assert b["max_leverage"] >= 200 and b["daily_loss_limit_pct"] == 30.0
    q = size(50, 10.0, 1.1, 1.0994, 1.0, 1.0, max_leverage=200)
    assert abs(q * 0.0006 - 5.0) < 0.01          # loses exactly $5 (10%) at the stop
    q30 = size(50, 10.0, 1.1, 1.0994, 1.0, 1.0, max_leverage=30)
    assert q30 < q                                 # the old 30x cap would have cut it
    # NQ-like: 25 point stop, $2/pt micro-style point value -> 0.1 contracts, well inside the cap
    qn = size(50, 10.0, 21000, 20975, 2.0, 1.0, max_leverage=200)
    assert abs(qn * 25 * 2.0 - 5.0) < 0.01


def test_reset_daily_limit():
    import time as _t
    from flowdesk.broker import PaperBroker
    from flowdesk.journal import Journal
    j = Journal(":memory:")
    b = PaperBroker(j, {"starting_balance": 50, "daily_loss_limit_pct": 30, "spread_bps": {"futures": 0}, "slippage_bps": 0, "max_leverage": 1000})
    t = b.open("NQ=F", "LONG", 21000, 20990, 21010, 21020, risk_pct=40)
    b.close(t["id"], 20990, ts=int(_t.time()) - 5)
    assert b.daily_limit_hit() and b.can_open("ES=F")[0] is False
    r = b.reset_daily_limit()
    assert not r["hit"] and not b.daily_limit_hit() and b.can_open("ES=F")[0] and b.daily_loss_pct == 30
