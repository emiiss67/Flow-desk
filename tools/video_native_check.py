"""Native-timeframe check of the video strategies on 5-minute bars (the videos use 5m/1m charts; the live bot scans 15m).

Same signal code, same simulator, same costs as the learning loop; 50/25/25 time split per symbol.
Run:  python tools/video_native_check.py  [> research/tiktok_native_5m.json]"""
import json, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from flowdesk import learning as L, strategies as S, instruments
from flowdesk.config import get_config
from flowdesk.data import get_provider

NAMES = ["orb15", "fcr_fvg", "session_mom"]


def main(tf: str = "5m") -> dict:
    cfg = get_config(); L._CFG["c"] = cfg
    out = {n: {"train": [], "val": [], "test": []} for n in NAMES}
    for w in cfg["watchlist"]:
        sym = instruments.normalize(w["symbol"])
        try:
            df = get_provider().candles(sym, tf)
        except Exception as e:
            print("skip", sym, e, file=sys.stderr); continue
        d = S.indicators(df)
        ts = [int(t.timestamp()) for t in d.index]
        x = {"df": df, "R": S.rows(d), "ts": ts, "raw": {}}
        t0, t1 = ts[220], ts[-1]
        a, b = t0 + (t1 - t0) * 0.5, t0 + (t1 - t0) * 0.75
        for n in NAMES:
            par = dict(S.DEFAULT_PARAMS, **S.STRATEGIES[n]["params"])
            for t in L.simulate_strategy(sym, n, x, par):
                out[n]["train" if t["t"] < a else "val" if t["t"] < b else "test"].append(t)
    res = {n: {k: L.summarize(v) for k, v in segs.items()} for n, segs in out.items()}
    for n in res:
        allt = sum((out[n][k] for k in out[n]), [])
        res[n]["all"] = L.summarize(allt)
    return res


if __name__ == "__main__":
    print(json.dumps(main(), indent=1))
