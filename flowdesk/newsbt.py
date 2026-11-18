"""News-reaction backtest (paper research, not a live strategy unless it passes out-of-sample).

Data (free, downloaded by tools/news_backtest.py, kept out of git):
- calendar: Forex Factory history snapshot on Hugging Face (Ehsanrs2/Forex_Factory_Calendar, 2007 - 2025-04-07) with
  actual / forecast. Its clock times are unreliable (many rows read 00:00, Tehran offsets), so each event's release
  time comes from the official US schedule below (ET), and only the date is taken from the file.
- prices: HistData.com free 1-minute bid bars (EURUSD, GBPUSD, USDJPY, XAUUSD, SPXUSD = S&P 500, NSXUSD = Nasdaq 100),
  stored in New York wall-clock time and converted to UTC.

Method (no lookahead):
- surprise z = (actual - forecast) / median |actual - forecast| of the same event's PREVIOUS releases (>= 6 needed);
  sign flipped for events where higher = worse for USD (unemployment, claims). One event per release time (priority).
- FOLLOW: wait d minutes after the release, enter at the next bar's open in the direction the surprise implies
  (USD up -> EURUSD/GBPUSD/gold down, USDJPY up; stock indices: direction learned on the learn segment only).
  Stop beyond the release-window extreme, target 2R, else exit after H minutes.
- FADE: wait d minutes, enter AGAINST the move since the pre-release price (if it is > k x pre-release 1m range),
  stop beyond the spike extreme, target = back to the pre-release price (capped at 3R), else exit after H minutes.
- costs: normal spread x widening (x6 at minute 0, x4 to 2 min, x2.5 to 5 min, x1.5 to 15 min, x1 after), paid on
  entry and exit, plus slippage of half a (widened) spread on each fill; a stop that gaps fills at the bar open;
  a bar touching stop and target counts as the stop.
- segments by time: learn 2018-2021, validate 2022-2023, test 2024 - 2025-04 (touched once, for the report).
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

import numpy as np
import pandas as pd

# event -> (ET release time, +1 if higher than forecast is USD-positive, priority within the slot (lower first))
EVENTS = {
    "Non-Farm Employment Change": ("08:30", 1, 0), "Core CPI m/m": ("08:30", 1, 1), "CPI m/m": ("08:30", 1, 2),
    "Core PCE Price Index m/m": ("08:30", 1, 3), "Retail Sales m/m": ("08:30", 1, 4), "Core Retail Sales m/m": ("08:30", 1, 5),
    "Advance GDP q/q": ("08:30", 1, 6), "PPI m/m": ("08:30", 1, 7), "Core PPI m/m": ("08:30", 1, 8),
    "Unemployment Claims": ("08:30", -1, 9), "Empire State Manufacturing Index": ("08:30", 1, 10),
    "ADP Non-Farm Employment Change": ("08:15", 1, 0),
    "ISM Manufacturing PMI": ("10:00", 1, 0), "ISM Services PMI": ("10:00", 1, 1), "JOLTS Job Openings": ("10:00", 1, 2),
    "CB Consumer Confidence": ("10:00", 1, 3), "Prelim UoM Consumer Sentiment": ("10:00", 1, 4),
    "Flash Manufacturing PMI": ("09:45", 1, 0), "Flash Services PMI": ("09:45", 1, 1),
    "Federal Funds Rate": ("14:00", 1, 0),
}
GROUP = {"Non-Farm Employment Change": "jobs", "ADP Non-Farm Employment Change": "jobs", "Unemployment Claims": "jobs",
         "JOLTS Job Openings": "jobs", "Core CPI m/m": "inflation", "CPI m/m": "inflation", "Core PCE Price Index m/m": "inflation",
         "PPI m/m": "inflation", "Core PPI m/m": "inflation", "Federal Funds Rate": "fed"}
# instrument -> (FlowDesk symbol, normal spread in price units, sign of the move when USD strengthens; 0 = learn it)
INSTR = {"EURUSD": ("EURUSD=X", 0.00008, -1), "GBPUSD": ("GBPUSD=X", 0.00012, -1), "USDJPY": ("USDJPY=X", 0.010, 1),
         "XAUUSD": ("GC=F", 0.30, -1), "SPXUSD": ("ES=F", 0.50, 0), "NSXUSD": ("NQ=F", 1.50, 0)}
SEGMENTS = {"learn": ("2018-01-01", "2022-01-01"), "validate": ("2022-01-01", "2024-01-01"), "test": ("2024-01-01", "2025-04-08")}


def num(v) -> float | None:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    s = str(v).strip().replace(",", "")
    m = re.match(r"^([<>]?)(-?\d+(?:\.\d+)?)\s*([%KMBT]?)", s)
    if not m:
        return None
    x = float(m.group(2))
    return x * {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}.get(m.group(3), 1)


def load_events(csv_path: str) -> pd.DataFrame:
    d = pd.read_csv(csv_path, dtype=str)
    d = d[(d.Currency == "USD") & d.Event.isin(EVENTS)].copy()
    d["date"] = d.DateTime.str[:10]
    d["a"], d["f"] = d.Actual.map(num), d.Forecast.map(num)
    d = d.dropna(subset=["a", "f"]).drop_duplicates(["date", "Event"])
    d["et"] = d.Event.map(lambda e: EVENTS[e][0])
    d["ts"] = pd.to_datetime(d.date + " " + d.et).dt.tz_localize("America/New_York").dt.tz_convert("UTC")
    d = d.sort_values("ts")
    # surprise scale from previous releases only
    zs = []
    for ev, g in d.groupby("Event", sort=False):
        diffs = (g.a - g.f).to_numpy()
        for i, (idx, dv) in enumerate(zip(g.index, diffs)):
            prev = np.abs(diffs[:i])
            prev = prev[prev > 0]
            sc = float(np.median(prev)) if len(prev) >= 6 else None
            zs.append((idx, dv / sc * EVENTS[ev][1] if sc else None))
    z = dict(zs)
    d["z"] = d.index.map(z)
    d = d.dropna(subset=["z"])
    d["prio"] = d.Event.map(lambda e: EVENTS[e][2])
    d = d.sort_values(["ts", "prio"]).drop_duplicates("ts")      # one event per release time
    d["group"] = d.Event.map(lambda e: GROUP.get(e, "growth"))
    return d[["ts", "Event", "group", "a", "f", "z"]].reset_index(drop=True)


def widen(minute: float) -> float:
    return 6 if minute < 1 else 4 if minute < 2 else 2.5 if minute < 5 else 1.5 if minute < 15 else 1


@dataclass
class Params:
    mode: str = "follow"        # follow | fade
    delay: int = 2              # minutes after the release before entering
    hold: int = 30              # max minutes in the trade
    zmin: float = 1.0           # |surprise z| needed (follow)
    spike: float = 3.0          # fade: move since pre-release must exceed spike x median 1m range before release
    wide: bool = False          # follow: stop 1.5 x the release-window range away instead of just beyond its extreme
    cost: float = 1.0           # cost multiplier (0 = no spread/slippage: shows the raw signal only)


def windows(px: pd.DataFrame, ts_list, pre=60, post=130):
    """1m bars around each release as numpy arrays: (minute offsets, o, h, l, c)."""
    idx = px.index.as_unit("s").asi8 // 60
    o, h, l, c = (px[k].to_numpy() for k in ("o", "h", "l", "c"))
    out = {}
    for ts in ts_list:
        t0 = int(pd.Timestamp(ts).timestamp()) // 60
        a, b = np.searchsorted(idx, t0 - pre), np.searchsorted(idx, t0 + post)
        if b - a < 40:
            continue
        m = idx[a:b] - t0
        if not ((m >= 0) & (m <= 2)).any() or not (m < 0).any():
            continue
        out[ts] = (m, o[a:b], h[a:b], l[a:b], c[a:b])
    return out


def trade(win, spread, p: Params, direction: int | None):
    """One simulated trade on a release window; returns R multiple (after costs) or None if no trade."""
    m, o, h, l, c = win
    pre = m < 0
    if pre.sum() < 15:
        return None
    p0 = c[pre][-1]
    rng = np.median((h - l)[pre][-30:]) or spread
    ent_i = np.searchsorted(m, p.delay)
    if ent_i >= len(m) or m[ent_i] > p.delay + 2:
        return None
    first = (m >= 0) & (m < p.delay)
    if not first.any():
        return None
    hi, lo = h[first].max(), l[first].min()
    entry_raw = o[ent_i]
    move = entry_raw - p0
    if p.mode == "follow":
        side = direction
        if p.wide:
            sl = entry_raw - side * max(1.5 * (hi - lo), 5 * rng)
        else:
            sl = lo - rng if side > 0 else hi + rng
    else:
        if abs(move) < p.spike * rng:
            return None
        side = -1 if move > 0 else 1
        sl = hi + rng if side < 0 else lo - rng
    spread = spread * p.cost
    cost_in = spread * widen(p.delay) * 1.0          # half spread + half-spread slippage, widened
    entry = entry_raw + side * cost_in
    risk = (entry - sl) * side
    if risk <= max(spread, 1e-12):
        return None
    tp = entry + side * 2 * risk if p.mode == "follow" else entry + side * min(abs(entry - p0), 3 * risk)
    if p.mode == "fade" and (tp - entry) * side <= 0:
        return None
    for i in range(ent_i, len(m)):
        if m[i] > p.delay + p.hold:
            break
        w = widen(m[i]) * spread
        if (side > 0 and l[i] <= sl) or (side < 0 and h[i] >= sl):
            fill = (min(sl, o[i]) if side > 0 else max(sl, o[i])) if i > ent_i else sl
            return ((fill - side * w) - entry) * side / risk
        if (side > 0 and h[i] >= tp) or (side < 0 and l[i] <= tp):
            return ((tp - side * w) - entry) * side / risk
        last = i
    else:
        last = len(m) - 1
    fill = c[last] - side * widen(m[last]) * spread
    return (fill - entry) * side / risk


def run(events: pd.DataFrame, wins: dict, p: Params, sym: str, learned_sign: dict | None = None) -> list[dict]:
    _, spread, usd_sign = INSTR[sym]
    out = []
    for e in events.itertuples():
        w = wins.get(e.ts)
        if w is None:
            continue
        d = None
        if p.mode == "follow":
            if abs(e.z) < p.zmin:
                continue
            s = usd_sign or (learned_sign or {}).get(e.group, 0)
            if not s:
                continue
            d = int(np.sign(e.z)) * s
        r = trade(w, spread, p, d)
        if r is not None:
            out.append({"ts": e.ts, "event": e.Event, "sym": sym, "r": float(r)})
    return out


def summary(rs: list[float]) -> dict:
    n = len(rs)
    if not n:
        return {"n": 0, "win_rate": None, "exp_r": None, "t": None, "pf": None}
    a = np.array(rs)
    sd = a.std(ddof=1) if n > 1 else 0
    gw, gl = a[a > 0].sum(), -a[a < 0].sum()
    return {"n": n, "win_rate": round(100 * (a > 0).mean(), 1), "exp_r": round(a.mean(), 3),
            "t": round(a.mean() / (sd / math.sqrt(n)), 2) if sd else None, "pf": round(gw / gl, 2) if gl else None,
            "total_r": round(a.sum(), 1)}
