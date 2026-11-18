"""Strategy engine: FlowPro-style order-flow estimate + ICT confluence scoring + structural SL/TP levels.

check() is compute-only. It never places trades."""
from __future__ import annotations
import logging
import math
import time
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import ict, instruments, events
from .config import get_config
from .data import get_provider, resample, DataUnavailable, HTF
from .orderflow import FlowSettings, get_orderflow_provider

log = logging.getLogger("flowdesk.strategy")
RULES = {"1m": "1min", "5m": "5min", "15m": "15min", "30m": "30min", "1h": "1h", "4h": "4h", "1d": "1D"}


@dataclass
class Component:
    key: str
    side: str          # "long" | "short" | "both"
    points: float
    text: str
    tag: str


@dataclass
class Score:
    long: float = 0.0
    short: float = 0.0
    components: list = field(default_factory=list)


def score_features(f: dict) -> Score:
    """Pure scoring function. f holds plain numbers/flags extracted from the analysis (see extract_features)."""
    s = Score()

    def add(key, side, pts, text, tag):
        s.components.append(Component(key, side, pts, text, tag))
        if side in ("long", "both"):
            s.long += pts
        if side in ("short", "both"):
            s.short += pts

    if f.get("htf_trend") == 1:
        add("htf", "long", 15, f"Higher timeframe ({f.get('htf_tf')}) structure is bullish", "HTF bias")
    elif f.get("htf_trend") == -1:
        add("htf", "short", 15, f"Higher timeframe ({f.get('htf_tf')}) structure is bearish", "HTF bias")

    tr, ev = f.get("trend", 0), f.get("recent_break")  # recent_break: {"type","dir","level"}
    if ev:
        side = "long" if ev["dir"] == "bull" else "short"
        pts = 15 if (tr == 1 and side == "long") or (tr == -1 and side == "short") else 10
        word = "Break of structure" if ev["type"] == "BOS" else "Change of character"
        add("structure", side, pts, f"{word} ({ev['type']}) {'up' if side == 'long' else 'down'} through "
            f"{fmt(ev['level'])}", ev["type"])
    elif tr:
        add("structure", "long" if tr == 1 else "short", 8,
            f"Market structure on this timeframe is {'bullish' if tr == 1 else 'bearish'}", "Structure")

    for sw in f.get("sweeps", [])[:1]:
        side = "long" if sw["dir"] == "bull" else "short"
        liq = "Sell-side" if side == "long" else "Buy-side"
        add("sweep", side, 15, f"{liq} liquidity at {sw['level']} ({fmt(sw['price'])}) was swept and price closed "
            f"back {'above' if side == 'long' else 'below'} it (stop hunt)", "Liquidity sweep")

    surge = f.get("surge")  # {"side": "buy"/"sell", "pressure", "vol_ratio"}
    if surge:
        side = "long" if surge["side"] == "buy" else "short"
        add("pressure", side, 15, f"Estimated {'buying' if side == 'long' else 'selling'} pressure surge: "
            f"{surge['pressure']}% of normal delta on {surge['vol_ratio']}x volume", "Pressure surge")
    cds = f.get("cum_delta", 0.0)
    if cds > 0.12:
        add("delta", "long", 5, "Estimated cumulative delta is positive (buyers in control)", "Delta +")
    elif cds < -0.12:
        add("delta", "short", 5, "Estimated cumulative delta is negative (sellers in control)", "Delta -")

    ab = f.get("absorption")
    if ab:
        side = "long" if ab["side"] == "bullish" else "short"
        add("absorption", side, 10, f"{'Selling absorbed near the lows' if side == 'long' else 'Buying absorbed near the highs'}"
            f" ({ab['vol_ratio']}x volume, small body, long wick)", "Absorption")

    if f.get("in_bull_fvg"):
        add("fvg", "long", 10, f"Price is reacting inside a bullish fair value gap {f['in_bull_fvg']}", "FVG")
    if f.get("in_bear_fvg"):
        add("fvg", "short", 10, f"Price is reacting inside a bearish fair value gap {f['in_bear_fvg']}", "FVG")
    if f.get("at_bull_ob"):
        add("ob", "long", 10, f"Price is at a bullish order block {f['at_bull_ob']}", "Order block")
    if f.get("at_bear_ob"):
        add("ob", "short", 10, f"Price is at a bearish order block {f['at_bear_ob']}", "Order block")

    zone = f.get("zone")
    if zone == "discount":
        add("pd", "long", 8, f"Price is in the discount half of the range ({f.get('range_pos', 0):.0%})", "Discount")
    elif zone == "premium":
        add("pd", "short", 8, f"Price is in the premium half of the range ({f.get('range_pos', 0):.0%})", "Premium")
    if f.get("in_ote"):
        side = "long" if f.get("ote_dir") == "bull" else "short"
        add("ote", side, 7, "Price is in the optimal trade entry zone (62-79% retracement)", "OTE")

    vp = f.get("vp_side")
    if vp == "long":
        add("vp", "long", 5, f"Holding above a high-volume node / POC at {fmt(f.get('vp_level'))}", "Volume node")
    elif vp == "short":
        add("vp", "short", 5, f"Capped below a high-volume node / POC at {fmt(f.get('vp_level'))}", "Volume node")

    ps = f.get("psych_side")
    if ps:
        add("psych", ps, 3, f"{'Holding above' if ps == 'long' else 'Rejected below'} round number {fmt(f.get('psych_level'))}",
            "Round number")

    if f.get("killzone"):
        add("kz", "both", 5, f"{f['killzone']} killzone is active (higher-probability window)", "Killzone")
    s.long = min(95.0, s.long)
    s.short = min(95.0, s.short)
    return s


def decide(score: Score, min_score: float = 55, min_margin: float = 15, blackout: dict | None = None) -> str:
    if blackout:
        return "NO TRADE"
    best = "LONG" if score.long >= score.short else "SHORT"
    hi, lo = max(score.long, score.short), min(score.long, score.short)
    if hi >= min_score and hi - lo >= min_margin:
        return best
    return "NO TRADE"


def compute_levels(direction: str, entry: float, atr: float, sl_candidates: list[float], tp_candidates: list[float],
                   cfg: dict | None = None) -> dict:
    """Structural stop beyond the nearest invalidation + targets at opposing liquidity, with sanity clamps."""
    cfg = cfg or {}
    buf = cfg.get("sl_buffer_atr", 0.25) * atr
    min_d, max_d = cfg.get("min_sl_atr", 0.6) * atr, cfg.get("max_sl_atr", 3.0) * atr
    min_rr1, rr2 = cfg.get("min_rr_tp1", 1.0), cfg.get("default_rr_tp2", 2.5)
    sgn = 1 if direction == "LONG" else -1
    notes = []
    stops = []
    for c in sl_candidates:
        if c is None or not math.isfinite(c):
            continue
        sl = c - sgn * buf
        d = (entry - sl) * sgn
        if d >= min_d and d <= max_d:
            stops.append((d, sl))
    if stops:
        risk, sl = min(stops)
        sl_basis = "structure"
    else:
        risk = 1.5 * atr
        sl = entry - sgn * risk
        sl_basis = "ATR"
        notes.append("No clean structural stop within limits, using 1.5x ATR stop")
    tps = sorted({t for t in tp_candidates if t is not None and math.isfinite(t) and (t - entry) * sgn > 0},
                 key=lambda t: (t - entry) * sgn)
    tp1 = next((t for t in tps if (t - entry) * sgn >= min_rr1 * risk), None)
    tp1_basis = "liquidity"
    if tp1 is None:
        tp1 = entry + sgn * 1.5 * risk
        tp1_basis = "R multiple"
    r1 = (tp1 - entry) * sgn / risk
    tp2 = next((t for t in tps if (t - entry) * sgn >= max(r1 + 0.5, 2.0) * risk), None)
    tp2_basis = "liquidity"
    if tp2 is None:
        tp2 = entry + sgn * max(rr2, r1 + 1.0) * risk
        tp2_basis = "R multiple"
    return {"entry": entry, "sl": sl, "tp1": tp1, "tp2": tp2, "risk": risk,
            "rr1": round((tp1 - entry) * sgn / risk, 2), "rr2": round((tp2 - entry) * sgn / risk, 2),
            "sl_basis": sl_basis, "tp1_basis": tp1_basis, "tp2_basis": tp2_basis, "notes": notes}


def fmt(x) -> str:
    if x is None:
        return "-"
    x = float(x)
    ax = abs(x)
    d = 5 if ax < 10 else 3 if ax < 200 else 2
    return f"{x:,.{d}f}"


def decimals(price: float) -> int:
    ax = abs(price)
    return 5 if ax < 10 else 3 if ax < 200 else 2


def extract_features(df: pd.DataFrame, ia: dict, flow, htf_trend: int, htf_tf: str) -> dict:
    close = float(df["close"].iloc[-1])
    atr = ia["atr"] or 1e-9
    n = len(df)
    st = ia["structure"]
    recent = [e for e in st["events"] if e["i"] >= n - 12]
    f = {"close": close, "atr": atr, "trend": st["trend"], "htf_trend": htf_trend, "htf_tf": htf_tf,
         "recent_break": recent[-1] if recent else None, "sweeps": sorted(ia["sweeps"], key=lambda s: -s["time"]),
         "zone": ia["range"]["zone"], "range_pos": ia["range"]["position"], "in_ote": ia["range"]["in_ote"],
         "ote_dir": ia["range"]["ote_dir"], "killzone": ia["killzone"]}
    if flow.bars is not None:
        b = flow.bars.iloc[-3:]
        sb = b[b["surge"] != 0]
        if len(sb):
            r = sb.iloc[-1]
            f["surge"] = {"side": "buy" if r["surge"] > 0 else "sell", "pressure": int(r["pressure"]),
                          "vol_ratio": round(float(r["vol_ratio"]), 1)}
        ab = flow.bars.iloc[-5:]
        ab = ab[ab["absorb"] != 0]
        if len(ab):
            r = ab.iloc[-1]
            f["absorption"] = {"side": "bullish" if r["absorb"] > 0 else "bearish", "vol_ratio": round(float(r["vol_ratio"]), 1)}
        f["cum_delta"] = flow.cum_delta_slope
    tol = 0.3 * atr
    lo_recent = float(df["low"].iloc[-3:].min())
    hi_recent = float(df["high"].iloc[-3:].max())
    for g in ia["fvgs"]:
        if g["filled"]:
            continue
        if g["dir"] == "bull" and lo_recent <= g["top"] + tol and close >= g["bottom"]:
            f["in_bull_fvg"] = f"{fmt(g['bottom'])}-{fmt(g['top'])}"
            f["bull_fvg"] = g
        if g["dir"] == "bear" and hi_recent >= g["bottom"] - tol and close <= g["top"]:
            f["in_bear_fvg"] = f"{fmt(g['bottom'])}-{fmt(g['top'])}"
            f["bear_fvg"] = g
    for ob in ia["order_blocks"]:
        if ob["invalid"]:
            continue
        if ob["dir"] == "bull" and lo_recent <= ob["top"] + tol and close >= ob["bottom"]:
            f["at_bull_ob"] = f"{fmt(ob['bottom'])}-{fmt(ob['top'])}"
            f["bull_ob"] = ob
        if ob["dir"] == "bear" and hi_recent >= ob["bottom"] - tol and close <= ob["top"]:
            f["at_bear_ob"] = f"{fmt(ob['bottom'])}-{fmt(ob['top'])}"
            f["bear_ob"] = ob
    prof = flow.profile or {}
    nodes = ([prof["poc"]] if prof.get("poc") else []) + prof.get("hvn", [])
    if nodes:
        below = [x for x in nodes if 0 <= close - x <= 0.6 * atr]
        above = [x for x in nodes if 0 <= x - close <= 0.6 * atr]
        dc = f.get("cum_delta", 0)
        if below and dc >= 0:
            f["vp_side"], f["vp_level"] = "long", max(below)
        elif above and dc <= 0:
            f["vp_side"], f["vp_level"] = "short", min(above)
    for lv in flow.psych_levels:
        if 0 <= close - lv <= 0.3 * atr and lo_recent <= lv + 0.1 * atr:
            f["psych_side"], f["psych_level"] = "long", lv
        elif 0 <= lv - close <= 0.3 * atr and hi_recent >= lv - 0.1 * atr:
            f["psych_side"], f["psych_level"] = "short", lv
    return f


def level_candidates(direction: str, f: dict, ia: dict, flow) -> tuple[list[float], list[float]]:
    close = f["close"]
    if direction == "LONG":
        sl = [s["extreme"] for s in ia["sweeps"] if s["dir"] == "bull"]
        if f.get("bull_ob"):
            sl.append(f["bull_ob"]["bottom"])
        if f.get("bull_fvg"):
            sl.append(f["bull_fvg"]["bottom"])
        sl += [s["price"] for s in ia["swing_lows"][-6:] if s["price"] < close]
        tp = [s["price"] for s in ia["swing_highs"][-10:]] + \
             [l["price"] for l in ia["liquidity"] if l["side"] == "buy"] + \
             [g["bottom"] for g in ia["fvgs"] if g["dir"] == "bear" and not g["filled"]]
    else:
        sl = [s["extreme"] for s in ia["sweeps"] if s["dir"] == "bear"]
        if f.get("bear_ob"):
            sl.append(f["bear_ob"]["top"])
        if f.get("bear_fvg"):
            sl.append(f["bear_fvg"]["top"])
        sl += [s["price"] for s in ia["swing_highs"][-6:] if s["price"] > close]
        tp = [s["price"] for s in ia["swing_lows"][-10:]] + \
             [l["price"] for l in ia["liquidity"] if l["side"] == "sell"] + \
             [g["top"] for g in ia["fvgs"] if g["dir"] == "bull" and not g["filled"]]
    prof = flow.profile or {}
    tp += [x for x in [prof.get("poc"), prof.get("vah"), prof.get("val")] + prof.get("hvn", []) if x]
    return sl, tp


def check(symbol: str, tf: str = "15m", with_chart: bool = True, bars_out: int = 300) -> dict:
    cfg = get_config()
    scfg = cfg.get("strategy", {})
    sym = instruments.normalize(symbol)
    meta = instruments.info(sym)
    prov = get_provider()
    out = {"symbol": sym, "name": meta["name"], "category": meta["category"], "tf": tf, "paper": True,
           "source": prov.name, "source_note": getattr(prov, "delayed_note", ""), "generated": int(time.time()),
           "orderflow_estimated": True}
    try:
        df = prov.candles(sym, tf)
    except DataUnavailable as e:
        out.update({"ok": False, "decision": "DATA UNAVAILABLE", "error": "data unavailable", "detail": str(e)})
        return out
    if len(df) < 60:
        out.update({"ok": False, "decision": "DATA UNAVAILABLE", "error": "data unavailable",
                    "detail": f"only {len(df)} bars returned"})
        return out
    ia = ict.analyze(df, scfg.get("swing_k", 2), scfg.get("atr_period", 14))
    flow = get_orderflow_provider().analyze(df, FlowSettings.from_cfg(cfg.get("orderflow")))
    htf_tf = HTF.get(tf, "1h")
    htf_trend = 0
    try:
        hdf = resample(df, RULES[htf_tf]) if htf_tf != tf else df
        if len(hdf) >= 30:
            hs, ls = ict.swings(hdf, 2)
            htf_trend = ict.structure(hdf, hs, ls, 2)["trend"]
    except Exception as e:
        log.debug("htf failed: %s", e)
    f = extract_features(df, ia, flow, htf_trend, htf_tf)
    sc = score_features(f)
    bo = None
    warnings = []
    try:
        bo = events.blackout(sym)
        upcoming = events.events_for(sym, cfg.get("events", {}).get("warn_hours", 12))
        for e in upcoming[:5]:
            m = e["minutes_away"]
            when = f"in {m} min" if m < 120 else f"in {m / 60:.1f} h"
            warnings.append({"title": e["title"], "ccy": e["ccy"], "impact": e["impact"], "time": e["time"],
                             "minutes_away": m, "text": f"{e['ccy']} {e['title']} {when} (high impact)"})
    except Exception as e:
        warnings.append({"text": "Economic calendar: data unavailable"})
    decision = decide(sc, scfg.get("min_score", 55), scfg.get("min_margin", 15), bo)
    side_key = "long" if decision == "LONG" else "short" if decision == "SHORT" else ("long" if sc.long >= sc.short else "short")
    reasons = [{"text": c.text, "tag": c.tag, "points": c.points, "side": c.side}
               for c in sc.components if c.side in (side_key, "both")]
    against = [{"text": c.text, "tag": c.tag, "points": c.points, "side": c.side}
               for c in sc.components if c.side not in (side_key, "both")]
    close = f["close"]
    dp = decimals(close)
    out.update({"ok": True, "decision": decision, "price": round(close, dp),
                "last_bar": int(df.index[-1].timestamp()),
                "confidence": round(max(sc.long, sc.short) if decision != "NO TRADE" else max(sc.long, sc.short)),
                "scores": {"long": round(sc.long), "short": round(sc.short)},
                "reasons": reasons, "against": against, "warnings": warnings,
                "blackout": bo and {"title": bo["title"], "ccy": bo["ccy"], "time": bo["time"]},
                "atr": round(ia["atr"], dp + 1), "killzone": ia["killzone"],
                "trend": ia["structure"]["trend"], "htf_trend": htf_trend, "htf_tf": htf_tf,
                "zone": ia["range"]["zone"], "volume_source": flow.volume_source})
    if bo:
        out["reasons"].insert(0, {"text": f"High-impact {bo['ccy']} event '{bo['title']}' is too close - standing aside",
                                  "tag": "Event risk", "points": 0, "side": "both"})
    if decision in ("LONG", "SHORT"):
        slc, tpc = level_candidates(decision, f, ia, flow)
        lv = compute_levels(decision, close, ia["atr"], slc, tpc, scfg)
        for k in ("entry", "sl", "tp1", "tp2"):
            lv[k] = round(lv[k], dp)
        lv["risk"] = round(lv["risk"], dp + 1)
        out["levels"] = lv
        out["rr"] = lv["rr2"]
    else:
        # still give the user the reference levels for the stronger side, flagged as not a trade
        slc, tpc = level_candidates(side_key.upper(), f, ia, flow)
        lv = compute_levels(side_key.upper(), close, ia["atr"], slc, tpc, scfg)
        out["watch"] = {"bias": side_key.upper(), "sl": round(lv["sl"], dp), "tp1": round(lv["tp1"], dp),
                        "note": "Not enough confluence - reference levels only, no trade"}
    try:
        out["headlines"] = [{"title": n["title"], "source": n["source"], "ts": n["ts"], "link": n["link"]}
                            for n in events.news_for(sym, 24, 4)]
    except Exception:
        out["headlines"] = []
    if with_chart:
        out["chart"] = chart_payload(df, ia, flow, bars_out)
    return out


def chart_payload(df: pd.DataFrame, ia: dict, flow, bars_out: int = 300) -> dict:
    tail = df.iloc[-bars_out:]
    t0 = int(tail.index[0].timestamp())
    candles = [{"time": int(ts.timestamp()), "open": float(r.open), "high": float(r.high), "low": float(r.low),
                "close": float(r.close), "volume": float(r.volume)} for ts, r in tail.iterrows()]
    delta = []
    if flow.bars is not None:
        fb = flow.bars.iloc[-bars_out:]
        delta = [{"time": int(ts.timestamp()), "value": float(r["delta"]), "surge": int(r["surge"]),
                  "absorb": int(r["absorb"])} for ts, r in fb.iterrows()]
    return {
        "candles": candles, "delta": delta,
        "fvgs": [g for g in ia["fvgs"] if not g["filled"] and g["time"] >= t0][-8:],
        "order_blocks": [o for o in ia["order_blocks"] if not o["invalid"] and o["time"] >= t0][-6:],
        "liquidity": ia["liquidity"], "sweeps": ia["sweeps"],
        "structure": [e for e in ia["structure"]["events"] if e["time"] >= t0][-12:],
        "profile": {k: v for k, v in (flow.profile or {}).items()},
        "sessions": ict.session_boxes(tail),
        "psych": flow.psych_levels,
        "range": ia["range"],
    }
