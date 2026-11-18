"""Walk-forward backtest of the live rules -> historical win rate for /check.

For each past bar i the engine sees ONLY bars <= i (a trailing window), exactly like live. The trade is then
simulated on bars > i with the paper-broker rules (SL first if SL and target share a bar, 50% at TP1 then stop to
breakeven, ATR trail, TP2, time stop). Results per bar are cached on disk; stats are filtered at query time by
direction and score band, without overlapping trades (one position per symbol, like the broker)."""
from __future__ import annotations
import json
import logging
import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from . import instruments
from .config import get_config, data_dir
from .data import get_provider, DataUnavailable

log = logging.getLogger("flowdesk.backtest")
VERSION = 1
_lock = threading.Lock()
_running: dict = {}
_pool = ThreadPoolExecutor(max_workers=2)


def simulate(direction: str, entry: float, sl: float, tp1: float, tp2: float, future: pd.DataFrame,
             atr: float = 0.0, tp1_frac: float = 0.5, trail_atr: float = 1.0, max_hold: int = 96) -> dict | None:
    """Outcome of one trade on future bars only. Returns R multiple, tp1/tp2 flags and exit bar offset.
    None if the history ends before the trade resolves (excluded from stats)."""
    entry, sl, tp1, tp2, atr = float(entry), float(sl), float(tp1), float(tp2), float(atr or 0)
    risk = abs(entry - sl)
    if risk <= 0:
        return None
    long = direction == "LONG"
    sgn = 1 if long else -1
    stop, tp1_hit, realized = sl, False, 0.0
    bars = future.iloc[:max_hold]
    for k, (h, l, c) in enumerate(zip(bars["high"].values, bars["low"].values, bars["close"].values)):
        if (l <= stop) if long else (h >= stop):          # stop first (conservative)
            rest = (1 - tp1_frac) if tp1_hit else 1.0
            realized += rest * (stop - entry) * sgn / risk
            return {"r": realized, "tp1": tp1_hit, "tp2": False, "exit": k + 1, "how": "stop" if not tp1_hit else "be/trail"}
        if not tp1_hit and ((h >= tp1) if long else (l <= tp1)):
            tp1_hit = True
            realized += tp1_frac * (tp1 - entry) * sgn / risk
            stop = entry
        if tp1_hit and ((h >= tp2) if long else (l <= tp2)):
            realized += (1 - tp1_frac) * (tp2 - entry) * sgn / risk
            return {"r": realized, "tp1": True, "tp2": True, "exit": k + 1, "how": "tp2"}
        if tp1_hit and atr and trail_atr > 0:
            t = c - sgn * trail_atr * atr
            if (long and t > stop) or (not long and t < stop):
                stop = t
    if len(bars) < max_hold:
        return None                                           # unresolved at the end of history
    c = float(bars["close"].values[-1])
    rest = (1 - tp1_frac) if tp1_hit else 1.0
    realized += rest * (c - entry) * sgn / risk
    return {"r": realized, "tp1": tp1_hit, "tp2": False, "exit": len(bars), "how": "time"}


def run(df: pd.DataFrame, tf: str, cfg: dict | None = None, window: int | None = None, max_evals: int = 1500,
        max_hold: int = 96) -> list[dict]:
    """Evaluate the engine on every bar (walk-forward) and simulate both directions. Pure function of df."""
    from .strategy import analyze_frame, level_candidates, compute_levels
    cfg = cfg or get_config()
    scfg, bcfg = cfg.get("strategy", {}), cfg.get("broker", {})
    window = window or int(scfg.get("lookback_bars", 300))
    n = len(df)
    start = max(window, n - max_evals)
    out = []
    for i in range(start, n - 1):
        hist = df.iloc[i - window + 1:i + 1]                  # bars <= i only
        try:
            ev = analyze_frame(hist, tf, cfg, now=hist.index[-1].to_pydatetime())
        except Exception as e:
            log.debug("eval %s failed: %s", i, e)
            continue
        f, sc, ia, flow = ev["f"], ev["sc"], ev["ia"], ev["flow"]
        rec = {"i": i, "t": int(df.index[i].timestamp()), "long": round(sc.long, 1), "short": round(sc.short, 1)}
        future = df.iloc[i + 1:]
        for side in ("LONG", "SHORT"):
            slc, tpc = level_candidates(side, f, ia, flow)
            lv = compute_levels(side, f["close"], ia["atr"], slc, tpc, scfg)
            o = simulate(side, lv["entry"], lv["sl"], lv["tp1"], lv["tp2"], future, ia["atr"],
                         bcfg.get("tp1_close_pct", 50) / 100, bcfg.get("trail_atr", 1.0), max_hold)
            rec[side.lower() + "_o"] = o and {k: (round(v, 3) if isinstance(v, float) else v) for k, v in o.items()}
        out.append(rec)
    return out


def stats(records: list[dict], direction: str, score: float, band: float = 10.0, min_score: float | None = None) -> dict:
    side = direction.lower()
    lo, hi = score - band, score + band
    if min_score is not None:
        lo = max(lo, min_score)
    other = "short" if side == "long" else "long"
    taken, busy_until = [], -1
    for r in records:
        if r["i"] < busy_until:
            continue                                          # still in the previous trade (no overlap)
        s = r[side]
        o = r.get(side + "_o")
        if o is None or not (lo <= s <= hi) or s <= r[other]:
            continue
        taken.append(o)
        busy_until = r["i"] + o["exit"]
    n = len(taken)
    res = {"direction": direction, "band": [round(lo), round(hi)], "n": n, "low_sample": n < 20}
    if not n:
        return dict(res, win_rate=None, tp2_rate=None, avg_r=None, expectancy_r=None)
    wins = sum(1 for o in taken if o["tp1"])
    rs = [float(o["r"]) for o in taken]
    res.update(win_rate=round(100 * wins / n, 1), tp2_rate=round(100 * sum(o["tp2"] for o in taken) / n, 1),
               avg_r=round(sum(rs) / n, 2), expectancy_r=round(sum(rs) / n, 2),
               stop_rate=round(100 * sum(1 for o in taken if not o["tp1"] and o["r"] < 0) / n, 1))
    return res


# ---------------- cache + async ----------------
def _path(symbol: str, tf: str):
    return data_dir() / f"bt_{symbol.replace('^', '_').replace('=', '_')}_{tf}.json"


def cached(symbol: str, tf: str, max_age: float = 3600) -> dict | None:
    p = _path(symbol, tf)
    if p.exists() and time.time() - p.stat().st_mtime < max_age:
        try:
            d = json.loads(p.read_text())
            if d.get("v") == VERSION:
                return d
        except Exception:
            return None
    return None


def compute(symbol: str, tf: str) -> dict:
    sym = instruments.normalize(symbol)
    t0 = time.time()
    try:
        df = get_provider().candles(sym, tf)
    except DataUnavailable as e:
        return {"v": VERSION, "ok": False, "error": "data unavailable"}
    recs = run(df, tf)
    d = {"v": VERSION, "ok": True, "symbol": sym, "tf": tf, "records": recs, "bars": len(df),
         "from": recs[0]["t"] if recs else None, "to": recs[-1]["t"] if recs else None,
         "computed": int(time.time()), "seconds": round(time.time() - t0, 1)}
    _path(sym, tf).write_text(json.dumps(d))
    return d


def _bg(symbol: str, tf: str) -> None:
    try:
        compute(symbol, tf)
    except Exception as e:
        log.warning("backtest %s %s failed: %s", symbol, tf, e)
    finally:
        with _lock:
            _running.pop((symbol, tf), None)


def winrate(symbol: str, tf: str, direction: str, score: float, mode: str = "sync") -> dict:
    """mode 'sync' computes if needed; 'async' starts a background job and returns status=computing."""
    cfg = get_config().get("strategy", {})
    sym = instruments.normalize(symbol)
    d = cached(sym, tf)
    if d is None:
        if mode == "async":
            with _lock:
                if (sym, tf) not in _running:
                    _running[(sym, tf)] = _pool.submit(_bg, sym, tf)
            return {"status": "computing"}
        d = compute(sym, tf)
    if not d.get("ok"):
        return {"status": "unavailable", "error": "data unavailable"}
    st = stats(d["records"], direction, score, band=10, min_score=None)
    b = get_config().get("broker", {})
    risk_usd = b.get("starting_balance", 50) * b.get("risk_pct", 1.0) / 100
    if st.get("expectancy_r") is not None:
        st["expectancy_usd"] = round(st["expectancy_r"] * risk_usd, 2)
        st["risk_usd"] = risk_usd
    st.update(status="ok", period_from=d["from"], period_to=d["to"], tf=tf, computed=d["computed"],
              method="walk-forward replay of the live rules on Yahoo history (no lookahead); TP1 before SL = win",
              note="Past results on limited free history. Event blackouts and spreads are not replayed.")
    return st
