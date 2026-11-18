import pytest
from flowdesk.strategy import compute_levels


def test_long_structural_stop_and_liquidity_targets():
    lv = compute_levels("LONG", 100.0, 1.0, sl_candidates=[99.0, 95.0], tp_candidates=[100.5, 101.6, 103.5, 99.0])
    # nearest valid stop: 99.0 - 0.25 buffer = 98.75 (1.25 risk, within 0.6-3 ATR)
    assert lv["sl"] == pytest.approx(98.75)
    assert lv["sl_basis"] == "structure"
    # TP1 = first target >= 1R (101.25) -> 101.6 ; TP2 needs >= max(r1+0.5, 2)R -> 103.5
    assert lv["tp1"] == pytest.approx(101.6)
    assert lv["tp2"] == pytest.approx(103.5)
    assert lv["rr1"] == pytest.approx(1.28, abs=0.01)
    assert lv["tp2"] > lv["tp1"] > lv["entry"] > lv["sl"]


def test_short_levels_mirror():
    lv = compute_levels("SHORT", 100.0, 1.0, sl_candidates=[101.0], tp_candidates=[98.0, 96.0])
    assert lv["sl"] == pytest.approx(101.25)
    assert lv["tp1"] == pytest.approx(98.0)
    assert lv["tp2"] == pytest.approx(96.0)
    assert lv["sl"] > lv["entry"] > lv["tp1"] > lv["tp2"]


def test_atr_fallback_when_stop_too_far_or_close():
    lv = compute_levels("LONG", 100.0, 1.0, sl_candidates=[99.9, 90.0], tp_candidates=[])
    assert lv["sl_basis"] == "ATR"
    assert lv["sl"] == pytest.approx(98.5)
    assert lv["tp1"] == pytest.approx(100 + 1.5 * 1.5)
    assert lv["rr2"] >= 2.5


def test_tp2_always_beyond_tp1():
    lv = compute_levels("SHORT", 50.0, 0.5, sl_candidates=[50.6], tp_candidates=[49.0])
    assert lv["tp2"] < lv["tp1"] < 50.0
