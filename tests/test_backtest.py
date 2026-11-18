import numpy as np
import pandas as pd

from flowdesk import backtest
from flowdesk.config import get_config


def synth(n=420, seed=3):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2026-01-05", periods=n, freq="15min", tz="UTC")
    c = 1.1 + np.cumsum(rng.normal(0, 0.0006, n)) + 0.002 * np.sin(np.arange(n) / 25)
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) + rng.uniform(0.0001, 0.0008, n)
    l = np.minimum(o, c) - rng.uniform(0.0001, 0.0008, n)
    v = rng.uniform(100, 1000, n)
    return pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "volume": v}, index=idx)


def test_no_lookahead_scores():
    """Mutating bars after index m must not change any evaluation at bars < m."""
    df = synth()
    cfg = dict(get_config()); cfg["strategy"] = dict(cfg["strategy"], lookback_bars=120)
    a = backtest.run(df, "15m", cfg, max_evals=200, max_hold=20)
    m = 360
    df2 = df.copy()
    df2.iloc[m:, :4] = df2.iloc[m:, :4] * 1.05      # wild future change
    df2.iloc[m:, 4] *= 10
    b = backtest.run(df2, "15m", cfg, max_evals=200, max_hold=20)
    ra = {r["i"]: (r["long"], r["short"]) for r in a if r["i"] < m}
    rb = {r["i"]: (r["long"], r["short"]) for r in b if r["i"] < m}
    assert ra and ra == rb
    # outcomes of trades that ended before m are unchanged too
    for i, r in {r["i"]: r for r in a}.items():
        o = r.get("long_o")
        if i < m and o and i + o["exit"] < m:
            assert {x["i"]: x for x in b}[i]["long_o"] == o


def _bars(rows):
    idx = pd.date_range("2026-01-05", periods=len(rows), freq="15min", tz="UTC")
    return pd.DataFrame(rows, columns=["high", "low", "close"], index=idx)


def test_simulate_stop_first():
    # bar touches both SL and TP1 -> conservative: stop
    o = backtest.simulate("LONG", 100, 99, 101.5, 103, _bars([[102, 98.5, 100]]), atr=1, max_hold=5)
    assert o["r"] == -1 and not o["tp1"]


def test_simulate_tp1_then_be():
    o = backtest.simulate("LONG", 100, 99, 101.5, 103, _bars([[101.6, 100.2, 101.4], [101.0, 99.9, 100]]),
                          atr=1, trail_atr=0, max_hold=5)
    assert o["tp1"] and not o["tp2"] and abs(o["r"] - 0.75) < 1e-9   # 50% at +1.5R, rest at breakeven


def test_simulate_tp2_short():
    o = backtest.simulate("SHORT", 100, 101, 98.5, 97, _bars([[100.2, 98.4, 98.6], [98.6, 96.9, 97.1]]),
                          atr=1, trail_atr=0, max_hold=5)
    assert o["tp1"] and o["tp2"] and abs(o["r"] - (0.5 * 1.5 + 0.5 * 3)) < 1e-9


def test_simulate_unresolved_excluded():
    assert backtest.simulate("LONG", 100, 99, 102, 104, _bars([[100.5, 99.5, 100]]), max_hold=10) is None


def test_stats_band_and_overlap():
    recs = [{"i": 0, "long": 60, "short": 20, "long_o": {"r": 1.0, "tp1": True, "tp2": False, "exit": 3}},
            {"i": 1, "long": 62, "short": 20, "long_o": {"r": -1.0, "tp1": False, "tp2": False, "exit": 1}},  # overlaps
            {"i": 5, "long": 58, "short": 10, "long_o": {"r": -1.0, "tp1": False, "tp2": False, "exit": 1}},
            {"i": 9, "long": 90, "short": 10, "long_o": {"r": 2.0, "tp1": True, "tp2": True, "exit": 1}}]   # out of band
    s = backtest.stats(recs, "LONG", 60, band=10)
    assert s["n"] == 2 and s["win_rate"] == 50.0 and s["avg_r"] == 0.0 and s["low_sample"]
