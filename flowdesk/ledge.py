"""LVN ledge 3-step model ("wicked's trading model", owner's TikTok screenshots, 25 Nov 2026) - market-profile levels.

All values at bar i use bars <= i only:
  * Session = 18:00 -> 18:00 New York (a full daily profile). LVNs ("ledges"), POC and single prints come from the
    PREVIOUS completed sessions; the current session's 30-minute TPO only feeds the bias, built from its closed bars.
  * Volume profile: each bar's volume spread evenly over its high-low range. Yahoo gives NO forex volume, so FX profiles
    weight every bar equally (a time-at-price / TPO profile, not volume). Futures use Yahoo's exchange volume per 15m bar.
    The doc uses a 1-minute chart; FlowDesk only has ~60 days of 15m bars, so profiles are built from 15m bars (coarser).
  * LVN = local minimum of the smoothed profile at <= 35% of the POC with a clearly fuller node on both sides (a ledge).
    Kept only if it lines up with an LVN of one of the two sessions before (alignment), and dropped once the current
    session has spent 3+ bars straddling it (consolidated through). LVNs that push straight into a POC are skipped
    at signal time (POC within 1R in the trade direction).
  * Single prints: price bins touched by exactly one 30-minute TPO period, in runs of 2+ bins - used as targets.
  * Bias: current session's 30-minute TPO - share of TPO overlap in the upper half of the session range so far
    (>= 0.55 bullish, <= 0.45 bearish).
  * SMT: ISMT between two candles (the newer candle sweeps the older one's low/high with its wick but its body low/high
    holds = divergence) OR classic SMT against a correlated instrument (one makes a new 5-bar low/high, the other does not)."""
from __future__ import annotations
import math

import numpy as np
import pandas as pd

NY = "America/New_York"
BINS = 80
LVN_MAX = 0.35          # LVN volume <= 35% of the POC
NODE_X = 2.0            # fuller node on each side >= 2x the LVN
ALIGN_BINS = 2.5        # alignment tolerance in bins of the previous session's profile
CONSOL_BARS = 4         # bars straddling the LVN this session -> consolidated through, dropped
DEV_MIN = 16            # developing (current-session) profile used once it has 4 hours of bars
SMT_LOOK = 5

# correlated instruments for classic SMT (positive correlation only)
PEERS = {"NQ=F": "ES=F", "ES=F": "NQ=F", "YM=F": "ES=F", "RTY=F": "ES=F",
         "EURUSD=X": "GBPUSD=X", "GBPUSD=X": "EURUSD=X", "AUDUSD=X": "NZDUSD=X", "NZDUSD=X": "AUDUSD=X",
         "EURJPY=X": "GBPJPY=X", "GBPJPY=X": "EURJPY=X"}


def session_key(index: pd.DatetimeIndex) -> np.ndarray:
    """18:00 NY -> 18:00 NY session id (the NY date the session ends on, as yyyymmdd)."""
    ny = index.tz_convert(NY) + pd.Timedelta(hours=6)
    return (ny.year * 10000 + ny.month * 100 + ny.day).to_numpy()


def profile(h: np.ndarray, l: np.ndarray, w: np.ndarray, period: np.ndarray) -> dict | None:
    """Volume profile + 30-min TPO single prints of one session."""
    lo, hi = float(np.min(l)), float(np.max(h))
    if not (hi > lo) or len(h) < 16:
        return None
    step = (hi - lo) / BINS
    edges = lo + step * np.arange(BINS + 1)
    vol = np.zeros(BINS)
    a = np.clip(((l - lo) / step).astype(int), 0, BINS - 1)
    b = np.clip(((h - lo) / step).astype(int), 0, BINS - 1)
    for k in range(len(h)):
        vol[a[k]:b[k] + 1] += w[k] / (b[k] - a[k] + 1)
    sm = np.convolve(vol, np.ones(3) / 3, mode="same")
    poc_i = int(np.argmax(sm))
    poc = float(edges[poc_i] + step / 2)
    pv = sm[poc_i]
    lvns = []
    for k in range(4, BINS - 4):
        v = sm[k]
        if v > LVN_MAX * pv or not (v <= sm[k - 1] and v <= sm[k + 1]) or (v == sm[k - 1] and v == sm[k + 1]):
            continue
        if sm[:k].max() >= NODE_X * v and sm[k + 1:].max() >= NODE_X * v:
            lvns.append(float(edges[k] + step / 2))
    # 30-min TPO counts per bin -> single prints (runs of 2+ bins touched by one period only)
    tpo = np.zeros(BINS, dtype=int)
    for p in np.unique(period):
        m = period == p
        pa, pb = a[m].min(), b[m].max()
        tpo[pa:pb + 1] += 1
    sp, run = [], []
    for k in range(BINS):
        if tpo[k] == 1:
            run.append(k)
        else:
            if len(run) >= 2:
                sp.append((float(edges[run[0]]), float(edges[run[-1] + 1])))
            run = []
    if len(run) >= 2:
        sp.append((float(edges[run[0]]), float(edges[run[-1] + 1])))
    return {"lo": lo, "hi": hi, "step": step, "poc": poc, "lvns": lvns, "sp": sp}


def compute(df: pd.DataFrame, tail: int | None = None) -> pd.DataFrame:
    """Per-bar profile features (object columns hold tuples). Causal. tail = only fill the newest `tail` bars (live scans
    read just the last few bars; values are identical to a full run)."""
    n = len(df)
    out = {"vp_lvn": [()] * n, "vp_sp": [()] * n, "vp_poc": [()] * n, "tpo_up": [math.nan] * n, "tpo_n": [0] * n}
    if n < 50:
        return pd.DataFrame(out, index=df.index)
    h = df["high"].to_numpy(float); l = df["low"].to_numpy(float)
    v = df["volume"].fillna(0).to_numpy(float)
    w = np.where(v > 0, v, 1.0) if (v > 0).mean() > 0.5 else np.ones(n)     # FX: no volume -> time at price
    sk = session_key(df.index)
    secs = df.index.tz_convert("UTC").tz_localize(None).to_numpy().astype("datetime64[s]").astype(np.int64)
    period = secs // 1800                                                  # 30-minute TPO period id
    keys, starts = np.unique(sk, return_index=True)
    order = np.argsort(starts)
    keys, starts = keys[order], starts[order]
    ends = list(starts[1:]) + [n]
    profs = []
    for s0, s1 in zip(starts, ends):
        profs.append(profile(h[s0:s1], l[s0:s1], w[s0:s1], period[s0:s1]) if s1 - s0 >= 40 else None)
    first = n - tail if tail else 0
    for j, (s0, s1) in enumerate(zip(starts, ends)):
        if s1 <= first:
            continue
        prior = [p for p in profs[max(0, j - 3):j] if p]                    # up to three completed sessions, newest last
        dev, dev_p, p0 = None, None, s0
        hi_run, lo_run = -math.inf, math.inf
        per_ov = {}                                                         # TPO period -> (hi, lo) so far this session
        for i in range(s0, s1):
            if period[i] != dev_p:                                          # developing profile refreshed every 30 minutes,
                dev_p, p0 = period[i], i                                    # from the bars before this TPO period
                dev = None
            if dev is None and p0 - s0 >= DEV_MIN and i >= first:
                dev = profile(h[s0:p0], l[s0:p0], w[s0:p0], period[s0:p0])
            # levels known BEFORE bar i: completed sessions + this session's developing profile
            profs_now = ([dev] if dev else []) + prior[::-1]
            if profs_now and i >= first:
                lv = []
                for k, p in enumerate(profs_now[:3]):
                    for x in p["lvns"]:
                        if any(abs(x - y) <= ALIGN_BINS * max(p["step"], q["step"]) for m, q in enumerate(profs_now) if m != k for y in q["lvns"]):
                            if np.count_nonzero((l[s0:i] <= x) & (h[s0:i] >= x)) < CONSOL_BARS:   # not consolidated through
                                lv.append(round(x, 10))
                out["vp_lvn"][i] = tuple(sorted(set(lv)))
                out["vp_sp"][i] = tuple(z for p in profs_now[:3] for z in p["sp"])
                out["vp_poc"][i] = tuple(p["poc"] for p in profs_now[:2])
            # bias from the session's 30-min TPO including bar i (closed)
            hi_run, lo_run = max(hi_run, h[i]), min(lo_run, l[i])
            pi = period[i]
            ph, pl = per_ov.get(pi, (-math.inf, math.inf))
            per_ov[pi] = (max(ph, h[i]), min(pl, l[i]))
            if i < first:
                continue
            mid = (hi_run + lo_run) / 2
            up = tot = 0.0
            for ph, pl in per_ov.values():
                tot += ph - pl
                up += max(0.0, ph - max(pl, mid))
            out["tpo_up"][i] = up / tot if tot > 0 else 0.5
            out["tpo_n"][i] = len(per_ov)
    return pd.DataFrame(out, index=df.index)


def smt(df: pd.DataFrame, peer: pd.DataFrame | None = None) -> pd.DataFrame:
    """Bullish / bearish SMT flags per bar: ISMT (two candles) or vs a correlated instrument."""
    o, h, l, c = (df[k].astype(float) for k in ("open", "high", "low", "close"))
    bl, bh = np.minimum(o, c), np.maximum(o, c)
    ismt_bull = (l < l.shift(1)) & (bl >= bl.shift(1)) & (c > o)
    ismt_bear = (h > h.shift(1)) & (bh <= bh.shift(1)) & (c < o)
    d = pd.DataFrame(index=df.index)
    d["ismt_bull"], d["ismt_bear"] = ismt_bull.fillna(False), ismt_bear.fillna(False)
    d["psmt_bull"] = False
    d["psmt_bear"] = False
    if peer is not None and len(peer):
        p = peer[["high", "low"]].astype(float).reindex(df.index)
        ll = l < l.shift(1).rolling(SMT_LOOK).min()
        hh = h > h.shift(1).rolling(SMT_LOOK).max()
        pll = p["low"] < p["low"].shift(1).rolling(SMT_LOOK).min()
        phh = p["high"] > p["high"].shift(1).rolling(SMT_LOOK).max()
        have = p["low"].notna() & p["low"].shift(1).rolling(SMT_LOOK).min().notna()
        d["psmt_bull"] = (ll & ~pll & have).fillna(False)                  # we make a lower low, the peer does not
        d["psmt_bear"] = (hh & ~phh & have).fillna(False)
    return d
