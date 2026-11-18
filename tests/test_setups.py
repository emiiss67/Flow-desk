import numpy as np
import pandas as pd

from flowdesk import ict, setups
from flowdesk.orderflow import OHLCVEstimator, FlowSettings


def frame(rows, start="2026-01-06 14:00"):
    idx = pd.date_range(start, periods=len(rows), freq="15min", tz="UTC")
    return pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"], index=idx)


def base_rows(n=60, p=100.0):
    rng = np.random.default_rng(1)
    rows = []
    for _ in range(n):
        o = p; c = p + rng.normal(0, 0.05); rows.append([o, max(o, c) + 0.1, min(o, c) - 0.1, c, 100]); p = c
    return rows, p


def hvn_scenario():
    rows, p = base_rows()
    # impulse up: 4 big green bars on heavy volume
    for _ in range(4):
        rows.append([p, p + 1.05, p - 0.02, p + 1.0, 400]); p += 1.0
    # balance at ~104 (builds a high-volume node)
    for k in range(10):
        c = p + (0.08 if k % 2 else -0.08); rows.append([p, p + 0.15, p - 0.15, c, 260]); p = c
    # second leg up to the extreme
    for _ in range(3):
        rows.append([p, p + 0.7, p - 0.02, p + 0.65, 300]); p += 0.65
    # pullback back to the node
    for _ in range(3):
        rows.append([p, p + 0.05, p - 0.6, p - 0.55, 150]); p -= 0.55
    # absorption at the node: high volume, long lower wick, closes up
    rows.append([p, p + 0.1, p - 0.45, p + 0.06, 420])
    return frame(rows)


def analyze(df):
    ia = ict.analyze(df, 2, 14, now=df.index[-1].to_pydatetime())
    flow = OHLCVEstimator().analyze(df, FlowSettings.from_cfg({"lookback": 20, "profile_bars": 120, "profile_bins": 40}))
    return ia, flow


def test_hvn_absorption_fires_long_with_trend():
    df = hvn_scenario()
    ia, flow = analyze(df)
    found = setups.detect_hvn_absorption(df, ia, flow, "15m")
    assert found and found[0]["side"] == "long" and found[0]["name"] == setups.HVN_NAME
    s = found[0]
    assert s["sl"] < s["level"] < s["entry"] < s["tp1"]          # stop beyond the node, target the prior high
    lv = setups.setup_levels(s, ia["atr"])
    assert lv and lv["rr1"] >= 1.0 and lv["setup"] == setups.HVN_NAME


def test_no_setup_without_impulse():
    rows, _ = base_rows(90)
    df = frame(rows)
    ia, flow = analyze(df)
    assert setups.detect_hvn_absorption(df, ia, flow, "15m") == []


def test_heavy_absorption_sides_and_labels():
    rows, p = base_rows()
    rows.append([p, p + 0.05, p - 0.8, p + 0.02, 500])      # sellers absorbed at the low -> trapped sellers (bullish)
    rows.append([p, p + 0.8, p - 0.05, p - 0.02, 500])      # buyers absorbed at the high -> trapped buyers (bearish)
    df = frame(rows)
    _, flow = analyze(df)
    m = setups.heavy_absorption(flow.bars, 1.5, 10)
    sides = [x["side"] for x in m[-2:]]
    assert sides == ["trapped_sellers", "trapped_buyers"]
    assert all(float(x["value"]) > 0 and x["label"] for x in m)


def test_imbalance_and_hvn_zone_labels():
    df = hvn_scenario()
    ia, flow = analyze(df)
    imb = setups.imbalance_levels(flow.bars, ia["atr"])
    assert imb and all("x | " in z["label"] and z["top"] > z["bottom"] for z in imb)
    hz = setups.hvn_zones(flow.bars, 40)
    assert hz and all(z["label"].endswith("%") and " | " in z["label"] for z in hz)
    assert sum(z["pct"] for z in hz) <= 100.0 + 1e-6


def test_klar_reversal_long_at_imbalance():
    rows, p = base_rows()
    # rally leaves a buy imbalance at ~101-102, then price runs up and comes back
    rows.append([p, p + 1.6, p - 0.02, p + 1.55, 600]); lvl_top = p + 1.55; p += 1.55
    for _ in range(6):
        rows.append([p, p + 0.5, p - 0.02, p + 0.45, 150]); p += 0.45
    for _ in range(5):
        rows.append([p, p + 0.02, p - 0.6, p - 0.55, 150]); p -= 0.55
    # price reaches the imbalance top: two heavy absorption prints (trapped sellers) and a rejection close
    q = lvl_top + 0.1
    rows.append([q, q + 0.05, lvl_top - 0.5, q + 0.02, 520])
    rows.append([q, q + 0.25, lvl_top - 0.45, q + 0.2, 560])
    df = frame(rows, start="2026-01-06 14:15")       # 09:15 NY ... last bar inside the NY open hour
    ia, flow = analyze(df)
    found = setups.detect_key_level_reversal(df, ia, flow, "15m")
    assert found and found[0]["side"] == "long" and found[0]["name"] == setups.KLAR_NAME
    assert found[0]["sl"] < found[0]["entry"]


def test_setup_gets_extra_weight():
    from flowdesk.strategy import score_features
    f = {"setups": [{"name": setups.KLAR_NAME, "side": "short", "text": "x", "ny_open": True}]}
    sc = score_features(f)
    assert sc.short == setups.KLAR_POINTS + setups.NY_OPEN_BONUS and sc.long == 0
