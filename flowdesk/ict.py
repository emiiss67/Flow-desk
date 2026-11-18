"""ICT (Inner Circle Trader) concepts computed from candles: swings, BOS/CHoCH, FVGs, order blocks,
liquidity pools (prior day / session highs & lows, equal highs/lows), sweeps, premium/discount, OTE, killzones."""
from __future__ import annotations
from datetime import datetime, timezone, time as dtime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

NY = ZoneInfo("America/New_York")
# ICT killzones in New York time
KILLZONES = {"Asia": (dtime(20, 0), dtime(0, 0)), "London": (dtime(2, 0), dtime(5, 0)),
             "New York AM": (dtime(7, 0), dtime(10, 0)), "London Close": (dtime(10, 0), dtime(12, 0))}
SESSIONS = {"Asia": (20, 24), "London": (2, 5), "New York": (7, 10)}  # hours NY time used for session ranges


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    pc = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.rolling(n, min_periods=1).mean()


def swings(df: pd.DataFrame, k: int = 2) -> tuple[list[dict], list[dict]]:
    h, l = df["high"].values, df["low"].values
    highs, lows = [], []
    for i in range(k, len(df) - k):
        if h[i] == max(h[i - k:i + k + 1]) and h[i] > max(np.delete(h[i - k:i + k + 1], k)) - 1e-12:
            highs.append({"i": i, "time": int(df.index[i].timestamp()), "price": float(h[i])})
        if l[i] == min(l[i - k:i + k + 1]) and l[i] < min(np.delete(l[i - k:i + k + 1], k)) + 1e-12:
            lows.append({"i": i, "time": int(df.index[i].timestamp()), "price": float(l[i])})
    return highs, lows


def structure(df: pd.DataFrame, highs: list[dict], lows: list[dict], k: int = 2) -> dict:
    """Walk bars; a swing becomes 'known' k bars after it forms. Close beyond the last known swing = break.
    Break in trend direction = BOS, against it = CHoCH (change of character)."""
    c = df["close"].values
    hi_by_conf = {s["i"] + k: s for s in highs}
    lo_by_conf = {s["i"] + k: s for s in lows}
    last_h = last_l = None
    trend = 0
    events = []
    for i in range(len(df)):
        if i in hi_by_conf:
            last_h = dict(hi_by_conf[i], broken=False)
        if i in lo_by_conf:
            last_l = dict(lo_by_conf[i], broken=False)
        if last_h and not last_h["broken"] and c[i] > last_h["price"]:
            last_h["broken"] = True
            events.append({"type": "BOS" if trend >= 0 else "CHoCH", "dir": "bull", "level": last_h["price"],
                           "i": i, "time": int(df.index[i].timestamp()), "from_time": last_h["time"]})
            trend = 1
        if last_l and not last_l["broken"] and c[i] < last_l["price"]:
            last_l["broken"] = True
            events.append({"type": "BOS" if trend <= 0 else "CHoCH", "dir": "bear", "level": last_l["price"],
                           "i": i, "time": int(df.index[i].timestamp()), "from_time": last_l["time"]})
            trend = -1
    return {"trend": trend, "events": events, "last_high": last_h, "last_low": last_l}


def fair_value_gaps(df: pd.DataFrame, atr_s: pd.Series, lookback: int = 150, min_atr: float = 0.15) -> list[dict]:
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    out = []
    start = max(2, len(df) - lookback)
    for i in range(start, len(df)):
        a = float(atr_s.iloc[i]) or 1e-9
        if l[i] > h[i - 2] and (l[i] - h[i - 2]) >= min_atr * a:       # bullish FVG
            top, bot = float(l[i]), float(h[i - 2])
            later = l[i + 1:] if i + 1 < len(df) else np.array([])
            filled = bool(len(later) and later.min() <= bot)
            touched = bool(len(later) and later.min() <= top)
            out.append({"dir": "bull", "top": top, "bottom": bot, "time": int(df.index[i - 1].timestamp()),
                        "i": i - 1, "filled": filled, "touched": touched})
        if h[i] < l[i - 2] and (l[i - 2] - h[i]) >= min_atr * a:       # bearish FVG
            top, bot = float(l[i - 2]), float(h[i])
            later = h[i + 1:] if i + 1 < len(df) else np.array([])
            filled = bool(len(later) and later.max() >= top)
            touched = bool(len(later) and later.max() >= bot)
            out.append({"dir": "bear", "top": top, "bottom": bot, "time": int(df.index[i - 1].timestamp()),
                        "i": i - 1, "filled": filled, "touched": touched})
    return out


def order_blocks(df: pd.DataFrame, events: list[dict], lookback_bars: int = 12) -> list[dict]:
    """OB = last opposite-colour candle before the displacement that produced a BOS/CHoCH."""
    o, c, h, l = df["open"].values, df["close"].values, df["high"].values, df["low"].values
    obs = []
    for ev in events:
        j = ev["i"]
        rng = range(j - 1, max(-1, j - lookback_bars), -1)
        idx = None
        for t in rng:
            if ev["dir"] == "bull" and c[t] < o[t]:
                idx = t
                break
            if ev["dir"] == "bear" and c[t] > o[t]:
                idx = t
                break
        if idx is None:
            continue
        top, bot = float(h[idx]), float(l[idx])
        after_c = c[j + 1:]
        after_l, after_h = l[j + 1:], h[j + 1:]
        if ev["dir"] == "bull":
            invalid = bool(len(after_c) and after_c.min() < bot)
            mitigated = bool(len(after_l) and after_l.min() <= top)
        else:
            invalid = bool(len(after_c) and after_c.max() > top)
            mitigated = bool(len(after_h) and after_h.max() >= bot)
        obs.append({"dir": ev["dir"], "top": top, "bottom": bot, "time": int(df.index[idx].timestamp()), "i": idx,
                    "from": ev["type"], "invalid": invalid, "mitigated": mitigated})
    # dedupe by candle
    seen, out = set(), []
    for ob in obs:
        if ob["i"] in seen:
            continue
        seen.add(ob["i"])
        out.append(ob)
    return out


def liquidity_levels(df: pd.DataFrame, highs: list[dict], lows: list[dict], atr_now: float) -> list[dict]:
    lv = []
    ny = df.tz_convert(NY) if df.index.tz is not None else df
    days = ny.groupby(ny.index.date)
    dates = sorted(days.groups.keys())
    if len(dates) >= 2:
        prev = ny[ny.index.date == dates[-2]]
        lv.append({"name": "PDH", "price": float(prev["high"].max()), "side": "buy"})
        lv.append({"name": "PDL", "price": float(prev["low"].min()), "side": "sell"})
    hours = ny.index.hour
    for name, (a, b) in SESSIONS.items():
        mask = (hours >= a) & (hours < b)
        sess = ny[mask]
        if sess.empty:
            continue
        # most recent contiguous session block
        last_day = sess.index[-1].date()
        blk = sess[sess.index.date == last_day]
        if len(blk):
            lv.append({"name": f"{name} high", "price": float(blk["high"].max()), "side": "buy"})
            lv.append({"name": f"{name} low", "price": float(blk["low"].min()), "side": "sell"})
    tol = 0.1 * atr_now
    for arr, side, nm in ((highs[-12:], "buy", "Equal highs"), (lows[-12:], "sell", "Equal lows")):
        for a_i in range(len(arr) - 1):
            for b_i in range(a_i + 1, len(arr)):
                if abs(arr[a_i]["price"] - arr[b_i]["price"]) <= tol:
                    lv.append({"name": nm, "price": (arr[a_i]["price"] + arr[b_i]["price"]) / 2, "side": side})
    return lv


def sweeps(df: pd.DataFrame, levels: list[dict], bars: int = 6) -> list[dict]:
    """Wick through a liquidity level and close back inside = liquidity sweep / stop hunt."""
    out = []
    tail = df.iloc[-bars:]
    for lv in levels:
        p = lv["price"]
        for ts, r in tail.iterrows():
            if lv["side"] == "buy" and r["high"] > p and r["close"] < p:
                out.append({"level": lv["name"], "price": p, "dir": "bear", "time": int(ts.timestamp()),
                            "extreme": float(r["high"])})
                break
            if lv["side"] == "sell" and r["low"] < p and r["close"] > p:
                out.append({"level": lv["name"], "price": p, "dir": "bull", "time": int(ts.timestamp()),
                            "extreme": float(r["low"])})
                break
    return out


def dealing_range(df: pd.DataFrame, highs: list[dict], lows: list[dict], bars: int = 60) -> dict:
    tail = df.iloc[-bars:]
    hi, lo = float(tail["high"].max()), float(tail["low"].min())
    close = float(df["close"].iloc[-1])
    pos = (close - lo) / (hi - lo) if hi > lo else 0.5
    zone = "premium" if pos > 0.55 else "discount" if pos < 0.45 else "equilibrium"
    # OTE: 62-79% retracement of the most recent leg
    hi_i = int(tail["high"].values.argmax())
    lo_i = int(tail["low"].values.argmin())
    up_leg = lo_i < hi_i
    rngv = hi - lo
    if up_leg:
        ote = (hi - 0.79 * rngv, hi - 0.62 * rngv)
        in_ote = ote[0] <= close <= ote[1]
        ote_dir = "bull"
    else:
        ote = (lo + 0.62 * rngv, lo + 0.79 * rngv)
        in_ote = ote[0] <= close <= ote[1]
        ote_dir = "bear"
    return {"high": hi, "low": lo, "eq": (hi + lo) / 2, "position": pos, "zone": zone,
            "ote": [float(ote[0]), float(ote[1])], "ote_dir": ote_dir, "in_ote": bool(in_ote)}


def killzone(now: datetime | None = None) -> str | None:
    now = (now or datetime.now(timezone.utc)).astimezone(NY)
    t = now.time()
    if now.weekday() == 5 or (now.weekday() == 6 and t < dtime(18, 0)):
        return None
    for name, (a, b) in KILLZONES.items():
        if a < b and a <= t < b:
            return name
        if a > b and (t >= a or t < b):
            return name
    return None


def analyze(df: pd.DataFrame, k: int = 2, atr_period: int = 14) -> dict:
    a = atr(df, atr_period)
    highs, lows = swings(df, k)
    st = structure(df, highs, lows, k)
    fv = fair_value_gaps(df, a)
    ob = order_blocks(df, st["events"][-30:])
    atr_now = float(a.iloc[-1])
    liq = liquidity_levels(df, highs, lows, atr_now)
    sw = sweeps(df, liq)
    dr = dealing_range(df, highs, lows)
    return {"atr": atr_now, "swing_highs": highs, "swing_lows": lows, "structure": st, "fvgs": fv,
            "order_blocks": ob, "liquidity": liq, "sweeps": sw, "range": dr, "killzone": killzone()}


def session_boxes(df: pd.DataFrame, days: int = 3) -> list[dict]:
    """London / New York killzone boxes (NY time) for the last few days, for chart overlays."""
    if df.empty:
        return []
    ny = df.tz_convert(NY)
    out = []
    dates = sorted(set(ny.index.date))[-days:]
    for d in dates:
        day = ny[ny.index.date == d]
        for name, (a, b) in (("London", (2, 5)), ("New York", (7, 10))):
            blk = day[(day.index.hour >= a) & (day.index.hour < b)]
            if len(blk) < 2:
                continue
            out.append({"name": name, "start": int(blk.index[0].timestamp()), "end": int(blk.index[-1].timestamp()),
                        "high": float(blk["high"].max()), "low": float(blk["low"].min())})
    return out
