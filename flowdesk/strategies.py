"""Extra rule-based strategies + entry features, all computed CAUSALLY (every value at bar i uses bars <= i only).

Each strategy turns the indicator frame into entry signals at bar close: side, entry = close[i], stop from the
pattern (clamped to 0.4-3 ATR), targets as R multiples (tunable per strategy by the learning loop).
Order flow here is the same OHLCV estimate as the rest of FlowDesk (no exchange tape)."""
from __future__ import annotations
import math

import numpy as np
import pandas as pd

from . import ict

NY = "America/New_York"

STRATEGIES = {
    "silver_bullet": {"name": "ICT Silver Bullet", "desc": "Fair value gap formed inside the 3-4am / 10-11am / 2-3pm New York windows, in the direction of the 50-EMA bias."},
    "orb": {"name": "Session opening-range breakout", "desc": "First close beyond the first 30 minutes' range of London (07:00 UTC) or New York (13:30 UTC), within 2 hours."},
    "asian_sweep": {"name": "Asian range sweep reversal", "desc": "During London (07-10 UTC) price wicks through the Asian session high/low and closes back inside: fade it."},
    "vwap_revert": {"name": "VWAP deviation mean-reversion", "desc": "Price stretched more than 2 standard deviations from the session VWAP turns back with a strong bar."},
    "ema_pullback": {"name": "Trend pullback (EMA + order flow)", "desc": "20 > 50 > 200 EMA trend, price dips to the 20 EMA and closes back with strong estimated buying (or the mirror for shorts)."},
    "break_retest": {"name": "Break & retest of prior-day level", "desc": "Prior-day high/low broken earlier today, retested and held with a strong close."},
    # --- from the owner's TikTok videos (rules in research/tiktok_strategies.md). Fixed rules: never tuned by the learning loop,
    # never switched on by the regime check; on only with a positive out-of-sample edge (validation AND test).
    "orb15": {"name": "15-min opening range breakout (NY)", "video": 2, "fixed": True, "no_regime": True,
              "params": {"sl_pad_atr": 0.0, "tp1_r": 2.0, "tp2_r": 2.0},
              "desc": "New York open 09:30 ET: mark the first 15-minute candle's high/low. First close above the high = long, below the low = short; stop at the opposite end of the range, target 2R."},
    "fcr_fvg": {"name": "First candle rule + FVG retest + engulfing", "video": 5, "fixed": True, "no_regime": True,
                "params": {"sl_pad_atr": 0.0, "tp1_r": 3.0, "tp2_r": 3.0},
                "desc": "First candle after the 09:30 ET open sets the high/low. Price breaks a level leaving a fair value gap, retests the gap, then an engulfing candle closes back the other way: enter at its close, stop at its far end, fixed 3R target."},
    "session_mom": {"name": "Session momentum (first candle vs 12 EMA)", "video": 6, "fixed": True, "no_regime": True,
                    "params": {"sl_pad_atr": 0.0, "tp1_r": 1.0, "tp2_r": 8.0},
                    "desc": "At the 09:30 ET open the first candle closing above the 12 EMA = long, below = short; the winner is left to run with a trailing stop (stop = first candle's far end)."},
    "ote_fib": {"name": "ICT optimal trade entry (70.5% fib)", "video": 7, "fixed": True, "no_regime": True,
                "params": {"sl_pad_atr": 0.0, "tp1_r": 1.0, "tp2_r": 2.5},
                "desc": "Liquidity sweep of a low, displacement breaks structure to a new high; fib from the swing low to that high; first pullback into the 62-79% zone (70.5% sweet spot) = long, stop under the swing low, target the high (mirrored for shorts)."},
}
DEFAULT_PARAMS = {"tp1_r": 1.0, "tp2_r": 2.5, "sl_pad_atr": 0.2, "tp1_frac": 0.5}
GRID = {"tp1_r": [0.7, 1.0, 1.3, 1.6], "tp2_r": [1.6, 2.0, 2.5, 3.0], "sl_pad_atr": [0.1, 0.2, 0.35, 0.5]}   # TP1 close share stays the broker's tp1_close_pct


def indicators(df: pd.DataFrame) -> pd.DataFrame:
    d = pd.DataFrame(index=df.index)
    o, h, l, c = (df[k].astype(float) for k in ("open", "high", "low", "close"))
    v = df["volume"].astype(float).fillna(0)
    d["open"], d["high"], d["low"], d["close"] = o, h, l, c
    d["atr"] = ict.atr(df, 14)
    d["atr_med"] = d["atr"].rolling(200, min_periods=20).median()
    for n in (12, 20, 50, 200):
        d[f"ema{n}"] = c.ewm(span=n, adjust=False).mean()
    rng = (h - l).replace(0, np.nan)
    d["flow"] = ((c - o) / rng).fillna(0)                                     # estimated order-flow pressure -1..1
    utc = df.index.tz_convert("UTC")
    d["hour"] = utc.hour + utc.minute / 60
    ny = df.index.tz_convert(NY)
    d["ny_hour"] = ny.hour + ny.minute / 60
    d["bar_min"] = float(pd.Series(df.index).diff().dt.total_seconds().median() / 60) if len(df) > 2 else 15.0
    d["nyday"] = ny.year * 10000 + ny.month * 100 + ny.day              # New York calendar date as a number
    day = utc.normalize()
    d["day"] = day
    daily = df.groupby(day).agg(high=("high", "max"), low=("low", "min"))
    prev = daily.shift(1)
    d["pdh"] = prev["high"].reindex(day).values
    d["pdl"] = prev["low"].reindex(day).values
    # Asian range 00:00-06:00 UTC, usable from 06:00 (complete)
    asia = df[(utc.hour < 6)].groupby(day[utc.hour < 6]).agg(high=("high", "max"), low=("low", "min"))
    ah, al = asia["high"].reindex(day).values, asia["low"].reindex(day).values
    after = (utc.hour >= 6)
    d["asia_h"] = np.where(after, ah, np.nan)
    d["asia_l"] = np.where(after, al, np.nan)
    # opening ranges: London 07:00-07:30, New York 13:30-14:00 UTC; known once the window closed
    for tag, (a, b) in {"lon": (7.0, 7.5), "ny": (13.5, 14.0)}.items():
        m = (d["hour"] >= a) & (d["hour"] < b)
        g = df[m.values].groupby(day[m.values]).agg(high=("high", "max"), low=("low", "min"))
        live = (d["hour"] >= b) & (d["hour"] < b + 2)
        d[f"or_{tag}_h"] = np.where(live, g["high"].reindex(day).values, np.nan)
        d[f"or_{tag}_l"] = np.where(live, g["low"].reindex(day).values, np.nan)
    # session VWAP (UTC day); forex has no volume -> equal weights
    w = v.where(v > 0, 1.0)
    tp = (h + l + c) / 3
    d["vwap"] = (tp * w).groupby(day).cumsum() / w.groupby(day).cumsum()
    dev = c - d["vwap"]
    d["vz"] = dev / dev.rolling(96, min_periods=30).std()
    # today's running max/min close before this bar (for break & retest)
    d["day_maxc_prev"] = c.groupby(day).cummax().groupby(day).shift(1)
    d["day_minc_prev"] = c.groupby(day).cummin().groupby(day).shift(1)
    d["low5"] = l.rolling(5, min_periods=1).min()
    d["high5"] = h.rolling(5, min_periods=1).max()
    d["low3"] = l.rolling(3, min_periods=1).min()
    d["high3"] = h.rolling(3, min_periods=1).max()
    d["adx1h"] = adx_1h(df)
    return d


def adx_1h(df: pd.DataFrame, n: int = 14) -> pd.Series:
    """Wilder ADX(14) on 1-hour bars built from the frame, mapped back to each bar using only COMPLETED hours
    (an hour's value is attached at its close, so a 15m bar never sees the hour it is part of)."""
    try:
        hb = df[["high", "low", "close"]].astype(float).resample("1h").agg({"high": "max", "low": "min", "close": "last"}).dropna()
        if len(hb) < 3 * n:
            return pd.Series(np.nan, index=df.index)
        h, l, c = hb["high"], hb["low"], hb["close"]
        up, dn = h.diff(), -l.diff()
        pdm = up.where((up > dn) & (up > 0), 0.0)
        mdm = dn.where((dn > up) & (dn > 0), 0.0)
        tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
        a = 1 / n
        atr = tr.ewm(alpha=a, adjust=False).mean()
        pdi = 100 * pdm.ewm(alpha=a, adjust=False).mean() / atr
        mdi = 100 * mdm.ewm(alpha=a, adjust=False).mean() / atr
        dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
        adx = dx.ewm(alpha=a, adjust=False).mean()
        adx.index = adx.index + pd.Timedelta(hours=1)                    # an hour's value is usable only once it closed
        return adx.reindex(df.index, method="ffill")
    except Exception:
        return pd.Series(np.nan, index=df.index)


def trend_of(adx: float | None) -> str:
    if adx is None or not math.isfinite(adx):
        return "unknown"
    return "trend" if adx >= 25 else "range" if adx < 20 else "mixed"


def rows(d: pd.DataFrame) -> list[dict]:
    return d.drop(columns=["day"]).to_dict("records")



# ---------------- TikTok-video strategies (New York open / structure). Causal: bars <= i only. ----------------
def _range_bar(R: list[dict], i: int) -> int | None:
    """Index of today's (New York date) 09:30 ET bar - the 'first candle' - or None."""
    day = R[i]["nyday"]
    for j in range(i, max(i - 100, -1), -1):
        if R[j]["nyday"] != day:
            return None
        if R[j]["ny_hour"] == 9.5:
            return j
    return None


def _orb15(R: list[dict], i: int):
    j0 = _range_bar(R, i)
    if j0 is None:
        return None
    nb = max(1, int(round(15 / (R[i].get("bar_min") or 15))))          # bars in the first 15 minutes (1 on the 15m chart)
    j1 = j0 + nb - 1
    if i <= j1 or R[i]["ny_hour"] >= 16 or R[j1]["nyday"] != R[i]["nyday"]:
        return None
    rh = max(R[k]["high"] for k in range(j0, j1 + 1))
    rl = min(R[k]["low"] for k in range(j0, j1 + 1))
    for k in range(j1 + 1, i + 1):                       # first close beyond the range, either side
        c = R[k]["close"]
        if c > rh or c < rl:
            if k != i:
                return None
            return ("LONG", rl) if c > rh else ("SHORT", rh)
    return None


def _fcr_fvg(R: list[dict], i: int):
    j0 = _range_bar(R, i)
    if j0 is None or i < j0 + 3 or R[i]["ny_hour"] >= 16:
        return None
    rh, rl = R[j0]["high"], R[j0]["low"]
    side = zlo = zhi = None
    k_fvg = None
    retested = False
    for k in range(j0 + 2, i + 1):
        a, m, b = R[k - 2], R[k - 1], R[k]
        if side is None:
            # a fair value gap whose middle candle closes through the first candle's high/low
            if m["close"] < rl and b["high"] < a["low"]:
                side, zlo, zhi, k_fvg = "SHORT", b["high"], a["low"], k
            elif m["close"] > rh and b["low"] > a["high"]:
                side, zlo, zhi, k_fvg = "LONG", a["high"], b["low"], k
            continue
        # waiting for the retest of the gap and then an engulfing candle
        if side == "SHORT":
            if b["close"] > zhi:
                return None                                # gap fully reclaimed: setup dead
            retested = retested or b["high"] >= zlo
            p = R[k - 1]
            engulf = (b["close"] < b["open"] and p["close"] > p["open"] and b["open"] >= p["close"] and b["close"] <= p["open"])
            if retested and engulf:
                return ("SHORT", b["high"]) if k == i else None
        else:
            if b["close"] < zlo:
                return None
            retested = retested or b["low"] <= zhi
            p = R[k - 1]
            engulf = (b["close"] > b["open"] and p["close"] < p["open"] and b["open"] <= p["close"] and b["close"] >= p["open"])
            if retested and engulf:
                return ("LONG", b["low"]) if k == i else None
    return None


def _session_mom(R: list[dict], i: int):
    j0 = _range_bar(R, i)
    if j0 is None or i != j0:
        return None
    r = R[i]
    if r["close"] > r["ema12"]:
        return "LONG", r["low"]
    if r["close"] < r["ema12"]:
        return "SHORT", r["high"]
    return None


def _ote_fib(R: list[dict], i: int, win: int = 40, look: int = 10, disp_atr: float = 0.6, min_rng_atr: float = 1.0):
    """ICT OTE: sweep of a low (high) -> displacement through structure to a new high (low) -> first tap of the 70.5% retracement."""
    if i < win + look + 2:
        return None
    r = R[i]
    atr = r["atr"]
    a0 = i - win
    lows = [R[k]["low"] for k in range(a0, i)]
    highs = [R[k]["high"] for k in range(a0, i)]
    for side in ("LONG", "SHORT"):
        if side == "LONG":
            ext = min(lows); e_idx = a0 + lows.index(ext)                       # the swept swing low
            if e_idx - look < 0 or e_idx > i - 3:
                continue
            if not ext < min(R[k]["low"] for k in range(e_idx - look, e_idx)):   # it took out the prior low (sell-side liquidity)
                continue
            ref = max(R[k]["high"] for k in range(e_idx - look, e_idx))        # structure level to break
            tgt = max(highs[e_idx - a0 + 1:]); t_idx = e_idx + 1 + highs[e_idx - a0 + 1:].index(tgt)
            if tgt <= ref or t_idx >= i:
                continue
            if not any(R[k]["close"] > ref and R[k]["close"] - R[k]["open"] >= disp_atr * atr for k in range(e_idx + 1, t_idx + 1)):
                continue
            rng = tgt - ext
            if rng < min_rng_atr * atr:
                continue
            lvl = tgt - 0.705 * rng
            if any(R[k]["low"] <= lvl for k in range(t_idx + 1, i)):                 # only the first pullback into the zone
                continue
            if r["low"] <= lvl and r["low"] > ext and r["close"] <= tgt - 0.62 * rng and r["close"] > ext:
                return "LONG", (ext, tgt)
        else:
            ext = max(highs); e_idx = a0 + highs.index(ext)
            if e_idx - look < 0 or e_idx > i - 3:
                continue
            if not ext > max(R[k]["high"] for k in range(e_idx - look, e_idx)):
                continue
            ref = min(R[k]["low"] for k in range(e_idx - look, e_idx))
            tgt = min(lows[e_idx - a0 + 1:]); t_idx = e_idx + 1 + lows[e_idx - a0 + 1:].index(tgt)
            if tgt >= ref or t_idx >= i:
                continue
            if not any(R[k]["close"] < ref and R[k]["open"] - R[k]["close"] >= disp_atr * atr for k in range(e_idx + 1, t_idx + 1)):
                continue
            rng = ext - tgt
            if rng < min_rng_atr * atr:
                continue
            lvl = tgt + 0.705 * rng
            if any(R[k]["high"] >= lvl for k in range(t_idx + 1, i)):
                continue
            if r["high"] >= lvl and r["high"] < ext and r["close"] >= tgt + 0.62 * rng and r["close"] < ext:
                return "SHORT", (ext, tgt)
    return None


_VIDEO = {"orb15": _orb15, "fcr_fvg": _fcr_fvg, "session_mom": _session_mom, "ote_fib": _ote_fib}

def _raw_signal(name: str, R: list[dict], i: int):
    """(side, raw stop) at bar i, or None. Uses rows <= i only."""
    if i < 5:
        return None
    r = R[i]
    atr = r["atr"]
    if not atr or not math.isfinite(atr) or atr <= 0:
        return None
    c, o, h, l = r["close"], r["open"], r["high"], r["low"]
    if name in _VIDEO:
        return _VIDEO[name](R, i)
    if name == "silver_bullet":
        nh = r["ny_hour"]
        if not any(a <= nh < a + 1 for a in (3, 10, 14)):
            return None
        p2, p1 = R[i - 2], R[i - 1]
        if l > p2["high"] + 0.1 * atr and c > r["ema50"] and (p1["close"] - p1["open"]) > 0.5 * atr:
            return "LONG", p1["low"]
        if h < p2["low"] - 0.1 * atr and c < r["ema50"] and (p1["open"] - p1["close"]) > 0.5 * atr:
            return "SHORT", p1["high"]
        return None
    if name == "orb":
        pc = R[i - 1]["close"]
        for tag in ("lon", "ny"):
            hh, ll = r[f"or_{tag}_h"], r[f"or_{tag}_l"]
            if not (math.isfinite(hh) and math.isfinite(ll)):
                continue
            width = hh - ll
            if not (0.5 * atr <= width <= 3 * atr):
                continue
            if c > hh and pc <= hh:
                return "LONG", ll
            if c < ll and pc >= ll:
                return "SHORT", hh
        return None
    if name == "asian_sweep":
        if not (7 <= r["hour"] < 10):
            return None
        ah, al = r["asia_h"], r["asia_l"]
        if not (math.isfinite(ah) and math.isfinite(al)):
            return None
        if h > ah and c < ah and c < o:
            return "SHORT", h
        if l < al and c > al and c > o:
            return "LONG", l
        return None
    if name == "vwap_revert":
        if not (7 <= r["hour"] < 20):
            return None
        z0, z1 = R[i - 1]["vz"], r["vz"]
        if not (math.isfinite(z0) and math.isfinite(z1)):
            return None
        if z0 < -2.0 and z1 > z0 and r["flow"] > 0.4:
            return "LONG", r["low3"]
        if z0 > 2.0 and z1 < z0 and r["flow"] < -0.4:
            return "SHORT", r["high3"]
        return None
    if name == "ema_pullback":
        e20, e50, e200 = r["ema20"], r["ema50"], r["ema200"]
        e50_5 = R[i - 5]["ema50"]
        if e20 > e50 > e200 and e50 > e50_5 and l <= e20 < c and r["flow"] > 0.3:
            return "LONG", r["low5"]
        if e20 < e50 < e200 and e50 < e50_5 and h >= e20 > c and r["flow"] < -0.3:
            return "SHORT", r["high5"]
        return None
    if name == "break_retest":
        pdh, pdl = r["pdh"], r["pdl"]
        if not (math.isfinite(pdh) and math.isfinite(pdl)):
            return None
        mx, mn = r["day_maxc_prev"], r["day_minc_prev"]
        if math.isfinite(mx) and mx > pdh and l <= pdh + 0.15 * atr and c > pdh and r["flow"] > 0.2:
            return "LONG", min(l, pdh)
        if math.isfinite(mn) and mn < pdl and h >= pdl - 0.15 * atr and c < pdl and r["flow"] < -0.2:
            return "SHORT", max(h, pdl)
        return None
    raise KeyError(name)


def raw_signals(name: str, R: list[dict], start: int = 210) -> list[tuple[int, str, float]]:
    out = []
    for i in range(start, len(R)):
        s = _raw_signal(name, R, i)
        if s:
            st = s[1][0] if isinstance(s[1], tuple) else s[1]
            if math.isfinite(st):
                out.append((i, s[0], s[1] if isinstance(s[1], tuple) else float(s[1])))
    return out


def signal(name: str, R: list[dict], i: int, params: dict | None = None, raw: tuple[str, float] | None = None) -> dict | None:
    """Full trade plan at bar i (entry = that bar's close)."""
    p = {**DEFAULT_PARAMS, **STRATEGIES.get(name, {}).get("params", {}), **(params or {})}
    s = raw or _raw_signal(name, R, i)
    if not s:
        return None
    side, raw = s
    tgt = None
    if isinstance(raw, tuple):                      # (stop, target price) from a structure strategy
        raw, tgt = raw
    r = R[i]
    atr, entry = float(r["atr"]), float(r["close"])
    sgn = 1 if side == "LONG" else -1
    sl = raw - sgn * p["sl_pad_atr"] * atr
    dist = (entry - sl) * sgn
    if STRATEGIES.get(name, {}).get("fixed"):       # video rules: the stop is where the video puts it - skip, never move it
        if not (0.4 * atr <= dist <= 3.0 * atr):
            return None
        if tgt is not None:
            if (tgt - entry) * sgn < 1.0 * dist:
                return None
            tr = (tgt - entry) * sgn / dist
            return {"strategy": name, "side": side, "entry": entry, "sl": sl, "tp1": tgt, "tp2": tgt, "atr": atr,
                    "sl_atr": dist / atr, "tp1_frac": p["tp1_frac"], "rr": tr}
    else:
        dist = min(max(dist, 0.4 * atr), 3.0 * atr)
        sl = entry - sgn * dist
    return {"strategy": name, "side": side, "entry": entry, "sl": sl, "tp1": entry + sgn * p["tp1_r"] * dist,
            "tp2": entry + sgn * max(p["tp2_r"], p["tp1_r"]) * dist, "atr": atr, "sl_atr": dist / atr,
            "tp1_frac": p["tp1_frac"], "rr": max(p["tp2_r"], p["tp1_r"])}


# ---------------- entry features (shared by backtest + live trades) ----------------
def session(hour: float) -> str:
    return "asia" if hour < 7 else "london" if hour < 12 else "newyork" if hour < 17 else "late"


def killzone_of(ny_hour: float) -> str:
    return "london_kz" if 2 <= ny_hour < 5 else "ny_kz" if 7 <= ny_hour < 10 else "none"


def features(R: list[dict], i: int, side: str, sl_atr: float | None = None, score: float | None = None) -> dict:
    r = R[i]
    atr = float(r["atr"]) or 1e-12
    up = r["close"] > r["ema200"] and r["ema50"] > r["ema200"]
    dn = r["close"] < r["ema200"] and r["ema50"] < r["ema200"]
    al = ("with" if (up and side == "LONG") or (dn and side == "SHORT") else
          "against" if (up and side == "SHORT") or (dn and side == "LONG") else "mixed")
    reg = r["atr"] / r["atr_med"] if r["atr_med"] and math.isfinite(r["atr_med"]) else 1.0
    kd = min(abs(r["close"] - r["pdh"]), abs(r["close"] - r["pdl"])) / atr if math.isfinite(r["pdh"]) and math.isfinite(r["pdl"]) else 9
    f = {"side": side.lower(), "session": session(r["hour"]), "hour": int(r["hour"]), "killzone": killzone_of(r["ny_hour"]),
         "htf_align": al, "atr_regime": "low" if reg < 0.8 else "high" if reg > 1.3 else "normal",
         "key_dist": "at_level" if kd < 0.5 else "near_level" if kd < 1.5 else "far",
         "trend": trend_of(r.get("adx1h"))}
    if sl_atr is not None:
        f["sl_atr"] = "tight" if sl_atr < 0.8 else "normal" if sl_atr < 1.6 else "wide"
    if score is not None:
        f["score"] = f"{int(score // 10 * 10)}s"
    return f


FEATURE_KEYS = ["symbol", "side", "session", "killzone", "htf_align", "atr_regime", "key_dist", "sl_atr", "score"]
FEATURE_LABEL = {"symbol": "on", "side": "direction", "session": "during the", "killzone": "in killzone", "htf_align": "trend alignment",
                 "atr_regime": "volatility", "key_dist": "distance to prior-day level", "sl_atr": "stop size", "score": "confluence score"}
