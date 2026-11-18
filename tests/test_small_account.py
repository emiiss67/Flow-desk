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
