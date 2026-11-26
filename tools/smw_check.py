"""Research check for the 8-ATR session-momentum variant (video 17): frozen snapshot, same code path as the learning loop.
usage: python tools/smw_check.py frozen.pkl [out.json]   - also runs it intraday-only (max hold 28 bars) and session_mom for comparison."""
import functools, json, pickle, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from flowdesk import learning as L
from flowdesk.config import get_config
import tools.strategy_eval as E

L._CFG["c"] = get_config()
data = pickle.load(open(sys.argv[1], "rb"))


def f(z):
    return f"n={z['n']:4d} win={z['win_rate'] or 0:5.1f}% exp={z['exp_r'] or 0:+.3f}R"


res, orig = {}, L.simulate_strategy
for label, name, mh in (("session_mom_wide (24h max hold)", "session_mom_wide", 96),
                        ("session_mom_wide intraday-only (28 bars, flat before 16:45 ET)", "session_mom_wide", 28),
                        ("session_mom (note #6: first-candle stop, 1R + 1-ATR trail)", "session_mom", 96)):
    L.simulate_strategy = functools.partial(orig, max_hold=mh) if mh != 96 else orig
    o, per = E.run(data, name)
    L.simulate_strategy = orig
    res[label] = {"all": o, "per": per}
    print(label)
    print("  TRAIN", f(o["train"]), "| VAL", f(o["val"]), "| TEST", f(o["test"]), "| HELD-OUT", f(o["heldout"]), "| on:", o["symbols_on"])
    for s in ("NQ=F", "ES=F", "YM=F"):
        z = per.get(s)
        if z:
            print("  ", s, "TRAIN", f(z["train"]), "| VAL", f(z["val"]), "| TEST", f(z["test"]))
if len(sys.argv) > 2:
    json.dump(res, open(sys.argv[2], "w"), indent=1)
