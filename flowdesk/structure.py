"""ICT-style structure from candles: swings, BOS/CHoCH, FVGs, order blocks, liquidity.

Levels come from the bars passed in. Nothing here invents a price.
"""

from __future__ import annotations

from datetime import datetime, timezone

from flowdesk.catalog import derive_psych_step
from flowdesk.models import (
    Bar,
    FairValueGap,
    Instrument,
    LiquidityLevel,
    OrderBlock,
    SessionRange,
    Structure,
    Sweep,
    Swing,
)


def average_true_range(bars: list[Bar], period: int = 14) -> float:
    if not bars:
        return 0.0
    if len(bars) == 1:
        return max(bars[0].high - bars[0].low, 0.0)
    true_ranges: list[float] = []
    for index in range(1, len(bars)):
        current = bars[index]
        previous = bars[index - 1]
        true_ranges.append(
            max(
                current.high - current.low,
                abs(current.high - previous.close),
                abs(current.low - previous.close),
            )
        )
    if len(true_ranges) < period:
        return sum(true_ranges) / len(true_ranges)
    value = sum(true_ranges[:period]) / period
    for tr in true_ranges[period:]:
        value = (value * (period - 1) + tr) / period
    return value


def find_swings(bars: list[Bar], left: int = 2, right: int = 2) -> list[Swing]:
    swings: list[Swing] = []
    count = len(bars)
    if count < left + right + 1:
        return swings
    for index in range(left, count - right):
        high = bars[index].high
        low = bars[index].low
        highs = [bars[j].high for j in range(index - left, index + right + 1)]
        lows = [bars[j].low for j in range(index - left, index + right + 1)]
        if high == max(highs) and highs.count(high) == 1:
            swings.append(Swing(index, bars[index].time, "high", high))
        if low == min(lows) and lows.count(low) == 1:
            swings.append(Swing(index, bars[index].time, "low", low))
    return swings


def swing_bias(swings: list[Swing]) -> str:
    highs = [item for item in swings if item.kind == "high"]
    lows = [item for item in swings if item.kind == "low"]
    if len(highs) < 2 or len(lows) < 2:
        return "unclear"
    higher_high = highs[-1].price > highs[-2].price
    higher_low = lows[-1].price > lows[-2].price
    lower_high = highs[-1].price < highs[-2].price
    lower_low = lows[-1].price < lows[-2].price
    if higher_high and higher_low:
        return "bullish"
    if lower_high and lower_low:
        return "bearish"
    return "range"


def fresh_break(bars: list[Bar], level: float, direction: str, lookback: int = 3) -> bool:
    if len(bars) < lookback + 1:
        return False

    def broken(bar: Bar) -> bool:
        if direction == "bullish":
            return bar.close > level
        return bar.close < level

    recent = bars[-lookback:]
    prior = bars[-lookback - 1]
    return any(broken(bar) for bar in recent) and not broken(prior)


def fair_value_gaps(bars: list[Bar], min_gap: float) -> list[FairValueGap]:
    gaps: list[FairValueGap] = []
    for index in range(2, len(bars)):
        left = bars[index - 2]
        right = bars[index]
        if right.low - left.high >= min_gap:
            bottom = left.high
            top = right.low
            mitigated = any(bars[j].low <= bottom for j in range(index + 1, len(bars)))
            gaps.append(FairValueGap("bullish", bottom, top, index, right.time, mitigated))
        elif left.low - right.high >= min_gap:
            bottom = right.high
            top = left.low
            mitigated = any(bars[j].high >= top for j in range(index + 1, len(bars)))
            gaps.append(FairValueGap("bearish", bottom, top, index, right.time, mitigated))
    return gaps


def find_order_blocks(bars: list[Bar], atr_value: float) -> list[OrderBlock]:
    if atr_value <= 0 or len(bars) < 6:
        return []
    blocks: list[OrderBlock] = []
    for index in range(2, len(bars)):
        bar = bars[index]
        span = bar.high - bar.low
        if span < 1.2 * atr_value or span <= 0:
            continue
        close_pos = (bar.close - bar.low) / span
        if bar.close > bar.open and close_pos >= 0.7:
            for back in range(index - 1, max(-1, index - 6), -1):
                candle = bars[back]
                if candle.close < candle.open:
                    mitigated = any(bars[j].low < candle.low for j in range(index + 1, len(bars)))
                    zone_high = max(candle.open, candle.close)
                    blocks.append(OrderBlock("bullish", candle.low, zone_high, back, candle.time, mitigated))
                    break
        elif bar.close < bar.open and close_pos <= 0.3:
            for back in range(index - 1, max(-1, index - 6), -1):
                candle = bars[back]
                if candle.close > candle.open:
                    mitigated = any(bars[j].high > candle.high for j in range(index + 1, len(bars)))
                    zone_low = min(candle.open, candle.close)
                    blocks.append(OrderBlock("bearish", zone_low, candle.high, back, candle.time, mitigated))
                    break
    # Keep the most recent unmitigated blocks, then a few mitigated ones for context.
    fresh = [block for block in blocks if not block.mitigated]
    return fresh[-8:]


def _session_name(moment: datetime) -> str:
    hour = moment.astimezone(timezone.utc).hour
    if hour < 7:
        return "Asia"
    if hour < 12:
        return "London"
    if hour < 21:
        return "New York"
    return "Late"


def session_ranges(bars: list[Bar]) -> list[SessionRange]:
    groups: dict[tuple, list[Bar]] = {}
    for bar in bars:
        ts = bar.time.astimezone(timezone.utc)
        key = (ts.date().isoformat(), _session_name(ts))
        groups.setdefault(key, []).append(bar)
    ranges: list[SessionRange] = []
    keys = list(groups.keys())
    for index, key in enumerate(keys):
        group = groups[key]
        ranges.append(
            SessionRange(
                name=key[1],
                start=group[0].time,
                end=group[-1].time,
                high=max(item.high for item in group),
                low=min(item.low for item in group),
                complete=index < len(keys) - 1,
            )
        )
    return ranges


def killzone(moment: datetime) -> str | None:
    ts = moment.astimezone(timezone.utc)
    hour = ts.hour + ts.minute / 60.0
    if 7 <= hour < 10:
        return "London"
    if 12 <= hour < 15:
        return "New York"
    return None


def _dealing_range(last_high: Swing | None, last_low: Swing | None, price: float, atr_value: float) -> tuple:
    if not last_high or not last_low:
        return None, None, None, None, None
    high = max(last_high.price, last_low.price)
    low = min(last_high.price, last_low.price)
    if high <= low:
        return high, low, None, None, None
    equilibrium = (high + low) / 2.0
    span = high - low
    band = max(0.05 * atr_value, span * 0.02)
    if price > equilibrium + band:
        zone = "premium"
    elif price < equilibrium - band:
        zone = "discount"
    else:
        zone = "equilibrium"
    ote = None
    # Up-leg (swing low printed before swing high): long OTE is the 62–79% pullback.
    if last_low.index < last_high.index:
        upper = high - 0.62 * span
        lower = high - 0.79 * span
        if lower <= price <= upper:
            ote = "long"
    if last_high.index < last_low.index:
        lower = low + 0.62 * span
        upper = low + 0.79 * span
        if lower <= price <= upper:
            ote = "short"
    return high, low, equilibrium, zone, ote


def _liquidity(
    bars: list[Bar],
    swings: list[Swing],
    sessions: list[SessionRange],
    atr_value: float,
) -> tuple[list[LiquidityLevel], list[Sweep]]:
    levels: list[LiquidityLevel] = []
    highs = [item for item in swings if item.kind == "high"]
    lows = [item for item in swings if item.kind == "low"]
    if highs:
        levels.append(LiquidityLevel(highs[-1].price, "swing_high", "swing high"))
    if lows:
        levels.append(LiquidityLevel(lows[-1].price, "swing_low", "swing low"))
    if len(highs) >= 2 and atr_value > 0 and abs(highs[-1].price - highs[-2].price) <= 0.1 * atr_value:
        price = (highs[-1].price + highs[-2].price) / 2
        levels.append(LiquidityLevel(price, "equal_highs", "equal highs"))
    if len(lows) >= 2 and atr_value > 0 and abs(lows[-1].price - lows[-2].price) <= 0.1 * atr_value:
        price = (lows[-1].price + lows[-2].price) / 2
        levels.append(LiquidityLevel(price, "equal_lows", "equal lows"))

    by_day: dict = {}
    for bar in bars:
        by_day.setdefault(bar.time.astimezone(timezone.utc).date(), []).append(bar)
    days = sorted(by_day)
    if len(days) >= 2:
        previous = by_day[days[-2]]
        levels.append(LiquidityLevel(max(item.high for item in previous), "pdh", "prior day high"))
        levels.append(LiquidityLevel(min(item.low for item in previous), "pdl", "prior day low"))

    completed = [item for item in sessions if item.complete]
    for item in completed[-4:]:
        levels.append(LiquidityLevel(item.high, "session_high", f"{item.name} session high"))
        levels.append(LiquidityLevel(item.low, "session_low", f"{item.name} session low"))

    sweeps: list[Sweep] = []
    lookback = min(8, len(bars))
    start = len(bars) - lookback
    recent = list(enumerate(bars[start:], start=start))

    def _sweep_low(level: float, label: str, before_index: int) -> None:
        for index, bar in recent:
            if index <= before_index:
                continue
            if bar.low < level and bar.close > level:
                sweeps.append(Sweep("bullish", level, bar.low, index, label))
                return

    def _sweep_high(level: float, label: str, before_index: int) -> None:
        for index, bar in recent:
            if index <= before_index:
                continue
            if bar.high > level and bar.close < level:
                sweeps.append(Sweep("bearish", level, bar.high, index, label))
                return

    prior_lows = [item for item in lows if item.index < start]
    prior_highs = [item for item in highs if item.index < start]
    if prior_lows:
        _sweep_low(prior_lows[-1].price, "prior swing low", prior_lows[-1].index)
    if prior_highs:
        _sweep_high(prior_highs[-1].price, "prior swing high", prior_highs[-1].index)
    for item in completed[-3:]:
        _sweep_low(item.low, f"{item.name} session low", -1)
        _sweep_high(item.high, f"{item.name} session high", -1)
    for level in levels:
        if level.kind == "pdl":
            _sweep_low(level.price, level.label, -1)
        elif level.kind == "pdh":
            _sweep_high(level.price, level.label, -1)
    # De-duplicate sweeps that share a direction and almost the same level.
    unique: list[Sweep] = []
    for sweep in sweeps:
        if any(existing.direction == sweep.direction and abs(existing.level - sweep.level) <= 1e-9 for existing in unique):
            continue
        unique.append(sweep)
    return levels, unique


def _psych(price: float, instrument: Instrument | None, atr_value: float) -> tuple[float | None, bool]:
    step = instrument.psych_step if instrument and instrument.psych_step else derive_psych_step(price)
    if step <= 0:
        return None, False
    nearest = round(price / step) * step
    near = atr_value > 0 and abs(price - nearest) <= 0.25 * atr_value
    return nearest, near


def analyze_structure(
    bars: list[Bar],
    *,
    now: datetime | None = None,
    instrument: Instrument | None = None,
    swing_left: int = 2,
    swing_right: int = 2,
    atr_period: int = 14,
) -> Structure:
    atr_value = average_true_range(bars, atr_period)
    swings = find_swings(bars, swing_left, swing_right)
    bias = swing_bias(swings)
    highs = [item for item in swings if item.kind == "high"]
    lows = [item for item in swings if item.kind == "low"]
    last_high = highs[-1] if highs else None
    last_low = lows[-1] if lows else None
    bos = None
    choch = None
    if last_high and fresh_break(bars, last_high.price, "bullish"):
        if bias == "bearish":
            choch = "bullish"
        else:
            bos = "bullish"
    elif last_low and fresh_break(bars, last_low.price, "bearish"):
        if bias == "bullish":
            choch = "bearish"
        else:
            bos = "bearish"
    price = bars[-1].close if bars else 0.0
    dealing_high, dealing_low, equilibrium, zone, ote = _dealing_range(last_high, last_low, price, atr_value)
    min_gap = max(atr_value * 0.05, 0.0)
    gaps = [gap for gap in fair_value_gaps(bars, min_gap) if not gap.mitigated][-8:]
    blocks = find_order_blocks(bars, atr_value)
    sessions = session_ranges(bars)
    liquidity, sweeps = _liquidity(bars, swings, sessions, atr_value)
    moment = now or (bars[-1].time if bars else datetime.now(timezone.utc))
    psych_level, psych_near = _psych(price, instrument, atr_value)
    if psych_level is not None:
        liquidity.append(LiquidityLevel(psych_level, "psych", "psychological level"))
    return Structure(
        bias=bias,
        swings=swings,
        bos=bos,
        choch=choch,
        last_swing_high=last_high,
        last_swing_low=last_low,
        dealing_high=dealing_high,
        dealing_low=dealing_low,
        equilibrium=equilibrium,
        zone=zone,
        ote=ote,
        fvgs=gaps,
        order_blocks=blocks,
        liquidity=liquidity,
        sweeps=sweeps,
        sessions=sessions[-8:],
        atr=atr_value,
        killzone=killzone(moment),
        psych_level=psych_level,
        psych_near=psych_near,
    )
