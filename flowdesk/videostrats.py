"""Strategies from the owner's second batch of sources (25 Nov 2026): the OTE PDF (photos) and the @resellingleague
TikTok account ("leaked course" clips). Rules and every assumption: research/tiktok_strategies.md (batch 2).

Same contract as the video strategies in strategies.py: fn(R, i) -> (side, stop) or (side, (stop, target)) or None,
computed CAUSALLY from rows <= i only, entry = close of bar i (a finished candle). Fixed rules: never tuned by the
learning loop, never switched on by the regime check. Variants were compared on the TRAIN segment only; the variant
picked there is the only one registered (no picking on held-out data)."""
from __future__ import annotations
import math

import numpy as np

_CACHE: list = []          # [(R, n, arrays)] - R kept referenced so its id can not be reused


def arr(R: list[dict]) -> dict:
    for ref, n, a in _CACHE:
        if ref is R and n == len(R):
            return a
    a = {k: np.array([float(r[k]) for r in R]) for k in ("open", "high", "low", "close", "atr", "ema50", "ema200", "ny_hour", "nyday")}
    _CACHE.append((R, len(R), a))
    del _CACHE[:-4]
    return a


def _fin(*xs) -> bool:
    return all(x is not None and math.isfinite(x) for x in xs)


# ---------------- OTE (optimal trade entry) from the PDF ----------------
# Fib drawn on a leg: long = swing low (1) -> swing high (0); golden zone 0.62-0.78 = entry, below 0.5 = discount.
# Target = opposing liquidity = the 0 level (the leg's extreme). Stop: just beyond 0.78 ("z78") or at the 1 level ("s1").
OTE_LEVELS = (0.0, 0.5, 0.62, 0.7, 0.78, 1.0)


def _leg_major(a: dict, i: int, side: str, win: int = 64, min_atr: float = 3.0):
    """The big move: lowest low -> highest high (long) of the last `win` closed bars before i, low first."""
    lo0 = i - win
    if lo0 < 1:
        return None
    h, l = a["high"][lo0:i], a["low"][lo0:i]
    if side == "LONG":
        e1, e0 = lo0 + int(np.argmin(l)), lo0 + int(np.argmax(h))        # 1 = swing low, 0 = swing high
        if not e1 < e0:
            return None
        p1, p0 = a["low"][e1], a["high"][e0]
    else:
        e1, e0 = lo0 + int(np.argmax(h)), lo0 + int(np.argmin(l))
        if not e1 < e0:
            return None
        p1, p0 = a["high"][e1], a["low"][e0]
    if i - e0 < 3 or abs(p0 - p1) < min_atr * a["atr"][i]:                # the extreme must be an established swing
        return None
    return e1, e0, p1, p0


def _pivots(a: dict, i: int, k: int = 2, look: int = 80):
    """Confirmed fractal pivots (k bars each side, all of them closed before bar i): lists of (idx, price)."""
    h, l = a["high"], a["low"]
    ph, pl = [], []
    for j in range(max(k, i - look), i - k):
        if h[j] >= h[j - k:j].max() and h[j] > h[j + 1:j + k + 1].max():
            ph.append((j, h[j]))
        if l[j] <= l[j - k:j].min() and l[j] < l[j + 1:j + k + 1].min():
            pl.append((j, l[j]))
    return ph, pl


def _leg_internal(a: dict, i: int, side: str, min_atr: float = 1.5):
    """An internal leg: the newest confirmed swing high and the lowest low since the swing high before it (long)."""
    ph, pl = _pivots(a, i)
    if side == "LONG":
        if not ph:
            return None
        e0, p0 = ph[-1]
        prev = [j for j, _ in ph[:-1]]
        s = (prev[-1] + 1) if prev else max(0, e0 - 40)
        if e0 - s < 2:
            return None
        e1 = s + int(np.argmin(a["low"][s:e0])); p1 = a["low"][e1]
    else:
        if not pl:
            return None
        e0, p0 = pl[-1]
        prev = [j for j, _ in pl[:-1]]
        s = (prev[-1] + 1) if prev else max(0, e0 - 40)
        if e0 - s < 2:
            return None
        e1 = s + int(np.argmax(a["high"][s:e0])); p1 = a["high"][e1]
    if i - e0 < 3 or abs(p0 - p1) < min_atr * a["atr"][i]:
        return None
    return e1, e0, p1, p0


def ote(R: list[dict], i: int, leg: str = "major", stop: str = "s1", filt: str = "none"):
    a = arr(R)
    atr = a["atr"][i]
    if i < 210 or not _fin(atr) or atr <= 0:
        return None
    o, h, l, c = a["open"][i], a["high"][i], a["low"][i], a["close"][i]
    for side in ("LONG", "SHORT"):
        g = (_leg_major if leg == "major" else _leg_internal)(a, i, side)
        if not g:
            continue
        e1, e0, p1, p0 = g
        sg = 1 if side == "LONG" else -1
        rng = (p0 - p1) * sg                                              # > 0
        lvl = {f: p0 - sg * f * rng for f in OTE_LEVELS}
        seg_l, seg_h = a["low"][e0 + 1:i], a["high"][e0 + 1:i]
        if side == "LONG":
            if len(seg_l) and seg_l.min() <= lvl[0.62]:                    # first visit of the golden zone only
                continue
            if not (l <= lvl[0.62] and l > lvl[1.0] and lvl[0.78] <= c < lvl[0.0]):
                continue
        else:
            if len(seg_h) and seg_h.max() >= lvl[0.62]:
                continue
            if not (h >= lvl[0.62] and h < lvl[1.0] and lvl[0.0] < c <= lvl[0.78]):
                continue
        if filt == "trend" and not ((a["ema50"][i] - a["ema200"][i]) * sg > 0):
            continue
        if filt == "confirm" and not ((c - o) * sg > 0 and (c - lvl[0.62]) * sg > 0):   # rejection candle closes back out of the zone's deep half
            continue
        st = lvl[0.78] - sg * 0.1 * atr if stop == "z78" else lvl[1.0] - sg * 0.05 * atr
        return side, (float(st), float(lvl[0.0]))
    return None


def _v(leg, stop, filt):
    return lambda R, i: ote(R, i, leg, stop, filt)


OTE_VARIANTS = {f"ote_{leg}_{st}_{f}": _v(leg, st, f) for leg in ("major", "internal") for st in ("z78", "s1") for f in ("none", "trend", "confirm")}

FUNCS: dict = {}
# Variant picked on TRAIN only (best train expectancy with >= 30 trades, research/tiktok_strategies.md batch 2):
#   major leg    -> stop at the 1 level, no extra filter  (train -0.05R / 275 - the least bad; all major variants lost in train)
#   internal leg -> stop beyond 0.78, rejection-candle confirmation  (train +0.12R / 34)
FUNCS["ote_major"] = OTE_VARIANTS["ote_major_s1_none"]
FUNCS["ote_internal"] = OTE_VARIANTS["ote_internal_z78_confirm"]

_F = {"fixed": True, "no_regime": True, "per_symbol": True}
STRATEGIES: dict = {
    "ote_major": {"name": "OTE golden zone - major leg (PDF)", "src": "OTE PDF", **_F, "params": {"sl_pad_atr": 0.0, "tp1_r": 1.0, "tp2_r": 2.5},
                  "desc": "Fib on the big move of the last 16 hours (swing low = 1, swing high = 0 for a long). First retrace into the 0.62-0.78 golden zone that closes inside it = entry; stop at the 1 level, target the 0 level (opposing liquidity). Mirrored for shorts."},
    "ote_internal": {"name": "OTE golden zone - internal leg + confirmation (PDF)", "src": "OTE PDF", **_F, "params": {"sl_pad_atr": 0.0, "tp1_r": 1.0, "tp2_r": 2.5},
                     "desc": "Fib on the newest internal swing leg. First tap of the 0.62-0.78 golden zone with a rejection candle closing back out of the zone = entry; stop just beyond 0.78, target the leg's extreme (0 level)."},
    "data_hl": {"name": "Data high / low (08:30 ET news candle)", "src": "Powell / Dodgy", **_F, "params": {"sl_pad_atr": 0.0, "tp1_r": 1.0, "tp2_r": 2.5},
                "desc": "Mark the 08:30 ET candle's high and low (needs a big candle). The first side taken out, then a close back inside the other way = entry toward the opposing side; stop beyond the sweep."},
    "ko10": {"name": "10 AM key open (rejection at the 10:00 ET open)", "src": "Powell", **_F, "params": {"sl_pad_atr": 0.0, "tp1_r": 1.0, "tp2_r": 3.0},
             "desc": "09:30-10:00 ET sweeps the pre-market high (low); after 10:00 price moves away from the 10 AM open and the first return to it rejects = trade away from the sweep. Stop beyond the manipulation, 1R partial and a 3R runner; no Mondays."},
    "rej_block": {"name": "Rejection block (wick 50% / CE)", "src": "Powell", **_F, "params": {"sl_pad_atr": 0.0, "tp1_r": 1.0, "tp2_r": 3.0},
                  "desc": "A big wick that swept a 20-bar high (low); price leaves it, then the first return to the wick's 50% closing back = entry; stop just beyond the wick, 1R partial and a 3R runner."},
    "pb_mech": {"name": "Mech model (inversion fair value gap)", "src": "PB", **_F, "params": {"sl_pad_atr": 0.0, "tp1_r": 1.0, "tp2_r": 2.5},
                "desc": "After a swing low that swept liquidity, the biggest bearish fair value gap of the down-leg is closed through (inverted) = long; stop under the swing low, target the nearest unfilled gap above (mirrored for shorts)."},
    "stdv_london": {"name": "Standard deviations of the London leg", "src": "Dutch / Wicked", **_F, "params": {"sl_pad_atr": 0.0, "tp1_r": 1.0, "tp2_r": 2.5},
                    "desc": "Mark the last London leg (04:30-05:30 ET, wick to wick); in the New York morning the first rejection candle 2-4 leg lengths beyond it is faded back to the leg; stop beyond that candle."},
    # thequantbuilder "learn one strategy" (video 17, 26 Nov): same entry as session_mom but the video adds the missing rules:
    # stop "far away" = 8 x ATR, trailing stop that follows, 1% risk. Intraday only here: the EOD flat closes at 16:45 ET.
    "session_mom_wide": {"name": "Session momentum, wide 8-ATR stop (first candle vs 12 EMA)", "src": "thequantbuilder 2", **_F, "max_sl_atr": 8.0,
                         "params": {"sl_pad_atr": 0.0, "tp1_r": 0.125, "tp2_r": 1.0},
                         "desc": "At the 09:30 ET open the first candle closing above the 12 EMA = long, below = short. Stop 8 ATR away (so noise never stops it out); 1 ATR in profit takes half and the stop trails 1 ATR behind, the rest runs to 8 ATR. Closed by the end-of-day flat."},
    "cisd": {"name": "Sweep + change in state of delivery", "src": "Aval", **_F, "params": {"sl_pad_atr": 0.0, "tp1_r": 1.0, "tp2_r": 2.5},
             "desc": "A 20-bar high (low) is swept, then a close back through the open of the candle run that made the sweep = entry toward the opposite 20-bar extreme (draw on liquidity); stop beyond the sweep."},
}


# ---------------- @resellingleague "leaked course" models (15m adaptations) ----------------
def _bar_at(a: dict, i: int, ny_h: float, back: int = 100):
    """Index of today's (New York date) bar that starts at ny_h, or None (bars <= i only)."""
    day = a["nyday"][i]
    for j in range(i, max(i - back, -1), -1):
        if a["nyday"][j] != day:
            return None
        if abs(a["ny_hour"][j] - ny_h) < 1e-6:
            return j
    return None


def _day_start(a: dict, i: int, back: int = 120) -> int:
    day = a["nyday"][i]
    j = i
    while j > 0 and i - j < back and a["nyday"][j - 1] == day:
        j -= 1
    return j


def _weekday(nyday: float) -> int:
    import datetime as _dt
    d = int(nyday)
    return _dt.date(d // 10000, d // 100 % 100, d % 100).weekday()


def data_hl(R: list[dict], i: int):
    """Powell / Dodgy 'data high and low': the 08:30 ET (news) candle's high and low. The first side taken out ->
    wait for a close back inside in the other direction -> target the opposing side; stop beyond the sweep."""
    a = arr(R)
    if not (8.75 <= a["ny_hour"][i] < 11.0):
        return None
    j = _bar_at(a, i, 8.5)
    if j is None or j >= i:
        return None
    H, L, atr = a["high"][j], a["low"][j], a["atr"][j]
    if not _fin(atr) or H - L < 1.0 * atr:                   # only a prominent data candle (no calendar history: proxy for a news print)
        return None
    first = side = None
    for k in range(j + 1, i + 1):
        up, dn = a["high"][k] > H, a["low"][k] < L
        if up and dn:
            return None
        if up or dn:
            first, side = k, ("SHORT" if up else "LONG")
            break
    if first is None:
        return None
    for k in range(first, i + 1):
        o, c = a["open"][k], a["close"][k]
        if side == "SHORT":
            if a["low"][k] < L:
                return None                                    # the opposing side was reached already
            if c < H and c < o:
                return ("SHORT", (float(a["high"][first:i + 1].max()), float(L))) if k == i else None
        else:
            if a["high"][k] > H:
                return None
            if c > L and c > o:
                return ("LONG", (float(a["low"][first:i + 1].min()), float(H))) if k == i else None
    return None


def ko10(R: list[dict], i: int):
    """Powell '10 AM key open': 09:30-10:00 ET sweeps the pre-market high (low) = manipulation; after 10:00 price
    displaces away from the 10:00 open, then the first return to the 10 AM open rejects -> trade away from the sweep.
    Stop beyond the manipulation extreme; 1R partial (break-even) and a 3R runner. No Mondays (the video skips them)."""
    a = arr(R)
    if not (10.25 <= a["ny_hour"][i] < 12.0) or _weekday(a["nyday"][i]) == 0:
        return None
    j10 = _bar_at(a, i, 10.0)
    j930 = _bar_at(a, i, 9.5)
    if j10 is None or j930 is None or j10 >= i:
        return None
    s = _day_start(a, i)
    pre = [k for k in range(s, j930) if a["ny_hour"][k] >= 4.0]
    if len(pre) < 4:
        return None
    ph, pl = a["high"][pre].max(), a["low"][pre].min()
    mh, ml = a["high"][j930:j10].max(), a["low"][j930:j10].min()
    up, dn = mh > ph, ml < pl
    if up == dn:
        return None
    side = "SHORT" if up else "LONG"
    K, atr = a["open"][j10], a["atr"][i]
    sg = -1 if side == "SHORT" else 1
    disp = None
    for k in range(j10, i):
        if (a["close"][k] - K) * sg >= 0.5 * atr:
            disp = k
            break
    if disp is None:
        return None
    back = a["high"][disp + 1:i] if side == "SHORT" else a["low"][disp + 1:i]
    if len(back) and ((back.max() >= K) if side == "SHORT" else (back.min() <= K)):
        return None                                            # only the first return to the key open
    h, l, c = a["high"][i], a["low"][i], a["close"][i]
    if side == "SHORT" and h >= K and c < K:
        return "SHORT", float(a["high"][j930:i + 1].max())
    if side == "LONG" and l <= K and c > K:
        return "LONG", float(a["low"][j930:i + 1].min())
    return None


def rej_block(R: list[dict], i: int, look: int = 30):
    """Powell rejection block / wick theory: a big wick that swept a 20-bar high (low); price leaves, then the first
    return to the wick's 50% (CE) that closes back below (above) it -> enter, stop just beyond the wick."""
    a = arr(R)
    atr = a["atr"][i]
    o, h, l, c = a["open"], a["high"], a["low"], a["close"]
    for j in range(i - 2, max(i - look, 22), -1):
        rng = h[j] - l[j]
        if rng < 1.2 * a["atr"][j]:
            continue
        top, bot = max(o[j], c[j]), min(o[j], c[j])
        if h[j] - top >= 0.5 * rng and h[j] > h[j - 20:j].max():          # upper rejection wick that took buy-side liquidity
            ce = (h[j] + top) / 2
            seg = slice(j + 1, i)
            if (i - j - 1) and (h[seg].max() >= ce or l[seg].min() > top - 1.0 * atr):
                continue                                                    # must have left by 1 ATR and not returned yet
            if i - j - 1 == 0:
                continue
            if h[i] >= ce and h[i] < h[j] and c[i] < ce:
                return "SHORT", float(h[j] + 0.05 * atr)
            continue
        if bot - l[j] >= 0.5 * rng and l[j] < l[j - 20:j].min():
            ce = (l[j] + bot) / 2
            seg = slice(j + 1, i)
            if i - j - 1 == 0 or l[seg].min() <= ce or h[seg].max() < bot + 1.0 * atr:
                continue
            if l[i] <= ce and l[i] > l[j] and c[i] > ce:
                return "LONG", float(l[j] - 0.05 * atr)
    return None


def pb_mech(R: list[dict], i: int):
    """PB 'Mech model': after a swing low that swept liquidity, the biggest bearish fair value gap of the down-leg is
    inverted (a close above it) -> long, stop under the swing low, target the nearest unfilled bearish gap above
    (mirrored for shorts). The 1-5m 'highest timeframe gap' becomes the largest 15m gap of the leg."""
    a = arr(R)
    if i < 60:
        return None
    o, h, l, c, atr = a["open"], a["high"], a["low"], a["close"], a["atr"][i]
    for side in ("LONG", "SHORT"):
        w0 = i - 20
        if side == "LONG":
            e = w0 + int(np.argmin(l[w0:i])); ext = l[e]
            if e - 10 < 0 or not ext < l[e - 10:e].min():
                continue
        else:
            e = w0 + int(np.argmax(h[w0:i])); ext = h[e]
            if e - 10 < 0 or not ext > h[e - 10:e].max():
                continue
        best = None                                           # largest gap formed in the leg into the extreme
        for k in range(max(e - 12, 2), min(e + 2, i)):
            if side == "LONG" and h[k] < l[k - 2]:
                z = (h[k], l[k - 2])
            elif side == "SHORT" and l[k] > h[k - 2]:
                z = (h[k - 2], l[k])
            else:
                continue
            if z[1] - z[0] >= 0.2 * atr and (best is None or z[1] - z[0] > best[1][1] - best[1][0]):
                best = (k, z)
        if not best:
            continue
        k, (zl, zh) = best
        prev = c[k + 1:i]
        if side == "LONG":
            if len(prev) and prev.max() > zh:                 # first inversion only
                continue
            if not c[i] > zh:
                continue
            tgt = None
            for g in range(i - 96, k - 2):                    # unfilled bearish gaps above: price never traded back to their top
                if g < 2 or not h[g] < l[g - 2]:
                    continue
                gl, gh = h[g], l[g - 2]
                if gl > c[i] and h[g + 1:i + 1].max() < gh:
                    tgt = gl if tgt is None else min(tgt, gl)
            if tgt is None:
                continue
            return "LONG", (float(ext - 0.05 * atr), float(tgt))
        else:
            if len(prev) and prev.min() < zl:
                continue
            if not c[i] < zl:
                continue
            tgt = None
            for g in range(i - 96, k - 2):
                if g < 2 or not l[g] > h[g - 2]:
                    continue
                gl, gh = h[g - 2], l[g]
                if gh < c[i] and l[g + 1:i + 1].min() > gl:
                    tgt = gh if tgt is None else max(tgt, gh)
            if tgt is None:
                continue
            return "SHORT", (float(ext + 0.05 * atr), float(tgt))
    return None


def stdv_london(R: list[dict], i: int):
    """Dutch / Wicked standard deviations: mark the last London leg (04:30-05:30 ET, wick to wick); project it
    -2 to -4 standard deviations (2-4 leg lengths) beyond its end; in the NY morning the first rejection candle
    inside that max reversal zone is faded back to the leg's 0 level. Stop just beyond the rejection candle."""
    a = arr(R)
    if not (7.0 <= a["ny_hour"][i] < 12.0):
        return None
    s = _day_start(a, i)
    leg = [k for k in range(s, i) if 4.5 <= a["ny_hour"][k] < 5.5]
    if len(leg) < 2:
        return None
    hi_k = leg[0] + int(np.argmax(a["high"][leg[0]:leg[-1] + 1])); lo_k = leg[0] + int(np.argmin(a["low"][leg[0]:leg[-1] + 1]))
    H, L, atr = a["high"][hi_k], a["low"][lo_k], a["atr"][i]
    ln = H - L
    if not (0.5 * a["atr"][leg[-1]] <= ln <= 3.0 * a["atr"][leg[-1]]):
        return None
    after = slice(leg[-1] + 1, i)
    o, h, l, c = a["open"][i], a["high"][i], a["low"][i], a["close"][i]
    if hi_k > lo_k:                                            # bullish leg: bottom -> top, reversal zone above
        z2, z4 = H + 2.0 * ln, H + 4.0 * ln
        if (leg[-1] + 1 < i) and (a["low"][after].min() < L or a["high"][after].max() >= z2):
            return None                                        # leg broken, or zone already visited
        if h >= z2 and h <= z4 and c < o:
            return "SHORT", (float(h + 0.1 * atr), float(H))
    else:                                                      # bearish leg: top -> bottom, reversal zone below
        z2, z4 = L - 2.0 * ln, L - 4.0 * ln
        if (leg[-1] + 1 < i) and (a["high"][after].max() > H or a["low"][after].min() <= z2):
            return None
        if l <= z2 and l >= z4 and c > o:
            return "LONG", (float(l - 0.1 * atr), float(L))
    return None


def cisd(R: list[dict], i: int):
    """Aval: a sweep of a 20-bar high (low), then a change in state of delivery - a close back through the open of the
    candle run that made the sweep - toward the draw on liquidity (the opposite 20-bar extreme). Stop beyond the sweep."""
    a = arr(R)
    if not (2.0 <= a["ny_hour"][i] < 16.0):
        return None
    o, h, l, c = a["open"], a["high"], a["low"], a["close"]
    for s in range(i - 1, max(i - 7, 25), -1):
        if h[s] > h[s - 20:s].max() and h[s] >= h[s:i + 1].max():           # buy-side swept at s, still the high
            k = s
            while k > s - 8 and c[k] <= o[k]:                               # back to the last up-close candle
                k -= 1
            j = k
            while j - 1 > s - 10 and c[j - 1] > o[j - 1]:                   # start of the up-close run
                j -= 1
            if not c[k] > o[k]:
                continue
            lvl = o[j]
            if c[s + 1:i].min(initial=np.inf) < lvl if s + 1 < i else False:
                continue                                                    # first CISD close only
            if c[i] < lvl:
                return "SHORT", (float(h[s:i + 1].max() + 0.05 * a["atr"][i]), float(l[s - 20:s].min()))
            continue
        if l[s] < l[s - 20:s].min() and l[s] <= l[s:i + 1].min():
            k = s
            while k > s - 8 and c[k] >= o[k]:
                k -= 1
            j = k
            while j - 1 > s - 10 and c[j - 1] < o[j - 1]:
                j -= 1
            if not c[k] < o[k]:
                continue
            lvl = o[j]
            if c[s + 1:i].max(initial=-np.inf) > lvl if s + 1 < i else False:
                continue
            if c[i] > lvl:
                return "LONG", (float(l[s:i + 1].min() - 0.05 * a["atr"][i]), float(h[s - 20:s].max()))
    return None


def session_mom_wide(R: list[dict], i: int, stop_atr: float = 8.0):
    """First 09:30 ET candle closes above (below) its 12 EMA = long (short); stop = stop_atr x ATR from the close."""
    r = R[i]
    if r["ny_hour"] != 9.5:
        return None
    a, c, e = float(r["atr"]), float(r["close"]), float(r["ema12"])
    if not _fin(a, c, e) or a <= 0:
        return None
    if c > e:
        return "LONG", c - stop_atr * a
    if c < e:
        return "SHORT", c + stop_atr * a
    return None


FUNCS.update({"session_mom_wide": session_mom_wide, "data_hl": data_hl, "ko10": ko10, "rej_block": rej_block, "pb_mech": pb_mech, "stdv_london": stdv_london, "cisd": cisd})
