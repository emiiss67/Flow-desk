"""Order-flow estimates from OHLCV.

This is not a footprint. Candle delta splits each bar's volume by where the
close finished inside the range. If the feed has no volume, the result is
unavailable rather than a made-up number.
"""

from __future__ import annotations

from flowdesk.models import Bar, OrderFlowEstimate

_NOTE = (
    "Estimated from OHLCV candle position and volume. "
    "This is not exchange footprint or tick order flow."
)


def candle_delta(bar: Bar) -> float | None:
    """Buy volume minus sell volume, estimated from where the bar closed.

    Returns None when the range is zero, because the split is undefined.
    A zero-volume bar returns 0.0 — the caller decides whether the feed
    actually provided volume.
    """
    span = bar.high - bar.low
    if span <= 0:
        return None
    if bar.volume < 0:
        return None
    buy = bar.volume * (bar.close - bar.low) / span
    sell = bar.volume * (bar.high - bar.close) / span
    return buy - sell


def detect_absorption(bar: Bar, high_volume: bool) -> str | None:
    """Wick rejection on elevated volume. None when the pattern is absent."""
    if not high_volume:
        return None
    span = bar.high - bar.low
    if span <= 0:
        return None
    body_top = max(bar.open, bar.close)
    body_bottom = min(bar.open, bar.close)
    upper = bar.high - body_top
    lower = body_bottom - bar.low
    body = body_top - body_bottom
    if lower >= 0.55 * span and body <= 0.35 * span:
        return "bullish"
    if upper >= 0.55 * span and body <= 0.35 * span:
        return "bearish"
    return None


def volume_profile(bars: list[Bar], bins: int = 24) -> tuple[float | None, list[float]]:
    """POC and high-volume nodes.

    Each bar's entire volume is placed in the bin of its typical price
    (high + low + close) / 3. That is a bar profile, not a traded-price profile.
    """
    usable = [bar for bar in bars if bar.volume > 0]
    if len(usable) < 5:
        return None, []
    lo = min(bar.low for bar in usable)
    hi = max(bar.high for bar in usable)
    if hi <= lo:
        return None, []
    bins = max(8, min(bins, 48))
    step = (hi - lo) / bins
    bucket = [0.0] * bins
    for bar in usable:
        typical = (bar.high + bar.low + bar.close) / 3.0
        index = min(bins - 1, max(0, int((typical - lo) / step)))
        bucket[index] += bar.volume
    total = sum(bucket)
    if total <= 0:
        return None, []
    poc_index = max(range(bins), key=lambda i: bucket[i])
    poc = lo + (poc_index + 0.5) * step
    cutoff = sorted(bucket)[int(bins * 0.7)]
    hvns = [
        lo + (index + 0.5) * step
        for index, volume in enumerate(bucket)
        if volume >= cutoff and volume > 0
    ]
    return poc, hvns


def estimate_orderflow(bars: list[Bar], lookback: int = 20) -> OrderFlowEstimate:
    if not bars:
        return OrderFlowEstimate(
            available=False,
            kind="none",
            method="ohlcv-candle-delta",
            reason="no candles",
            note=_NOTE,
        )
    volumes = [bar.volume for bar in bars]
    if sum(volumes) <= 0:
        return OrderFlowEstimate(
            available=False,
            kind="none",
            method="ohlcv-candle-delta",
            reason="volume not provided by this feed",
            note=_NOTE,
        )
    window = bars[-lookback:]
    deltas: list[float] = []
    for bar in window:
        delta = candle_delta(bar)
        if delta is None:
            continue
        deltas.append(delta)
    if not deltas:
        return OrderFlowEstimate(
            available=False,
            kind="none",
            method="ohlcv-candle-delta",
            reason="candle ranges are zero, so delta cannot be estimated",
            note=_NOTE,
        )
    cumulative = float(sum(deltas))
    vol = sum(bar.volume for bar in window)
    ratio = cumulative / vol if vol else 0.0
    history = bars[-21:-1]
    avg = (sum(bar.volume for bar in history) / len(history)) if history else None
    spike = bool(avg and avg > 0 and bars[-1].volume >= 1.8 * avg)
    elevated = bool(avg and avg > 0 and bars[-1].volume >= 1.3 * avg)
    last = bars[-1]
    direction = "up" if last.close > last.open else "down" if last.close < last.open else "flat"
    poc, hvns = volume_profile(bars[-120:])
    return OrderFlowEstimate(
        available=True,
        kind="estimate",
        method="ohlcv-candle-delta",
        reason="",
        note=_NOTE,
        cumulative_delta=cumulative,
        delta_ratio=ratio,
        volume_spike=spike,
        last_bar_direction=direction,
        absorption=detect_absorption(last, elevated),
        poc=poc,
        hvns=hvns,
    )
