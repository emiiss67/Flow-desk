"""The four TikTok-video strategies on hand-built candles (15m bars, New York open 09:30 ET = 14:30 UTC in winter)."""
import numpy as np
import pandas as pd

from flowdesk import learning, strategies as S


def build(day_bars, warm=260, p=100.0):
    """warm-up noise ending the evening before 2026-01-06 14:30 UTC, then the given (o,h,l,c) bars from 09:30 ET."""
    rng = np.random.default_rng(3)
    rows = []
    for _ in range(warm):
        o = p + rng.normal(0, 0.12); c = p + rng.normal(0, 0.12)
        rows.append([o, max(o, c) + 0.12, min(o, c) - 0.12, c, 100.0])
    start = pd.Timestamp("2026-01-06 14:30", tz="UTC") - pd.Timedelta(minutes=15 * warm)
    rows += [[o, h, l, c, 100.0] for o, h, l, c in day_bars]
    idx = pd.date_range(start, periods=len(rows), freq="15min", tz="UTC")
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"], index=idx)
    return S.rows(S.indicators(df)), warm


def sigs(name, R, warm):
    return [(i - warm, side) for i, side, _ in S.raw_signals(name, R, start=warm)]


def test_orb15_long_stop_at_range_low_target_2r():
    day = [(100.0, 100.3, 99.8, 100.1), (100.1, 100.2, 100.0, 100.15), (100.15, 100.6, 100.1, 100.5), (100.5, 100.9, 100.4, 100.8)]
    R, w = build(day)
    assert sigs("orb15", R, w) == [(2, "LONG")]                       # first close above the first candle's high, only once
    sg = S.signal("orb15", R, w + 2)
    assert sg["sl"] == 99.8 and abs(sg["tp1"] - (sg["entry"] + 2 * (sg["entry"] - 99.8))) < 1e-9 and sg["tp1"] == sg["tp2"]


def test_orb15_short_and_no_look_ahead():
    day = [(100.0, 100.3, 99.8, 100.0), (100.0, 100.1, 99.5, 99.6), (99.6, 99.7, 99.0, 99.1)]
    R, w = build(day)
    assert sigs("orb15", R, w) == [(1, "SHORT")]
    R2, w = build(day[:2])                                             # same signal with the future bars removed
    assert sigs("orb15", R2, w) == [(1, "SHORT")]


def test_fcr_fvg_short_needs_gap_retest_engulfing():
    day = [(100.0, 100.3, 99.8, 100.0),                                # first candle
           (99.95, 100.0, 99.85, 99.9),                                # gap start (low 99.85)
           (99.9, 99.9, 99.3, 99.4),                                   # displacement closes under the first candle's low
           (99.4, 99.6, 99.2, 99.3),                                   # high 99.6 < 99.85: bearish FVG 99.6-99.85
           (99.4, 99.7, 99.35, 99.65),                                 # retest of the gap
           (99.7, 99.75, 99.3, 99.35)]                                 # bearish engulfing
    R, w = build(day)
    assert sigs("fcr_fvg", R, w) == [(5, "SHORT")]
    assert R[w + 5]["high"] == 99.75
    # no retest -> no trade
    R2, w = build(day[:4] + [(99.4, 99.5, 99.0, 99.1), (99.15, 99.2, 98.8, 98.9)])
    assert sigs("fcr_fvg", R2, w) == []


def test_session_mom_first_candle_vs_12ema():
    R, w = build([(100.0, 100.4, 99.95, 100.3), (100.3, 100.5, 100.2, 100.4)])
    assert sigs("session_mom", R, w) == [(0, "LONG")]                 # closes above the 12 EMA (~100)
    R, w = build([(100.0, 100.05, 99.6, 99.7), (99.7, 99.8, 99.5, 99.6)])
    assert sigs("session_mom", R, w) == [(0, "SHORT")]
    sg = S.signal("session_mom", R, w)
    assert sg["sl"] == 100.05                                          # the first candle's far end


def ote_day():
    d = []
    for _ in range(12):                                                # balance with highs near 100.15, lows near 99.85
        d.append((100.0, 100.15, 99.85, 100.0))
    d += [(100.0, 100.05, 99.5, 99.55), (99.55, 99.6, 98.8, 98.9)]       # sweep of the low
    d += [(98.9, 100.55, 98.85, 100.5)]                                # displacement through the 100.15 high
    d += [(100.5, 101.2, 100.4, 101.1), (101.1, 101.15, 100.7, 100.8)]   # new high 101.2
    d += [(100.8, 100.85, 100.2, 100.25), (100.25, 100.3, 99.9, 99.95)]  # pullback
    d += [(99.95, 100.0, 99.45, 99.6)]                                 # taps the 70.5% level (99.51), closes inside the zone
    return d


def test_ote_fib_long_stop_swing_low_target_the_high():
    R, w = build(ote_day())
    out = sigs("ote_fib", R, w)
    assert out and out[-1] == (len(ote_day()) - 1, "LONG") and len([o for o in out if o[1] == "LONG"]) == 1
    sg = S.signal("ote_fib", R, w + len(ote_day()) - 1)
    assert sg and abs(sg["sl"] - 98.8) < 1e-9 and abs(sg["tp2"] - 101.2) < 1e-9 and sg["tp1"] == sg["tp2"]


def test_ote_fib_mirrored_short():
    flip = [(200 - o, 200 - l, 200 - h, 200 - c) for o, h, l, c in ote_day()]
    R, w = build(flip, p=100.0)
    out = [o for o in sigs("ote_fib", R, w) if o[1] == "SHORT"]
    assert out == [(len(flip) - 1, "SHORT")]


def test_video_strategies_are_off_fixed_and_not_regime_switched():
    r = learning.default_rules()
    for k in ("orb15", "fcr_fvg", "session_mom", "ote_fib"):
        assert r["strategies"][k]["enabled"] is False
        assert S.STRATEGIES[k]["fixed"] and S.STRATEGIES[k]["no_regime"]
    from flowdesk import regime
    rules = dict(r, regime={"computed": 9e12, "strategies": {"orb15": {"state": "on"}}})
    assert regime.switched_on(rules, "orb15") is False
