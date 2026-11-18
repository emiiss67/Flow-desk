"""Named order-flow setups (estimated from OHLCV), modelled on the reference videos.

* HVN Absorption (trend continuation, ATAS/NQ style): an aggressive impulse / structure break sets the trend,
  price pulls back into a high-volume node, sellers (buyers) hit it but price fails to progress (high volume,
  small body / long wick, delta divergence) -> enter with the trend, stop just beyond the node, target the
  impulse extreme. Repeats on later pullbacks to later nodes.
* Key Level Absorption Reversal (ProfitPro style): price reaches a stacked-imbalance level or an HVN zone, a
  cluster of heavy absorption prints there and price rejects -> reversal, stop beyond the level / signal
  candle, target the next opposing key level. Extra weight in the New York open.

All values are estimates from candles (no tick data); nothing here looks at bars after the last one."""
from __future__ import annotations
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

NY = ZoneInfo("America/New_York")
HVN_NAME = "HVN Absorption"
KLAR_NAME = "Key Level Absorption Reversal"
HVN_POINTS, KLAR_POINTS, NY_OPEN_BONUS = 22, 20, 5


def _fmt_vol(v: float) -> str:
    v = float(v)
    if v >= 1e6:
        return f"{v / 1e6:.1f}M"
    if v >= 1e4:
        return f"{v / 1e3:.0f}k"
    if v >= 100:
        return f"{v:.0f}"
    return f"{v:.3g}"


def ny_open(ts) -> bool:
    t = pd.Timestamp(ts).tz_convert(NY) if pd.Timestamp(ts).tzinfo else pd.Timestamp(ts).tz_localize("UTC").tz_convert(NY)
    return t.weekday() < 5 and dtime(9, 30) <= t.time() < dtime(10, 30)


# ---------------- key levels ----------------
def imbalance_levels(bars: pd.DataFrame, atr: float, max_levels: int = 8) -> list[dict]:
    """Stacked-imbalance estimate: strong one-sided bars (big body, outsized volume/range, delta mostly one way).
    Adjacent/overlapping ones merge into a zone. Label 'ratio x | count'."""
    if bars is None or len(bars) < 10 or not atr:
        return []
    d = bars
    rng = (d["high"] - d["low"]).replace(0, np.nan)
    one_sided = (d["body_frac"] >= 0.65) & ((d["vol_ratio"] >= 1.6) | (rng >= 1.6 * atr))
    zones: list[dict] = []
    for i in np.flatnonzero(one_sided.values):
        r = d.iloc[i]
        side = "buy" if r["close"] > r["open"] else "sell"
        eps = 0.1 * max(float(r["vol"]), 1e-12)          # smoothing: a full-body bar reads ~10x, not infinite
        buy, sell = float(r["buy"]) + eps, float(r["sell"]) + eps
        ratio = min(10.0, buy / sell if side == "buy" else sell / buy)
        top, bot = float(max(r["open"], r["close"])), float(min(r["open"], r["close"]))
        z = zones[-1] if zones else None
        if z and z["side"] == side and i - z["last_i"] <= 3 and bot <= z["top"] + 0.25 * atr and top >= z["bottom"] - 0.25 * atr:
            z.update(top=max(z["top"], top), bottom=min(z["bottom"], bot), last_i=i, count=z["count"] + 1,
                     ratio=max(z["ratio"], ratio))
        else:
            zones.append({"side": side, "top": top, "bottom": bot, "i": i, "last_i": i, "count": 1, "ratio": ratio,
                          "time": int(d.index[i].timestamp())})
    # stacked count: number of one-sided bars inside the zone body, a proxy for stacked imbalance rows
    out = []
    closes = d["close"].values
    for z in zones:
        later = closes[z["last_i"] + 1:]
        # a level stays "live" until price closes through it in the opposite direction
        broken = (later < z["bottom"]).any() if z["side"] == "buy" else (later > z["top"]).any()
        if broken:
            continue
        h = z["top"] - z["bottom"]
        if h < 0.15 * atr:                       # keep thin zones visible
            mid = (z["top"] + z["bottom"]) / 2
            z["top"], z["bottom"] = mid + 0.075 * atr, mid - 0.075 * atr
        rows = max(1, int(round((z["top"] - z["bottom"]) / max(atr / 8, 1e-12)))) * z["count"]
        out.append({"side": z["side"], "top": z["top"], "bottom": z["bottom"], "time": z["time"],
                    "ratio": round(min(z["ratio"], 99), 1), "count": rows,
                    "label": f"{min(99, round(z['ratio']))}x | {rows}"})
    return out[-max_levels:]


def hvn_zones(bars: pd.DataFrame, n_bars: int, bins: int = 48, max_zones: int = 4, proxy: bool = False,
              min_pct: float = 8.0) -> list[dict]:
    """Session profile HVN zones (contiguous bins well above average around peaks). Label 'volume | % of session'."""
    if bars is None or len(bars) < 10:
        return []
    s = bars.iloc[-n_bars:]
    lo, hi = float(s["low"].min()), float(s["high"].max())
    if hi <= lo:
        return []
    edges = np.linspace(lo, hi, bins + 1)
    hist = np.zeros(bins)
    for l, h, v in zip(s["low"].values, s["high"].values, s["vol"].values):
        if v <= 0:
            continue
        i0 = max(0, int(np.searchsorted(edges, l, side="right") - 1))
        i1 = min(bins - 1, max(i0, int(np.searchsorted(edges, h, side="left") - 1)))
        hist[i0:i1 + 1] += v / (i1 - i0 + 1)
    tot = hist.sum()
    if tot <= 0:
        return []
    thr = 1.35 * hist.mean()
    zones, i = [], 0
    while i < bins:
        if hist[i] >= thr:
            j = i
            while j + 1 < bins and hist[j + 1] >= thr:
                j += 1
            vol = float(hist[i:j + 1].sum())
            zones.append({"bottom": float(edges[i]), "top": float(edges[j + 1]), "vol": vol, "pct": 100 * vol / tot,
                          "peak": float((edges[int(i + hist[i:j + 1].argmax())] + edges[int(i + hist[i:j + 1].argmax()) + 1]) / 2)})
            i = j + 1
        else:
            i += 1
    zones = sorted([z for z in zones if z["pct"] >= min_pct], key=lambda z: -z["vol"])[:max_zones]
    for z in zones:
        # without real volume (forex/indices on Yahoo) only the share of the session is meaningful
        z["label"] = f"{'est' if proxy else _fmt_vol(z['vol'])} | {z['pct']:.0f}%"
        z["time"] = int(s.index[0].timestamp())
    return sorted(zones, key=lambda z: z["bottom"])


def heavy_absorption(bars: pd.DataFrame, min_ratio: float = 1.5, last: int = 120) -> list[dict]:
    """Heavy absorption markers. side 'trapped_buyers' (buyers absorbed at the highs, bearish, drawn green above
    the candle) or 'trapped_sellers' (sellers absorbed at the lows, bullish, drawn red below). value = estimated
    absorbed volume (bar volume x wick share)."""
    if bars is None or not len(bars):
        return []
    d = bars.iloc[-last:]
    out = []
    rng = (d["high"] - d["low"]).replace(0, np.nan)
    upper = (d["high"] - d[["open", "close"]].max(axis=1)) / rng
    lower = (d[["open", "close"]].min(axis=1) - d["low"]) / rng
    for k, (ts, r) in enumerate(d.iterrows()):
        if r["absorb"] == 0 or r["vol_ratio"] < min_ratio:
            continue
        bull = r["absorb"] > 0
        wick = float(lower.iloc[k] if bull else upper.iloc[k])
        out.append({"time": int(ts.timestamp()), "i": len(bars) - len(d) + k, "side": "trapped_sellers" if bull else "trapped_buyers",
                    "price": float(r["low"] if bull else r["high"]), "value": float(r["vol"]) * max(wick, 0.0),
                    "label": _fmt_vol(float(r["vol"]) * max(wick, 0.0)), "vol_ratio": round(float(r["vol_ratio"]), 1)})
    return out


def bars_per_session(tf: str) -> int:
    return {"1m": 390, "5m": 96, "15m": 40, "30m": 26, "1h": 24, "4h": 30, "1d": 60}.get(tf, 60)


# ---------------- setups ----------------
def detect_hvn_absorption(df: pd.DataFrame, ia: dict, flow, tf: str) -> list[dict]:
    """Returns 0-1 setups (trend continuation)."""
    b = flow.bars
    atr = ia.get("atr") or 0
    if b is None or len(b) < 40 or not atr:
        return []
    n = len(b)
    look = 40
    start = n - look
    seg = b.iloc[start:]
    res = []
    for side in ("long", "short"):
        sgn = 1 if side == "long" else -1
        # (1) trend: aggressive impulse bar(s) and/or a structure break in the trend direction
        rngs = seg["high"] - seg["low"]
        impulse = seg[((seg["close"] - seg["open"]) * sgn > 0) & (seg["body_frac"] >= 0.6) &
                      ((rngs >= 1.4 * atr) | (seg["vol_ratio"] >= 1.8))]
        breaks = [e for e in ia["structure"]["events"] if e["i"] >= start and e["dir"] == ("bull" if side == "long" else "bear")]
        if impulse.empty and not breaks:
            continue
        cands = [e["i"] for e in breaks]
        if not impulse.empty:
            cands.append(int(b.index.get_loc(impulse.index[0])))
        i0 = min(cands)
        leg = b.iloc[max(0, i0 - 3):]
        if side == "long":
            ext_i = int(np.argmax(leg["high"].values)); ext = float(leg["high"].values[ext_i]); origin = float(leg["low"].values[:ext_i + 1].min())
        else:
            ext_i = int(np.argmin(leg["low"].values)); ext = float(leg["low"].values[ext_i]); origin = float(leg["high"].values[:ext_i + 1].max())
        if abs(ext - origin) < 2.0 * atr or ext_i >= len(leg) - 1:
            continue                                     # no real displacement, or no pullback yet
        close = float(b["close"].iloc[-1])
        if (ext - close) * sgn < 0.6 * atr:
            continue                                     # (2) needs a pullback away from the extreme
        # HVNs: composite profile nodes + nodes of the impulse leg itself (re-entries at later nodes)
        prof = flow.profile or {}
        nodes = list(prof.get("hvn", [])) + ([prof["poc"]] if prof.get("poc") else [])
        nodes += [z["peak"] for z in hvn_zones(leg, len(leg), bins=24, max_zones=3, min_pct=0)]
        nodes = [x for x in nodes if (x - origin) * sgn > 0 and (ext - x) * sgn > 0.4 * atr]
        if not nodes:
            continue
        last3 = b.iloc[-3:]
        touch = float(last3["low"].min()) if side == "long" else float(last3["high"].max())
        near = [x for x in nodes if abs(touch - x) <= 0.35 * atr]
        if not near:
            continue
        hvn = max(near) if side == "long" else min(near)
        # (3) absorption at the HVN: high volume, small body / long wick in our favour, or delta divergence
        conf = None
        for k in range(len(last3)):
            r = last3.iloc[k]
            at = abs((r["low"] if side == "long" else r["high"]) - hvn) <= 0.35 * atr
            wick_abs = r["absorb"] == sgn
            div = (r["delta"] * sgn < 0) and ((r["close"] - r["open"]) * sgn >= 0) and r["vol_ratio"] >= 1.2
            if at and r["vol_ratio"] >= 1.2 and (wick_abs or div or r["body_frac"] <= 0.35):
                conf = (k, r, "wick absorption" if wick_abs else "delta divergence" if div else "high volume, no progress")
        if conf is None or (close - hvn) * sgn <= 0:
            continue
        k, r, how = conf
        extreme = float(last3["low"].min() if side == "long" else last3["high"].max())
        sl = min(extreme, hvn - 0.15 * atr) - 0.1 * atr if side == "long" else max(extreme, hvn + 0.15 * atr) + 0.1 * atr
        res.append({"name": HVN_NAME, "side": side, "entry": close, "sl": sl, "tp1": ext,
                    "tp2": ext + sgn * 0.5 * abs(ext - origin), "level": hvn,
                    "text": f"{HVN_NAME}: impulse {'up' if side == 'long' else 'down'} ({abs(ext - origin) / atr:.1f} ATR), pullback into "
                            f"high-volume node {hvn:.6g}, {how} on {float(r['vol_ratio']):.1f}x volume - "
                            f"continuation toward {ext:.6g}"})
    return res[:1] if len(res) < 2 else []          # conflicting -> none


def detect_key_level_reversal(df: pd.DataFrame, ia: dict, flow, tf: str) -> list[dict]:
    b = flow.bars
    atr = ia.get("atr") or 0
    if b is None or len(b) < 40 or not atr:
        return []
    imbs = imbalance_levels(b.iloc[:-1], atr)         # levels must exist before the reaction bars
    hvz = hvn_zones(b.iloc[:-1], bars_per_session(tf), proxy=flow.volume_source.startswith("range"))
    marks = [m for m in heavy_absorption(b, 1.5, 6) if m["i"] >= len(b) - 5]
    close, hi3, lo3 = float(b["close"].iloc[-1]), float(b["high"].iloc[-3:].max()), float(b["low"].iloc[-3:].min())
    res = []
    for side, mside in (("long", "trapped_sellers"), ("short", "trapped_buyers")):
        sgn = 1 if side == "long" else -1
        ms = [m for m in marks if m["side"] == mside]
        if not ms:
            continue
        levels = [("imbalance", z) for z in imbs] + [("HVN", z) for z in hvz]
        best = None
        for kind, z in levels:
            probe = lo3 if side == "long" else hi3
            if not (z["bottom"] - 0.3 * atr <= probe <= z["top"] + 0.3 * atr):
                continue
            cand = (kind, z)
            at_lvl = [m for m in ms if (z["bottom"] - 0.35 * atr <= m["price"] <= z["top"] + 0.35 * atr)]
            cluster = len(at_lvl) >= 2 or any(m["vol_ratio"] >= 2.5 for m in at_lvl)
            if at_lvl and cluster:
                best = (cand, at_lvl)
                break
        if not best:
            continue
        (kind, z), at_lvl = best
        rejected = (close > z["top"] or close > (b["high"].iloc[-1] + b["low"].iloc[-1]) / 2) if side == "long" else \
                   (close < z["bottom"] or close < (b["high"].iloc[-1] + b["low"].iloc[-1]) / 2)
        if not rejected:
            continue
        sl = min(z["bottom"], lo3) - 0.1 * atr if side == "long" else max(z["top"], hi3) + 0.1 * atr
        # target: next opposing key level (imbalance <-> HVN)
        opp = [l for l in imbs + hvz if (l["bottom"] - close if side == "long" else close - l["top"]) > 0.3 * atr]
        opp = sorted(opp, key=lambda l: (l["bottom"] - close) if side == "long" else (close - l["top"]))
        tps = [(l["bottom"] if side == "long" else l["top"]) for l in opp[:2]]
        nyo = ny_open(b.index[-1])
        label = z.get("label", "")
        res.append({"name": KLAR_NAME, "side": side, "entry": close, "sl": sl,
                    "tp1": tps[0] if tps else None, "tp2": tps[1] if len(tps) > 1 else None,
                    "level": (z["top"] + z["bottom"]) / 2, "ny_open": nyo,
                    "text": f"{KLAR_NAME}: {kind} level {z['bottom']:.6g}-{z['top']:.6g} ({label}), {len(at_lvl)} heavy absorption print(s) "
                            f"({'trapped sellers' if side == 'long' else 'trapped buyers'}) and a rejection"
                            + (" - New York open" if nyo else "")})
    return res[:1] if len(res) < 2 else []


def detect(df: pd.DataFrame, ia: dict, flow, tf: str) -> list[dict]:
    out = []
    for fn in (detect_hvn_absorption, detect_key_level_reversal):
        try:
            out += fn(df, ia, flow, tf)
        except Exception:
            pass
    return out


def setup_levels(s: dict, atr: float, cfg: dict | None = None) -> dict | None:
    """Levels for a setup trade: tight stop beyond the zone, setup target; sanity clamps."""
    cfg = cfg or {}
    e, sl = float(s["entry"]), float(s["sl"])
    sgn = 1 if s["side"] == "long" else -1
    risk = (e - sl) * sgn
    if risk <= 0:
        return None
    if risk < 0.3 * atr:
        sl = e - sgn * 0.3 * atr; risk = 0.3 * atr
    if risk > cfg.get("max_sl_atr", 3.0) * atr:
        return None
    tp1 = s.get("tp1")
    if tp1 is None or (tp1 - e) * sgn < 1.0 * risk:
        tp1, b1 = e + sgn * 1.5 * risk, f"{1.5}R (setup target too close)" if tp1 is not None else "1.5R"
    else:
        b1 = "setup target"
    tp2 = s.get("tp2")
    r1 = (tp1 - e) * sgn / risk
    if tp2 is None or (tp2 - e) * sgn / risk < max(r1 + 0.5, 2.0):
        tp2, b2 = e + sgn * max(2.5, r1 + 1) * risk, "R multiple"
    else:
        b2 = "next key level"
    return {"entry": e, "sl": sl, "tp1": tp1, "tp2": tp2, "risk": risk, "rr1": round(r1, 2),
            "rr2": round((tp2 - e) * sgn / risk, 2), "sl_basis": "beyond setup zone", "tp1_basis": b1, "tp2_basis": b2,
            "setup": s["name"]}
