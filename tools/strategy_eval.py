"""Research harness: run fixed-rule strategies through the SAME code path as the nightly learning loop
(learning.simulate_strategy: costs, quality gate, one position per symbol, per-symbol 50/25/25 time split) on a
frozen data snapshot, and print train / validation / test and per-symbol stats.
usage: python tools/strategy_eval.py frozen.pkl name [name ...]   (names: registered strategies or videostrats variants)
       python tools/strategy_eval.py --freeze frozen.pkl            (snapshot the watchlist with learning.load_symbol)"""
import json, pickle, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from flowdesk import learning as L, strategies as S, videostrats as V
from flowdesk.config import get_config


def register(name):
    if name not in S.STRATEGIES:
        fn = V.OTE_VARIANTS.get(name) or V.FUNCS.get(name)
        S.STRATEGIES[name] = {"name": name, "fixed": True, "no_regime": True, "params": {"sl_pad_atr": 0.0, "tp1_r": 1.0, "tp2_r": 2.5}, "desc": name}
        S._VIDEO[name] = fn
        L.NAMES[name] = name


def run(data, name):
    register(name)
    p = dict(S.DEFAULT_PARAMS, **S.STRATEGIES[name].get("params", {}))
    seg = {"train": [], "val": [], "test": []}
    per = {}
    for x in data:
        ts = L.simulate_strategy(x["sym"], name, x, p)
        per[x["sym"]] = {s: L.summarize(L._seg(ts, x["split"], s)) for s in seg}
        for s in seg:
            seg[s] += L._seg(ts, x["split"], s)
    out = {s: L.summarize(v) for s, v in seg.items()}
    out["heldout"] = L.summarize(seg["val"] + seg["test"])
    lim = L.LIMITS                                           # the learning loop's per-symbol switch-on rule
    out["symbols_on"] = [s for s, z in per.items() if z["val"]["n"] >= lim.get("sym_min_val_n", 10) and (z["val"]["exp_r"] or 0) > 0
                         and z["test"]["n"] >= lim.get("sym_min_test_n", 8) and (z["test"]["exp_r"] or 0) > 0]
    return out, per


if __name__ == "__main__":
    L._CFG["c"] = get_config()
    if sys.argv[1] == "--freeze":
        from flowdesk import instruments
        data = [x for x in (L.load_symbol(instruments.normalize(w["symbol"]), w.get("tf", "15m")) for w in L._CFG["c"]["watchlist"]) if x]
        pickle.dump(data, open(sys.argv[2], "wb"))
        print("froze", len(data), "symbols")
        sys.exit(0)
    data = pickle.load(open(sys.argv[1], "rb"))
    res = {}
    for name in sys.argv[2:]:
        o, per = run(data, name)
        res[name] = {"all": o, "per": per}
        f = lambda z: f"n={z['n']:4d} win={z['win_rate'] if z['win_rate'] is not None else 0:5.1f}% exp={z['exp_r'] if z['exp_r'] is not None else 0:+.3f}R"
        print(f"{name:32s} TRAIN {f(o['train'])} | VAL {f(o['val'])} | TEST {f(o['test'])} | on: {','.join(o['symbols_on']) or '-'}", flush=True)
    if len(sys.argv) > 2:
        json.dump(res, open(sys.argv[1] + ".eval.json", "w"))
