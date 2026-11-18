import numpy as np
import pandas as pd

from flowdesk.strategy import score_features, decide
from flowdesk.orderflow import OHLCVEstimator, FlowSettings, psych_levels, volume_profile
from flowdesk import ict


def test_bullish_confluence_scores_long():
    f = {"htf_trend": 1, "htf_tf": "1h", "trend": 1,
         "recent_break": {"type": "BOS", "dir": "bull", "level": 1.1},
         "sweeps": [{"dir": "bull", "level": "PDL", "price": 1.09}],
         "surge": {"side": "buy", "pressure": 420, "vol_ratio": 2.6}, "cum_delta": 0.3,
         "in_bull_fvg": "1.09-1.095", "zone": "discount", "range_pos": 0.3}
    s = score_features(f)
    assert s.long > s.short
    assert s.long >= 55
    assert decide(s) == "LONG"


def test_bearish_mirror_scores_short():
    f = {"htf_trend": -1, "htf_tf": "1h", "trend": -1,
         "recent_break": {"type": "CHoCH", "dir": "bear", "level": 1.1},
         "sweeps": [{"dir": "bear", "level": "PDH", "price": 1.12}],
         "surge": {"side": "sell", "pressure": 500, "vol_ratio": 3.0}, "cum_delta": -0.4,
         "at_bear_ob": "1.11-1.115", "zone": "premium", "range_pos": 0.8}
    s = score_features(f)
    assert decide(s) == "SHORT"


def test_mixed_signals_no_trade():
    f = {"htf_trend": 1, "htf_tf": "1h", "trend": -1, "zone": "premium", "range_pos": 0.7}
    s = score_features(f)
    assert decide(s) == "NO TRADE"


def test_event_blackout_blocks():
    f = {"htf_trend": 1, "trend": 1, "recent_break": {"type": "BOS", "dir": "bull", "level": 1},
         "sweeps": [{"dir": "bull", "level": "PDL", "price": 1}], "surge": {"side": "buy", "pressure": 400, "vol_ratio": 3},
         "zone": "discount", "range_pos": 0.2}
    s = score_features(f)
    assert decide(s) == "LONG"
    assert decide(s, blackout={"title": "CPI"}) == "NO TRADE"


def test_score_capped():
    f = {"htf_trend": 1, "trend": 1, "recent_break": {"type": "BOS", "dir": "bull", "level": 1},
         "sweeps": [{"dir": "bull", "level": "PDL", "price": 1}], "surge": {"side": "buy", "pressure": 900, "vol_ratio": 4},
         "cum_delta": 1, "absorption": {"side": "bullish", "vol_ratio": 3}, "in_bull_fvg": "x", "at_bull_ob": "y",
         "zone": "discount", "range_pos": 0.1, "in_ote": True, "ote_dir": "bull", "vp_side": "long", "vp_level": 1,
         "psych_side": "long", "psych_level": 1, "killzone": "London"}
    assert score_features(f).long <= 95


def _df(n=200, seed=0, vol=True):
    rng = np.random.default_rng(seed)
    p = 100 + np.cumsum(rng.normal(0, 0.3, n))
    o = p + rng.normal(0, 0.1, n)
    c = p + rng.normal(0, 0.1, n)
    h = np.maximum(o, c) + rng.random(n) * 0.3
    l = np.minimum(o, c) - rng.random(n) * 0.3
    v = rng.integers(100, 1000, n).astype(float) if vol else np.zeros(n)
    idx = pd.date_range("2026-11-10", periods=n, freq="15min", tz="UTC")
    return pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "volume": v}, index=idx)


def test_orderflow_surge_detection():
    df = _df()
    # inject a big bullish bar with huge volume closing at the high
    i = df.index[-2]
    df.loc[i, ["open", "low"]] = df.loc[i, "close"] - 2.0
    df.loc[i, "high"] = df.loc[i, "close"] + 0.01
    df.loc[i, "volume"] = 20000
    r = OHLCVEstimator().analyze(df, FlowSettings(market_pressure=300, volume_spread=2))
    assert r.estimated
    assert r.bars.loc[i, "surge"] == 1
    assert r.profile["poc"] and r.profile["val"] <= r.profile["poc"] <= r.profile["vah"]


def test_orderflow_no_volume_uses_proxy():
    r = OHLCVEstimator().analyze(_df(vol=False), FlowSettings())
    assert "proxy" in r.volume_source


def test_psych_levels_eurusd():
    lv = psych_levels(1.0974)
    assert 1.1 in [round(x, 4) for x in lv] and 1.095 in [round(x, 4) for x in lv]


def test_fvg_and_structure():
    df = _df(seed=3)
    # bullish displacement making a gap
    i = len(df) - 5
    base = df["high"].iloc[i - 2]
    for k, off in ((i - 1, 1.5), (i, 2.0)):
        ix = df.index[k]
        df.loc[ix, ["open", "low"]] = [base + off - 1.2, base + off - 0.2]
        df.loc[ix, ["close", "high"]] = [base + off + 0.8, base + off + 1.0]
    a = ict.atr(df)
    gaps = ict.fair_value_gaps(df, a)
    assert any(g["dir"] == "bull" for g in gaps)
    hs, ls = ict.swings(df, 2)
    st = ict.structure(df, hs, ls, 2)
    assert st["trend"] in (-1, 0, 1)
    assert all(e["type"] in ("BOS", "CHoCH") for e in st["events"])


def test_killzone_ny():
    from datetime import datetime, timezone
    assert ict.killzone(datetime(2026, 11, 18, 13, 30, tzinfo=timezone.utc)) == "New York AM"   # 08:30 NY
    assert ict.killzone(datetime(2026, 11, 18, 8, 0, tzinfo=timezone.utc)) == "London"          # 03:00 NY
    assert ict.killzone(datetime(2026, 11, 21, 15, 0, tzinfo=timezone.utc)) is None             # Saturday
