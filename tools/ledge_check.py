"""Backtest of the LVN ledge model (research/tiktok_strategies.md #8) per symbol, same code/simulator/costs/quality gate
and the SAME time split as the learning loop: replay window = last 1500 bars; train = everything before its midpoint,
validation = next 25%, test = newest 25%. Correlated instrument passed in for SMT where ledge.PEERS has one.
Run:  python tools/ledge_check.py [--snap DIR] [--tf 15m]   (DIR holds <SYMBOL>.pkl candle snapshots; default = live Yahoo)"""
import argparse, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pandas as pd
from flowdesk import learning as L, strategies as S, instruments, ledge
from flowdesk.config import get_config
from flowdesk.data import get_provider

NAMES = ["lvn_ledge", "lvn_ledge_open"]


def main(snap: str | None = None, tf: str = "15m", names=NAMES) -> dict:
    cfg = get_config(); L._CFG["c"] = cfg
    syms = [instruments.normalize(w["symbol"]) for w in cfg["watchlist"]]

    def load(s):
        if snap:
            p = Path(snap) / (f"{s}.pkl" if tf == "15m" else f"{s}_{tf}.pkl")
            return pd.read_pickle(p) if p.exists() else None
        try:
            return get_provider().candles(s, tf)
        except Exception:
            return None
    frames = {s: load(s) for s in syms}
    res = {n: {} for n in names}
    for sym in syms:
        df = frames[sym]
        if df is None or len(df) < 400:
            continue
        d = S.indicators(df, frames.get(ledge.PEERS.get(sym)))
        ts = [int(t.timestamp()) for t in d.index]
        x = {"df": df, "R": S.rows(d), "ts": ts, "raw": {}}
        # 15m: the learning loop's split (replay = last 1500 bars). Other timeframes: whole history (as video_native_check)
        t0, t1 = (ts[max(300, len(ts) - 1500)] if tf == "15m" else ts[220]), ts[-1]
        a, b = t0 + (t1 - t0) * 0.5, t0 + (t1 - t0) * 0.75
        for n in names:
            par = dict(S.DEFAULT_PARAMS, **S.STRATEGIES[n]["params"])
            tr = L.simulate_strategy(sym, n, x, par)
            seg = {"train": [t for t in tr if t["t"] < a], "val": [t for t in tr if a <= t["t"] < b], "test": [t for t in tr if t["t"] >= b]}
            res[n][sym] = {k: L.summarize(v) for k, v in seg.items()}
            res[n][sym]["heldout"] = L.summarize(seg["val"] + seg["test"])
            res[n][sym]["_trades"] = seg
    out = {}
    for n in names:
        allseg = {k: sum((res[n][s]["_trades"][k] for s in res[n]), []) for k in ("train", "val", "test")}
        out[n] = {"ALL": {k: L.summarize(v) for k, v in allseg.items()},
                  "symbols": {s: {k: v for k, v in r.items() if k != "_trades"} for s, r in res[n].items()}}
        out[n]["ALL"]["heldout"] = L.summarize(allseg["val"] + allseg["test"])
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--snap"); ap.add_argument("--tf", default="15m")
    a = ap.parse_args()
    print(json.dumps(main(a.snap, a.tf), indent=1))
