"""LVN ledge 3-step model (owner's screenshots of "wicked's trading model"): profile levels, SMT, signal rules, causality,
and the per-symbol switch in the learning loop."""
import numpy as np
import pandas as pd

from flowdesk import ledge, learning as L, strategies as S


def test_profile_finds_ledge_between_nodes_and_single_prints():
    # two balance areas (100.0-100.4 and 101.0-101.4), one fast bar through the gap, one 30-min period only up at 102
    hs, ls, per = [], [], []
    for k in range(20):
        hs.append(100.4); ls.append(100.0); per.append(k // 2)
    hs.append(101.0); ls.append(100.4); per.append(10)                 # thin path 100.4-101.0
    for k in range(20):
        hs.append(101.4); ls.append(101.0); per.append(11 + k // 2)
    hs.append(102.0); ls.append(101.4); per.append(30)                 # single print 101.4-102.0 (one period)
    p = ledge.profile(np.array(hs), np.array(ls), np.ones(len(hs)), np.array(per))
    assert p and any(100.45 < x < 100.95 for x in p["lvns"])            # the ledge between the two nodes
    assert 100.0 <= p["poc"] <= 101.4
    assert any(a >= 101.35 and b <= 102.01 for a, b in p["sp"])         # single print above the upper node


def frame(n=2600, seed=7, vol=True):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2026-09-01", periods=n, freq="15min", tz="UTC")
    c = 100 + np.cumsum(rng.normal(0, 0.08, n)) + 0.6 * np.sin(np.arange(n) / 30)
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) + rng.uniform(0.01, 0.08, n)
    l = np.minimum(o, c) - rng.uniform(0.01, 0.08, n)
    v = rng.uniform(100, 900, n) if vol else np.zeros(n)
    return pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "volume": v}, index=idx)


def test_levels_are_causal_and_tail_matches_full():
    df = frame()
    full = ledge.compute(df)
    assert sum(len(x) for x in full["vp_lvn"]) > 0 and full["tpo_up"].notna().sum() > 1000
    for cut in (1700, 2111, 2600):
        part = ledge.compute(df.iloc[:cut])                            # no future bars -> identical values
        tl = ledge.compute(df.iloc[:cut], tail=8)                      # live mode: only the newest bars
        for col in full.columns:
            assert part[col].tolist() == full[col].iloc[:cut].tolist(), col
            assert tl[col].iloc[-8:].tolist() == full[col].iloc[cut - 8:cut].tolist(), col


def test_forex_without_volume_uses_time_at_price():
    df = frame(vol=False)
    c = ledge.compute(df)
    assert sum(len(x) for x in c["vp_lvn"]) > 0                         # equal weights still give a (TPO) profile


def test_ismt_and_peer_smt_flags():
    idx = pd.date_range("2026-01-05 14:00", periods=8, freq="15min", tz="UTC")
    o = [10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 9.9, 9.92]
    c = [10.0, 10.0, 10.0, 10.0, 10.0, 9.9, 9.92, 10.05]
    hi = [10.1] * 8
    lo = [9.95, 9.95, 9.95, 9.95, 9.95, 9.85, 9.8, 9.88]
    df = pd.DataFrame({"open": o, "high": hi, "low": lo, "close": c, "volume": 1.0}, index=idx)
    f = ledge.smt(df)
    assert bool(f["ismt_bull"].iloc[6])                                 # wick swept 9.85, body low 9.9 held, green
    assert not f["ismt_bull"].iloc[5]
    peer = df.copy()
    peer["low"] = [9.95] * 8                                            # the peer did NOT make a new low
    g = ledge.smt(df, peer)
    assert bool(g["psmt_bull"].iloc[5]) and bool(g["psmt_bull"].iloc[6])
    g2 = ledge.smt(df, df)                                              # same instrument -> never diverges
    assert not g2["psmt_bull"].any()


def row(**k):
    base = {"open": 100.6, "high": 100.7, "low": 100.05, "close": 100.6, "atr": 0.5, "ny_hour": 10.0, "tpo_n": 8, "tpo_up": 0.7,
            "vp_lvn": (100.1,), "vp_sp": ((102.0, 102.4),), "vp_poc": (99.0,), "ismt_bull": True, "ismt_bear": False,
            "psmt_bull": False, "psmt_bear": False}
    base.update(k)
    return base


def R_(last, prev_close=100.8):
    return [row(close=prev_close, ismt_bull=False)] * 6 + [row(close=prev_close, ismt_bull=False), last]


def test_long_needs_bias_lvn_tap_and_smt_targets_single_print():
    R = R_(row())
    side, (stop, tgt) = S._lvn_ledge(R, 7)
    assert side == "LONG" and stop < 100.05 and tgt == 102.0             # stop beyond the sweep, target the single print
    assert S._lvn_ledge(R_(row(tpo_up=0.5)), 7) is None                 # no bias
    assert S._lvn_ledge(R_(row(tpo_up=0.3)), 7) is None                 # bearish bias -> no long off a support ledge
    assert S._lvn_ledge(R_(row(ismt_bull=False)), 7) is None            # no SMT
    assert S._lvn_ledge(R_(row(vp_lvn=())), 7) is None                  # LVN consolidated through / not aligned
    assert S._lvn_ledge(R_(row(close=100.08)), 7) is None               # closed back under the ledge
    assert S._lvn_ledge(R_(row(vp_poc=(100.9,))), 7) is None            # pushes straight into a POC
    assert S._lvn_ledge(R_(row(ny_hour=17.0)), 7) is None               # outside 03:00-16:00 NY
    side, (stop, tgt) = S._lvn_ledge(R_(row(vp_sp=())), 7)              # no single print -> 2R
    assert abs((tgt - 100.6) - 2 * (100.6 - stop)) < 1e-9


def test_short_mirror_and_open_variant():
    s = row(open=99.4, high=99.95, low=99.3, close=99.4, tpo_up=0.3, vp_lvn=(99.9,), vp_sp=((97.6, 98.0),), vp_poc=(101.0,),
            ismt_bull=False, ismt_bear=True)
    R = [dict(s, close=99.2, ismt_bear=False)] * 7 + [s]
    side, (stop, tgt) = S._lvn_ledge(R, 7)
    assert side == "SHORT" and stop > 99.95 and tgt == 98.0
    op = row(ismt_bull=False, ny_hour=9.75, open=100.3)                            # aggressive NY open: no SMT, rejection candle
    assert S._raw_signal("lvn_ledge_open", R_(op), 7)[0] == "LONG"
    assert S._raw_signal("lvn_ledge_open", R_(dict(op, ny_hour=11.0)), 7) is None
    assert S._raw_signal("lvn_ledge_open", R_(dict(op, close=100.25, open=100.6)), 7) is None   # red candle: no rejection


def test_full_trade_plan_and_defaults_off():
    sg = S.signal("lvn_ledge", R_(row()), 7)
    assert sg and sg["side"] == "LONG" and sg["tp1"] == sg["tp2"] == 102.0 and 0.4 <= sg["sl_atr"] <= 3
    r = L.default_rules()
    for k in ("lvn_ledge", "lvn_ledge_open"):
        assert r["strategies"][k]["enabled"] is False and S.STRATEGIES[k]["fixed"] and S.STRATEGIES[k]["per_symbol"]


class Prov:
    name = "fake"

    def __init__(self, frames):
        self.frames = frames

    def candles(self, sym, tf):
        return self.frames[sym]


def test_learning_switches_ledge_on_only_where_val_and_test_are_positive(tmp_path, monkeypatch):
    monkeypatch.setenv("FLOWDESK_DATA_DIR", str(tmp_path))
    from flowdesk.data import set_provider
    syms = ["EURUSD=X", "GBPUSD=X"]
    frames = {s: frame(1800, seed=3 + k, vol=False) for k, s in enumerate(syms)}
    import json
    from flowdesk import backtest
    for s in syms:                                                      # no core replay needed for this test
        backtest._path(s, "15m").write_text(json.dumps({"v": backtest.VERSION, "ok": True, "records": []}))
    set_provider(Prov(frames))

    def fake(sym, name, x, params, max_hold=96):                      # ledge wins on EUR/USD only, every period
        if name != "lvn_ledge":
            return []
        out = []
        for i in range(300, len(x["R"]) - 1, 12):
            r = 1.2 if sym == "EURUSD=X" else -1.0
            out.append({"t": x["ts"][i], "i": i, "strategy": name, "side": "LONG", "r": r, "win": r > 0,
                        "f": {"symbol": sym, "side": "long", "session": "london", "atr_regime": "normal"}})
        return out
    monkeypatch.setattr(L, "simulate_strategy", fake)
    try:
        r = L.run_cycle([(s, "15m") for s in syms])
    finally:
        set_provider(None)
    st = r["strategies"]["lvn_ledge"]
    assert st["enabled"] and st["symbols_on"] == ["EURUSD=X"] and "EUR/USD" in st["reason"]
    assert "lvn_ledge" in r["symbols"]["GBPUSD=X"]["blocked"] and "lvn_ledge" not in r["symbols"]["EURUSD=X"]["blocked"]
    assert L.allow(r, "lvn_ledge", "EURUSD=X", {"session": "london"})[0]
    assert not L.allow(r, "lvn_ledge", "GBPUSD=X", {"session": "london"})[0]
    assert not r["strategies"]["lvn_ledge_open"]["enabled"]
