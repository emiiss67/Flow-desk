import json

import numpy as np
import pandas as pd
import pytest

from flowdesk import backtest, learning as L, strategies as S
from flowdesk.data import set_provider


def synth(n=3000, seed=5):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2026-09-01", periods=n, freq="15min", tz="UTC")
    c = 1.1 + np.cumsum(rng.normal(0, 0.0007, n)) + 0.003 * np.sin(np.arange(n) / 40)
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) + rng.uniform(0.0001, 0.0009, n)
    l = np.minimum(o, c) - rng.uniform(0.0001, 0.0009, n)
    return pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "volume": rng.uniform(100, 900, n)}, index=idx)


def test_indicators_and_signals_are_causal():
    """Changing bars after m must not change any indicator, signal or feature at bars < m."""
    df = synth(1500)
    m = 1100
    df2 = df.copy()
    df2.iloc[m:, :4] *= 1.07
    df2.iloc[m:, 4] *= 20
    a, b = S.indicators(df), S.indicators(df2)
    cols = [c for c in a.columns if c != "day"]
    pd.testing.assert_frame_equal(a[cols].iloc[:m], b[cols].iloc[:m])
    Ra, Rb = S.rows(a), S.rows(b)
    for name in S.STRATEGIES:
        sa = [x for x in S.raw_signals(name, Ra) if x[0] < m]
        sb = [x for x in S.raw_signals(name, Rb) if x[0] < m]
        assert sa == sb, name
    for i in range(300, m, 97):
        assert S.features(Ra, i, "LONG", 1.0, 62) == S.features(Rb, i, "LONG", 1.0, 62)


def test_signal_levels_sane():
    R = S.rows(S.indicators(synth(1500)))
    n = 0
    for name in S.STRATEGIES:
        for i, side, raw in S.raw_signals(name, R)[:20]:
            sg = S.signal(name, R, i, None, (side, raw))
            if sg is None:                       # video strategies skip trades whose stop breaks the sanity limits
                assert S.STRATEGIES[name].get("fixed")
                continue
            sgn = 1 if side == "LONG" else -1
            assert sgn * (sg["entry"] - sg["sl"]) > 0 and sgn * (sg["tp2"] - sg["tp1"]) >= 0
            assert 0.39 <= sg["sl_atr"] <= 3.01
            n += 1
    assert n > 0


class FakeProv:
    name = "fake"

    def __init__(self, frames):
        self.frames = frames

    def candles(self, sym, tf):
        return self.frames[sym]


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("FLOWDESK_DATA_DIR", str(tmp_path))
    frames, rng = {}, np.random.default_rng(1)
    syms = ["EURUSD=X", "GBPUSD=X"]
    for k, s in enumerate(syms):
        df = synth(3000, seed=10 + k)
        frames[s] = df
        recs = []
        for i in range(1500, 2990):
            # core trades lose badly in the "late" session in every period; elsewhere a small edge
            hr = df.index[i].hour
            bad = hr >= 17
            lo = {"r": float(-1.0 if bad and rng.random() < .8 else rng.choice([-1.0, 1.5])), "tp1": False, "tp2": False, "exit": 4, "how": "x"}
            lo["tp1"] = lo["r"] > 0
            recs.append({"i": i, "t": int(df.index[i].timestamp()), "long": 70.0, "short": 10.0, "long_o": lo, "short_o": None})
        backtest._path(s, "15m").write_text(json.dumps({"v": backtest.VERSION, "ok": True, "records": recs}))
    set_provider(FakeProv(frames))
    yield syms
    set_provider(None)


def test_cycle_blocks_losers_versions_and_rollback(world):
    syms = [(s, "15m") for s in world]
    r1 = L.run_cycle(syms)
    assert r1["version"] == 1 and L.rules_path().exists()
    assert len(r1["changes"]) <= L.LIMITS["max_new_blocks"] + 3 * len(r1["strategies"])
    assert any(b["strategy"] == "core" and b["feature"] == "session" and b["bucket"] == "late" for b in r1["blocks"])
    # per cycle: at most one parameter change per strategy
    per = {}
    for c in r1["changes"]:
        if c["kind"] == "param":
            per[c["strategy"]] = per.get(c["strategy"], 0) + 1
    assert all(v == 1 for v in per.values())
    # every enabled extra strategy earned it on validation, never on the test segment
    for k, st in r1["strategies"].items():
        if k in S.STRATEGIES and st["enabled"]:
            assert st["stats"]["val"]["exp_r"] > 0 and st["stats"]["val"]["n"] >= L.LIMITS["enable_min_n"]
    ok, why = L.allow(r1, "core", "EURUSD=X", {"session": "late"}, 70)
    assert not ok and "late" in why
    assert L.allow(r1, "core", "EURUSD=X", {"session": "london"}, 70)[0] or r1["symbols"]["EURUSD=X"]["blocked"]
    r2 = L.run_cycle(syms)
    assert r2["version"] == 2
    rb = L.rollback(1)
    assert rb["version"] == 3 and rb["blocks"] == r1["blocks"] and L.load_rules()["version"] == 3
    h = L.history()
    assert [x["version"] for x in h][:3] == [3, 2, 1]


def test_disabled_strategy_and_min_score():
    rules = L.default_rules()
    assert not L.allow(rules, "orb", "EURUSD=X", {})[0]                        # new strategies start OFF
    assert L.allow(rules, "core", "EURUSD=X", {}, 60)[0]
    rules["strategies"]["core"]["params"]["min_score"] = 65
    ok, why = L.allow(rules, "core", "EURUSD=X", {}, 60)
    assert not ok and "65" in why
    rules["symbols"] = {"EURUSD=X": {"blocked": ["core"]}}
    assert not L.allow(rules, "core", "EURUSD=X", {}, 80)[0]
    assert L.allow(rules, "core", "GBPUSD=X", {}, 80)[0]


def test_stats_for_sizing_shape():
    rules = L.default_rules()
    assert L.stats_for(rules, "orb")["status"] == "computing"
    rules["strategies"]["orb"]["stats"] = {"val": {"n": 40, "win_rate": 55.0, "exp_r": 0.12}}
    from flowdesk import sizing
    from flowdesk.config import get_config
    wr = L.stats_for(rules, "orb", "EURUSD=X")
    sz = sizing.choose(wr, get_config())
    assert wr["status"] == "ok" and sz["risk_pct"] > 0
