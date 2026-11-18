"""Order-flow analysis, FlowPro-style, ESTIMATED from OHLCV bars.

True footprint/bid-ask order flow needs a paid tick feed (e.g. Rithmic) and spot forex has no central
order book at all. Everything here is an approximation from candles and is labelled 'estimated'.
A real tick provider can implement OrderFlowProvider later.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class FlowSettings:
    market_pressure: float = 300.0   # |delta| as % of rolling mean |delta| (FlowPro range 300-900)
    volume_spread: float = 2.0       # volume as multiple of rolling mean volume (FlowPro range 2-4)
    lookback: int = 20
    profile_bars: int = 120
    profile_bins: int = 40

    @classmethod
    def from_cfg(cls, cfg: dict | None):
        cfg = cfg or {}
        return cls(**{k: cfg[k] for k in cls.__dataclass_fields__ if k in cfg})


@dataclass
class FlowResult:
    estimated: bool = True
    volume_source: str = "exchange volume"
    bars: pd.DataFrame | None = None           # per-bar estimated buy/sell/delta/pressure flags
    surges: list = field(default_factory=list)  # recent pressure surges
    absorptions: list = field(default_factory=list)
    profile: dict = field(default_factory=dict)  # poc, vah, val, hvn, bins
    cum_delta_slope: float = 0.0
    psych_levels: list = field(default_factory=list)


class OrderFlowProvider(ABC):
    name = "base"

    @abstractmethod
    def analyze(self, df: pd.DataFrame, settings: FlowSettings) -> FlowResult: ...


def psych_step(price: float) -> float:
    """Round-number spacing traders watch (e.g. 1.1000 on EURUSD, 155.00 on USDJPY, 27,000 on NQ)."""
    for limit, step in ((0.5, 0.005), (10, 0.01), (20, 0.1), (200, 1.0), (2000, 10.0), (8000, 50.0),
                        (40000, 100.0), (200000, 500.0)):
        if price < limit:
            return step
    return 1000.0


def psych_levels(price: float, n: int = 3) -> list[float]:
    step = psych_step(price)
    base = np.floor(price / step) * step
    lv = sorted({round(base + i * step, 6) for i in range(-n + 1, n + 1)})
    half = [round(l + step / 2, 6) for l in lv[:-1]]
    return sorted(set(lv + half))


def volume_profile(df: pd.DataFrame, vol: pd.Series, bins: int = 40) -> dict:
    lo, hi = float(df["low"].min()), float(df["high"].max())
    if hi <= lo:
        return {}
    edges = np.linspace(lo, hi, bins + 1)
    hist = np.zeros(bins)
    for l, h, v in zip(df["low"].values, df["high"].values, vol.values):
        if v <= 0:
            continue
        i0 = max(0, int(np.searchsorted(edges, l, side="right") - 1))
        i1 = min(bins - 1, int(np.searchsorted(edges, h, side="left") - 1))
        if i1 < i0:
            i1 = i0
        hist[i0:i1 + 1] += v / (i1 - i0 + 1)      # spread bar volume evenly over its range
    if hist.sum() <= 0:
        return {}
    mids = (edges[:-1] + edges[1:]) / 2
    poc_i = int(hist.argmax())
    # value area 70%
    order = np.argsort(hist)[::-1]
    acc, va = 0.0, []
    for i in order:
        acc += hist[i]
        va.append(i)
        if acc >= 0.7 * hist.sum():
            break
    mean = hist.mean()
    hvn = [float(mids[i]) for i in range(bins)
           if hist[i] > 1.5 * mean and (i == 0 or hist[i] >= hist[i - 1]) and (i == bins - 1 or hist[i] >= hist[i + 1])]
    lvn = [float(mids[i]) for i in range(1, bins - 1) if hist[i] < 0.35 * mean]
    return {"poc": float(mids[poc_i]), "vah": float(edges[max(va) + 1]), "val": float(edges[min(va)]),
            "hvn": hvn, "lvn": lvn, "bins": [{"price": float(m), "vol": float(v)} for m, v in zip(mids, hist)]}


class OHLCVEstimator(OrderFlowProvider):
    """Close-location-value delta estimate + volume spikes + wick absorption + bar-based volume profile."""
    name = "OHLCV estimate"

    def analyze(self, df: pd.DataFrame, s: FlowSettings) -> FlowResult:
        res = FlowResult()
        if df is None or len(df) < s.lookback + 5:
            return res
        d = df.copy()
        rng = (d["high"] - d["low"]).replace(0, np.nan)
        vol = d["volume"].astype(float)
        if (vol > 0).mean() < 0.5:
            # Forex/indices on Yahoo carry no volume: use bar range as an activity proxy (tick-volume-like).
            vol = (d["high"] - d["low"]).astype(float)
            res.volume_source = "range proxy (no volume in feed)"
        clv = (((d["close"] - d["low"]) - (d["high"] - d["close"])) / rng).fillna(0.0)
        d["vol"] = vol
        d["buy"] = vol * (1 + clv) / 2
        d["sell"] = vol * (1 - clv) / 2
        d["delta"] = d["buy"] - d["sell"]
        avg_vol = vol.rolling(s.lookback, min_periods=5).mean().shift(1)
        avg_absd = d["delta"].abs().rolling(s.lookback, min_periods=5).mean().shift(1)
        d["vol_ratio"] = (vol / avg_vol).replace([np.inf, -np.inf], np.nan).fillna(0)
        d["pressure"] = (100 * d["delta"].abs() / avg_absd).replace([np.inf, -np.inf], np.nan).fillna(0)
        body = (d["close"] - d["open"]).abs()
        d["body_frac"] = (body / rng).fillna(0)
        upper = d["high"] - d[["open", "close"]].max(axis=1)
        lower = d[["open", "close"]].min(axis=1) - d["low"]
        d["surge"] = 0
        surge_mask = (d["pressure"] >= s.market_pressure) & (d["vol_ratio"] >= s.volume_spread)
        d.loc[surge_mask & (d["delta"] > 0), "surge"] = 1
        d.loc[surge_mask & (d["delta"] < 0), "surge"] = -1
        # aggressive = big volume + price moved with it; passive/absorption = big volume, small body, long wick
        d["aggressive"] = (d["vol_ratio"] >= 1.5) & (d["body_frac"] >= 0.6)
        absorb = (d["vol_ratio"] >= 1.5) & (d["body_frac"] <= 0.35)
        d["absorb"] = 0
        d.loc[absorb & (lower > 2 * upper) & (lower / rng > 0.45), "absorb"] = 1    # sellers absorbed at lows
        d.loc[absorb & (upper > 2 * lower) & (upper / rng > 0.45), "absorb"] = -1   # buyers absorbed at highs
        res.bars = d
        tail = d.iloc[-60:]
        for ts, r in tail[tail["surge"] != 0].iterrows():
            res.surges.append({"time": int(ts.timestamp()), "side": "buy" if r["surge"] > 0 else "sell",
                               "pressure": round(float(r["pressure"])), "vol_ratio": round(float(r["vol_ratio"]), 2),
                               "price": float(r["close"])})
        for ts, r in tail[tail["absorb"] != 0].iterrows():
            res.absorptions.append({"time": int(ts.timestamp()), "side": "bullish" if r["absorb"] > 0 else "bearish",
                                    "price": float(r["low"] if r["absorb"] > 0 else r["high"]),
                                    "vol_ratio": round(float(r["vol_ratio"]), 2)})
        cd = d["delta"].iloc[-s.lookback:].cumsum()
        norm = d["vol"].iloc[-s.lookback:].sum() or 1
        res.cum_delta_slope = float(cd.iloc[-1] / norm)  # -1..1, net estimated buy minus sell share
        pb = d.iloc[-s.profile_bars:]
        res.profile = volume_profile(pb, pb["vol"], s.profile_bins)
        res.psych_levels = psych_levels(float(d["close"].iloc[-1]))
        return res


def get_orderflow_provider() -> OrderFlowProvider:
    return OHLCVEstimator()
