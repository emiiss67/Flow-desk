"""Run the news-reaction walk-forward test (see flowdesk/newsbt.py). Usage:
    python tools/news_backtest.py DATA_DIR OUT_JSON
DATA_DIR holds ff.csv (Forex Factory history) and <PAIR>.pkl 1m bars (UTC) built from HistData."""
from __future__ import annotations
import itertools, json, sys, time
from pathlib import Path
import numpy as np
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from flowdesk.newsbt import INSTR, SEGMENTS, Params, load_events, windows, run, summary  # noqa: E402

data, out = Path(sys.argv[1]), Path(sys.argv[2])
ev = load_events(str(data / "ff.csv"))
ev = ev[(ev.ts >= SEGMENTS["learn"][0]) & (ev.ts < SEGMENTS["test"][1])]
seg = lambda df, s: df[(df.ts >= SEGMENTS[s][0]) & (df.ts < SEGMENTS[s][1])]
W = {s: windows(pd.read_pickle(data / f"{s}.pkl"), ev.ts) for s in INSTR}

# stock-index direction per event group, learned on the learn segment only: sign of mean(sign(z) x 15-min move)
signs = {}
for s in ("SPXUSD", "NSXUSD"):
    signs[s] = {}
    le = seg(ev, "learn")
    for g, gg in le.groupby("group"):
        mv = []
        for e in gg.itertuples():
            w = W[s].get(e.ts)
            if w is None or abs(e.z) < 0.5:
                continue
            m, o, h, l, c = w
            pre, after = c[m < 0][-1], c[m <= 15][-1]
            mv.append(np.sign(e.z) * (after - pre))
        signs[s][g] = int(np.sign(np.mean(mv))) if len(mv) >= 15 and abs(np.mean(mv)) > 0 else 0

GRID = {"follow": [Params("follow", d, h, z, wide=wd) for d, h, z, wd in itertools.product([1, 2, 3, 5], [15, 30, 60], [0.5, 1.0, 1.5, 2.0], [False, True])],
        "fade": [Params("fade", d, h, spike=k) for d, h, k in itertools.product([1, 2, 3, 5], [15, 30, 60], [2.0, 3.0, 5.0, 8.0])]}


def evaluate(p, segname):
    trades = []
    for s in INSTR:
        trades += run(seg(ev, segname), W[s], p, s, signs.get(s))
    return trades


# raw reaction check: is the surprise direction right in minute 0-1, and after the entry delay?
react = {}
for s in INSTR:
    us = INSTR[s][2]
    rows = []
    for e in ev.itertuples():
        w = W[s].get(e.ts)
        sg = us or signs.get(s, {}).get(e.group, 0)
        if w is None or abs(e.z) < 1 or not sg:
            continue
        m, o, h, l, c = w
        p0 = c[m < 0][-1]
        at = lambda k: o[np.searchsorted(m, k)] if np.searchsorted(m, k) < len(m) else np.nan
        d = np.sign(e.z) * sg
        rows.append([d * (at(1) - p0), d * (at(32) - at(2)), d * (at(65) - at(5))])
    a = np.array(rows)
    a = a[~np.isnan(a).any(1)]
    sp = INSTR[s][1]
    react[INSTR[s][0]] = {"n": int(len(a)), "right_first_minute_pct": round(100 * float((a[:, 0] > 0).mean()), 1),
                          "right_2_to_32min_pct": round(100 * float((a[:, 1] > 0).mean()), 1),
                          "drift_2_to_32min_spreads": round(float(a[:, 1].mean()) / sp, 2),
                          "right_5_to_65min_pct": round(100 * float((a[:, 2] > 0).mean()), 1),
                          "drift_5_to_65min_spreads": round(float(a[:, 2].mean()) / sp, 2)}
res = {"generated": int(time.time()), "segments": SEGMENTS, "events": {k: int(len(seg(ev, k))) for k in SEGMENTS},
       "event_types": ev.Event.value_counts().to_dict(), "index_signs_learned": signs, "reaction": react, "modes": {}}
for mode, grid in GRID.items():
    rows = []
    for p in grid:
        tl = evaluate(p, "learn")
        sm = summary([t["r"] for t in tl])
        rows.append((p, sm))
    ok = [r for r in rows if r[1]["n"] >= 60]
    best = max(ok, key=lambda r: r[1]["exp_r"]) if ok else None
    pos_learn = sum(1 for r in ok if r[1]["exp_r"] > 0)
    entry = {"grid_size": len(grid), "learn_configs_positive": pos_learn, "learn_configs_eligible": len(ok)}
    if best:
        p = best[0]
        tv, tt = evaluate(p, "validate"), evaluate(p, "test")
        sv, st = summary([t["r"] for t in tv]), summary([t["r"] for t in tt])
        by = {}
        for s in INSTR:
            by[INSTR[s][0]] = summary([t["r"] for t in tt if t["sym"] == s])
        byev = {}
        for e in sorted({t["event"] for t in tt}):
            byev[e] = summary([t["r"] for t in tt if t["event"] == e])
        # robustness (information only, not used for choosing): share of all grid configs positive on the test segment
        test_pos = sum(1 for q in grid if (summary([t["r"] for t in evaluate(q, "test")])["exp_r"] or -1) > 0)
        g = Params(**dict(p.__dict__, cost=0.0))
        gross = {k: summary([t["r"] for t in evaluate(g, k)]) for k in SEGMENTS}
        entry.update(params=p.__dict__, gross_no_costs=gross, learn=best[1], validate=sv, test=st, test_by_symbol=by, test_by_event=byev,
                     test_configs_positive=test_pos,
                     passed=bool(sv["n"] >= 30 and sv["exp_r"] > 0 and st["n"] >= 30 and st["exp_r"] > 0.05 and (st["t"] or 0) > 2))
    res["modes"][mode] = entry
    print(mode, json.dumps({k: v for k, v in entry.items() if k in ("params", "learn", "validate", "test", "passed", "learn_configs_positive", "test_configs_positive")}), flush=True)
out.write_text(json.dumps(res, indent=1, default=str))
