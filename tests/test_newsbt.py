import numpy as np
import pandas as pd
from flowdesk import newsbt
from flowdesk.newsbt import Params, trade, num, summary


def _win(path):
    m = np.arange(-60, 130)
    c = np.array([path(t) for t in m], float)
    o = np.r_[c[0], c[:-1]]
    return m, o, np.maximum(o, c) + 0.0001, np.minimum(o, c) - 0.0001, c


def test_num_parsing():
    assert num("155K") == 155000 and num("0.3%") == 0.3 and num("7.60M") == 7.6e6 and num("-1.2B") == -1.2e9 and num(None) is None


def test_follow_wins_on_drift_and_costs_hurt():
    drift = _win(lambda t: 1.1 if t < 0 else 1.1 + 0.002 + 0.00005 * t)      # jump up then keep drifting up
    r_free = trade(drift, 0.0, Params("follow", 2, 30, 1.0), 1)
    r_cost = trade(drift, 0.0001, Params("follow", 2, 30, 1.0), 1)
    assert r_free > 0 and r_cost < r_free


def test_fade_needs_a_spike():
    flat = _win(lambda t: 1.1)
    assert trade(flat, 0.0001, Params("fade", 2, 30, spike=3), None) is None


def test_surprise_uses_only_past_releases(tmp_path):
    rows = [{"DateTime": f"2020-{m:02d}-03T00:00:00+03:30", "Currency": "USD", "Impact": "High Impact Expected",
             "Event": "ISM Manufacturing PMI", "Actual": str(50 + (m % 3)), "Forecast": "50", "Previous": "", "Detail": ""}
            for m in range(1, 13)]
    p = tmp_path / "ff.csv"
    pd.DataFrame(rows).to_csv(p, index=False)
    ev = newsbt.load_events(str(p))
    # the first 8 releases have < 6 earlier non-zero surprises to scale against -> first usable one is September
    assert ev.ts.iloc[0].month == 9 and ev.ts.iloc[0].hour == 14        # 10:00 ET in summer = 14:00 UTC (file says 00:00)
    assert ev.ts.iloc[-1].month == 12 and ev.ts.iloc[-1].hour == 15     # winter: 15:00 UTC


def test_summary():
    s = summary([1, -1, 2, -1])
    assert s["n"] == 4 and s["win_rate"] == 50 and s["exp_r"] == 0.25
