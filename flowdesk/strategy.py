"""Confluence scoring and trade levels.

Confidence is a weighted count of the confluences that are actually present.
It is not a probability. Event blackouts force NO TRADE.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from flowdesk.models import (
    Bar,
    CalendarEvent,
    Instrument,
    Levels,
    OrderFlowEstimate,
    Reason,
    Structure,
)
from flowdesk.orderflow import estimate_orderflow
from flowdesk.structure import analyze_structure

POINTS = {
    "bias": 18,
    "bos": 12,
    "choch": 14,
    "sweep": 16,
    "fvg": 10,
    "ob": 10,
    "zone": 8,
    "ote": 8,
    "killzone": 4,
    "htf": 10,
    "delta": 10,
    "absorption": 8,
    "spike": 6,
    "poc": 4,
    "psych": 3,
}

CONFIDENCE_CAP = 92


@dataclass
class Facts:
    bias: str = "unclear"
    bos: str | None = None
    choch: str | None = None
    sweeps: list[str] = field(default_factory=list)
    sweep_labels: list[str] = field(default_factory=list)
    fvg_touch: list[str] = field(default_factory=list)
    ob_touch: list[str] = field(default_factory=list)
    zone: str | None = None
    ote: str | None = None
    killzone: str | None = None
    htf_bias: str | None = None
    htf_name: str | None = None
    flow_available: bool = False
    flow_reason: str = ""
    delta_ratio: float | None = None
    absorption: str | None = None
    volume_spike: bool = False
    spike_direction: str | None = None
    near_poc: bool = False
    poc: float | None = None
    psych_near: bool = False
    psych_level: float | None = None
    timeframe: str = "M15"


@dataclass
class CheckResult:
    symbol: str
    display: str
    timeframe: str
    call: str
    confidence: int
    blocked_by_event: bool
    direction_if_clear: str | None
    hypothetical: bool
    entry: float | None
    stop_loss: float | None
    take_profit_1: float | None
    take_profit_2: float | None
    risk_reward_1: float | None
    risk_reward_2: float | None
    atr: float | None
    reasons: list[Reason]
    warnings: list[str]
    levels_basis: dict
    confluences: list[str]
    order_flow: dict
    structure: dict
    timeframes: dict
    candles: list[dict]
    overlays: dict
    data: dict
    calendar_available: bool = True
    lean: str | None = None
    long_points: float = 0
    short_points: float = 0

    def to_dict(self) -> dict:
        return {
            "paper_only": True,
            "placed_trade": False,
            "symbol": self.symbol,
            "display": self.display,
            "timeframe": self.timeframe,
            "call": self.call,
            "confidence": self.confidence,
            "confidence_note": "Weighted confluence score from 0 to 92, not a probability.",
            "blocked_by_event": self.blocked_by_event,
            "direction_if_clear": self.direction_if_clear,
            "hypothetical": self.hypothetical,
            "entry": self.entry,
            "stop_loss": self.stop_loss,
            "take_profit_1": self.take_profit_1,
            "take_profit_2": self.take_profit_2,
            "risk_reward_1": self.risk_reward_1,
            "risk_reward_2": self.risk_reward_2,
            "atr": self.atr,
            "reasons": [reason.to_dict() for reason in self.reasons],
            "warnings": self.warnings,
            "levels_basis": self.levels_basis,
            "confluences": self.confluences,
            "order_flow": self.order_flow,
            "structure": self.structure,
            "timeframes": self.timeframes,
            "candles": self.candles,
            "overlays": self.overlays,
            "data": self.data,
            "calendar_available": self.calendar_available,
            "lean": self.lean,
            "long_points": self.long_points,
            "short_points": self.short_points,
        }


def score_facts(facts: Facts, min_score: int = 55) -> tuple[str, int, float, float, list[Reason], list[str], str | None]:
    """Return call, confidence, long points, short points, reasons, tags, clear direction."""
    reasons: list[Reason] = []
    long_points = 0.0
    short_points = 0.0

    def add(side: str, points: float, text: str, tag: str) -> None:
        nonlocal long_points, short_points
        reasons.append(Reason(text, tag, side, points))
        if side == "long":
            long_points += points
        elif side == "short":
            short_points += points

    if facts.bias == "bullish":
        add("long", POINTS["bias"], f"{facts.timeframe} structure is bullish: the last two swing highs and swing lows are both rising.", "Structure")
    elif facts.bias == "bearish":
        add("short", POINTS["bias"], f"{facts.timeframe} structure is bearish: the last two swing highs and swing lows are both falling.", "Structure")
    else:
        add("info", 0, f"{facts.timeframe} structure is {facts.bias}. There is no clean higher-high/higher-low or lower-high/lower-low sequence.", "Structure")

    if facts.choch == "bullish":
        add("long", POINTS["choch"], f"Bullish change of character: {facts.timeframe} closed through the last swing high while the swing structure was bearish.", "CHoCH")
    elif facts.choch == "bearish":
        add("short", POINTS["choch"], f"Bearish change of character: {facts.timeframe} closed through the last swing low while the swing structure was bullish.", "CHoCH")
    elif facts.bos == "bullish":
        add("long", POINTS["bos"], f"Bullish break of structure: {facts.timeframe} closed through the last confirmed swing high.", "BOS")
    elif facts.bos == "bearish":
        add("short", POINTS["bos"], f"Bearish break of structure: {facts.timeframe} closed through the last confirmed swing low.", "BOS")

    seen_sweeps: set[str] = set()
    for label in facts.sweep_labels:
        direction = "long" if label.startswith("bullish") else "short"
        if direction in seen_sweeps:
            continue
        seen_sweeps.add(direction)
        kind = "lows" if direction == "long" else "highs"
        add(
            direction,
            POINTS["sweep"],
            f"Liquidity sweep of {kind}: {label.split(':', 1)[-1].strip()}. Price traded through the level and closed back inside.",
            "Liquidity",
        )

    for direction in facts.fvg_touch:
        side = "long" if direction == "bullish" else "short"
        add(side, POINTS["fvg"], f"Price is inside an unfilled {direction} fair value gap.", "FVG")
    for direction in facts.ob_touch:
        side = "long" if direction == "bullish" else "short"
        add(side, POINTS["ob"], f"Price is inside a {direction} order block (the last opposite candle before an impulse).", "Order block")

    if facts.zone == "discount":
        add("long", POINTS["zone"], "Price is in the discount half of the current dealing range.", "Discount")
    elif facts.zone == "premium":
        add("short", POINTS["zone"], "Price is in the premium half of the current dealing range.", "Premium")
    elif facts.zone == "equilibrium":
        add("info", 0, "Price is near the equilibrium of the current dealing range.", "Equilibrium")

    if facts.ote == "long":
        add("long", POINTS["ote"], "Price is in the long OTE retracement, between 62% and 79% of the latest up-swing.", "OTE")
    elif facts.ote == "short":
        add("short", POINTS["ote"], "Price is in the short OTE retracement, between 62% and 79% of the latest down-swing.", "OTE")

    if facts.killzone:
        # A killzone is timing, not direction. It adds to whichever side already leads
        # once scoring finishes. Recorded as info here and applied after the net is known.
        add("info", 0, f"{facts.killzone} killzone is active (London 07:00–10:00 UTC, New York 12:00–15:00 UTC).", "Killzone")

    if facts.htf_name and facts.htf_bias in ("bullish", "bearish"):
        side = "long" if facts.htf_bias == "bullish" else "short"
        add(side, POINTS["htf"], f"Higher timeframe {facts.htf_name} bias is {facts.htf_bias}.", "Higher TF")
    elif facts.htf_name and facts.htf_bias:
        add("info", 0, f"Higher timeframe {facts.htf_name} bias is {facts.htf_bias}.", "Higher TF")
    elif facts.htf_name:
        add("info", 0, f"Higher timeframe {facts.htf_name} bias is unavailable.", "Higher TF")

    if not facts.flow_available:
        why = facts.flow_reason or "the feed did not provide what the estimate needs"
        add("info", 0, f"Order-flow estimate unavailable: {why}.", "Order flow")
    else:
        ratio = facts.delta_ratio or 0.0
        if ratio > 0.08:
            add("long", POINTS["delta"], f"Order-flow estimate (not tick data): candle-delta over the recent window is positive ({ratio:.0%} of volume), so closes finished nearer the highs.", "Delta")
        elif ratio < -0.08:
            add("short", POINTS["delta"], f"Order-flow estimate (not tick data): candle-delta over the recent window is negative ({ratio:.0%} of volume), so closes finished nearer the lows.", "Delta")
        else:
            add("info", 0, "Order-flow estimate (not tick data): candle-delta is balanced, so it does not lean either way.", "Delta")
        if facts.absorption == "bullish":
            add("long", POINTS["absorption"], "Estimated absorption: the last bar has a long lower wick on elevated volume. That is an OHLCV estimate, not a footprint.", "Absorption")
        elif facts.absorption == "bearish":
            add("short", POINTS["absorption"], "Estimated absorption: the last bar has a long upper wick on elevated volume. That is an OHLCV estimate, not a footprint.", "Absorption")
        if facts.volume_spike and facts.spike_direction == "up":
            add("long", POINTS["spike"], "Volume is at least 1.8× its recent average and the last bar closed up.", "Volume")
        elif facts.volume_spike and facts.spike_direction == "down":
            add("short", POINTS["spike"], "Volume is at least 1.8× its recent average and the last bar closed down.", "Volume")
        if facts.near_poc and facts.poc is not None:
            add("info", 0, f"Price is near the estimated point of control at {facts.poc:.6g}. POC here is a bar-volume bin, not a tick node.", "POC")

    if facts.psych_near and facts.psych_level is not None:
        add("info", 0, f"Price is near the psychological level {facts.psych_level:.6g}.", "Psych level")

    net = long_points - short_points
    if net > 0:
        clear = "LONG"
    elif net < 0:
        clear = "SHORT"
    else:
        clear = None
    strength = abs(net)
    if facts.killzone and clear == "LONG":
        long_points += POINTS["killzone"]
        strength = abs(long_points - short_points)
        reasons.append(Reason(f"The {facts.killzone} killzone adds timing confluence to the long side.", "Killzone", "long", POINTS["killzone"]))
    elif facts.killzone and clear == "SHORT":
        short_points += POINTS["killzone"]
        strength = abs(long_points - short_points)
        reasons.append(Reason(f"The {facts.killzone} killzone adds timing confluence to the short side.", "Killzone", "short", POINTS["killzone"]))
    # Recompute net after the timing nudge.
    net = long_points - short_points
    if net > 0:
        clear = "LONG"
    elif net < 0:
        clear = "SHORT"
    else:
        clear = None
    strength = abs(net)
    confidence = int(min(CONFIDENCE_CAP, round(strength)))
    if clear and strength >= min_score:
        call = clear
    else:
        call = "NO TRADE"
    tags: list[str] = []
    lead = "long" if clear == "LONG" else "short" if clear == "SHORT" else None
    if lead:
        for reason in reasons:
            if reason.side == lead and reason.points > 0 and reason.tag not in tags:
                tags.append(reason.tag)
    return call, confidence, long_points, short_points, reasons, tags, clear


def build_levels(side: str, bars: list[Bar], structure: Structure) -> Levels:
    entry = bars[-1].close
    atr_value = structure.atr if structure.atr > 0 else max(abs(entry) * 0.001, 1e-8)
    basis: dict[str, str] = {}

    def clamp_stop(raw: float, anchor_text: str) -> float:
        minimum = entry - 0.4 * atr_value if side == "long" else entry + 0.4 * atr_value
        maximum = entry - 2.8 * atr_value if side == "long" else entry + 2.8 * atr_value
        if side == "long":
            # Further away is a smaller price. At least 0.4 ATR, at most 2.8 ATR.
            stopped = min(raw, minimum)
            stopped = max(stopped, maximum)
        else:
            stopped = max(raw, minimum)
            stopped = min(stopped, maximum)
        if abs(stopped - raw) > 1e-9:
            basis["stop"] = anchor_text + " Distance was then kept between 0.4 and 2.8 ATR."
        else:
            basis["stop"] = anchor_text
        return stopped

    anchors: list[tuple[float, str]] = []
    if side == "long":
        for sweep in structure.sweeps:
            if sweep.direction == "bullish":
                anchors.append((sweep.extreme, f"under the sweep wick {sweep.extreme:.6g} ({sweep.label})"))
        if structure.last_swing_low:
            anchors.append((structure.last_swing_low.price, f"under the swing low {structure.last_swing_low.price:.6g}"))
        for block in structure.order_blocks:
            if block.direction == "bullish" and not block.mitigated:
                anchors.append((block.low, f"under the bullish order block low {block.low:.6g}"))
        floor = entry - 3.0 * atr_value
        ceiling = entry - 0.15 * atr_value
        valid = [(price, text) for price, text in anchors if floor <= price <= ceiling]
        if valid:
            anchor, text = max(valid, key=lambda item: item[0])
            raw = anchor - 0.15 * atr_value
            sl = clamp_stop(raw, f"Stop is 0.15 ATR {text}.")
        else:
            sl = entry - 1.2 * atr_value
            basis["stop"] = "No sweep, swing low, or bullish order block sat between 0.15 and 3 ATR under price, so the stop is 1.2 ATR below entry."
        risk = entry - sl
        if risk <= 0:
            sl = entry - 1.2 * atr_value
            risk = entry - sl
            basis["stop"] = "The structural stop was not below entry, so the stop fell back to 1.2 ATR."
        opposing: list[tuple[float, str]] = []
        if structure.last_swing_high and structure.last_swing_high.price > entry:
            opposing.append((structure.last_swing_high.price, "swing high"))
        for level in structure.liquidity:
            if level.price > entry and level.kind != "psych":
                opposing.append((level.price, level.label))
        band = [(price, label) for price, label in opposing if entry + 0.8 * risk <= price <= entry + 2.4 * risk]
        if band:
            price, label = min(band, key=lambda item: item[0])
            tp1 = price
            basis["tp1"] = f"TP1 is the nearer opposing liquidity ({label}) at {price:.6g}, inside 0.8R–2.4R."
        else:
            tp1 = entry + 1.5 * risk
            basis["tp1"] = "No opposing liquidity between 0.8R and 2.4R, so TP1 is 1.5R."
        further = [(price, label) for price, label in opposing if price >= max(tp1, entry + 2.0 * risk) + 0.15 * risk]
        if further:
            price, label = min(further, key=lambda item: item[0])
            tp2 = price
            basis["tp2"] = f"TP2 is the next liquidity ({label}) at {price:.6g}."
        else:
            tp2 = entry + 2.5 * risk
            if tp2 <= tp1:
                tp2 = tp1 + risk
            basis["tp2"] = "TP2 is 2.5R because no further liquidity level qualified."
    else:
        for sweep in structure.sweeps:
            if sweep.direction == "bearish":
                anchors.append((sweep.extreme, f"above the sweep wick {sweep.extreme:.6g} ({sweep.label})"))
        if structure.last_swing_high:
            anchors.append((structure.last_swing_high.price, f"above the swing high {structure.last_swing_high.price:.6g}"))
        for block in structure.order_blocks:
            if block.direction == "bearish" and not block.mitigated:
                anchors.append((block.high, f"above the bearish order block high {block.high:.6g}"))
        floor = entry + 0.15 * atr_value
        ceiling = entry + 3.0 * atr_value
        valid = [(price, text) for price, text in anchors if floor <= price <= ceiling]
        if valid:
            anchor, text = min(valid, key=lambda item: item[0])
            raw = anchor + 0.15 * atr_value
            sl = clamp_stop(raw, f"Stop is 0.15 ATR {text}.")
        else:
            sl = entry + 1.2 * atr_value
            basis["stop"] = "No sweep, swing high, or bearish order block sat between 0.15 and 3 ATR above price, so the stop is 1.2 ATR above entry."
        risk = sl - entry
        if risk <= 0:
            sl = entry + 1.2 * atr_value
            risk = sl - entry
            basis["stop"] = "The structural stop was not above entry, so the stop fell back to 1.2 ATR."
        opposing = []
        if structure.last_swing_low and structure.last_swing_low.price < entry:
            opposing.append((structure.last_swing_low.price, "swing low"))
        for level in structure.liquidity:
            if level.price < entry and level.kind != "psych":
                opposing.append((level.price, level.label))
        band = [(price, label) for price, label in opposing if entry - 2.4 * risk <= price <= entry - 0.8 * risk]
        if band:
            price, label = max(band, key=lambda item: item[0])
            tp1 = price
            basis["tp1"] = f"TP1 is the nearer opposing liquidity ({label}) at {price:.6g}, inside 0.8R–2.4R."
        else:
            tp1 = entry - 1.5 * risk
            basis["tp1"] = "No opposing liquidity between 0.8R and 2.4R, so TP1 is 1.5R."
        further = [(price, label) for price, label in opposing if price <= min(tp1, entry - 2.0 * risk) - 0.15 * risk]
        if further:
            price, label = max(further, key=lambda item: item[0])
            tp2 = price
            basis["tp2"] = f"TP2 is the next liquidity ({label}) at {price:.6g}."
        else:
            tp2 = entry - 2.5 * risk
            if tp2 >= tp1:
                tp2 = tp1 - risk
            basis["tp2"] = "TP2 is 2.5R because no further liquidity level qualified."

    risk = abs(entry - sl)
    rr1 = abs(tp1 - entry) / risk if risk else 0.0
    rr2 = abs(tp2 - entry) / risk if risk else 0.0
    return Levels(entry, sl, tp1, tp2, rr1, rr2, basis)


def facts_from(
    structure: Structure,
    flow: OrderFlowEstimate,
    *,
    timeframe: str,
    htf_bias: str | None,
    htf_name: str | None,
    price: float,
) -> Facts:
    atr_value = structure.atr or 0.0
    fvg_touch = [
        gap.direction
        for gap in structure.fvgs
        if not gap.mitigated and gap.bottom <= price <= gap.top
    ]
    ob_touch = [
        block.direction
        for block in structure.order_blocks
        if not block.mitigated and block.low <= price <= block.high
    ]
    sweep_labels = [f"{sweep.direction}: {sweep.label}" for sweep in structure.sweeps]
    near_poc = bool(
        flow.available and flow.poc is not None and atr_value > 0 and abs(price - flow.poc) <= 0.35 * atr_value
    )
    return Facts(
        bias=structure.bias,
        bos=structure.bos,
        choch=structure.choch,
        sweeps=[sweep.direction for sweep in structure.sweeps],
        sweep_labels=sweep_labels,
        fvg_touch=fvg_touch,
        ob_touch=ob_touch,
        zone=structure.zone,
        ote=structure.ote,
        killzone=structure.killzone,
        htf_bias=htf_bias,
        htf_name=htf_name,
        flow_available=flow.available,
        flow_reason=flow.reason,
        delta_ratio=flow.delta_ratio,
        absorption=flow.absorption,
        volume_spike=flow.volume_spike,
        spike_direction=flow.last_bar_direction,
        near_poc=near_poc,
        poc=flow.poc,
        psych_near=structure.psych_near,
        psych_level=structure.psych_level,
        timeframe=timeframe,
    )


def _structure_dict(structure: Structure) -> dict:
    return {
        "bias": structure.bias,
        "bos": structure.bos,
        "choch": structure.choch,
        "zone": structure.zone,
        "ote": structure.ote,
        "killzone": structure.killzone,
        "equilibrium": structure.equilibrium,
        "dealing_high": structure.dealing_high,
        "dealing_low": structure.dealing_low,
        "atr": structure.atr,
        "psych_level": structure.psych_level,
        "psych_near": structure.psych_near,
        "last_swing_high": structure.last_swing_high.price if structure.last_swing_high else None,
        "last_swing_low": structure.last_swing_low.price if structure.last_swing_low else None,
    }


def _candles(bars: list[Bar], limit: int = 180) -> list[dict]:
    out = []
    for bar in bars[-limit:]:
        out.append(
            {
                "time": int(bar.time.timestamp()),
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume,
            }
        )
    return out


def _overlays(structure: Structure, flow: OrderFlowEstimate, bars: list[Bar]) -> dict:
    end = int(bars[-1].time.timestamp()) if bars else None
    return {
        "fvgs": [
            {
                "direction": gap.direction,
                "bottom": gap.bottom,
                "top": gap.top,
                "time": int(gap.time.timestamp()),
                "time_end": end,
                "mitigated": gap.mitigated,
            }
            for gap in structure.fvgs
        ],
        "order_blocks": [
            {
                "direction": block.direction,
                "low": block.low,
                "high": block.high,
                "time": int(block.time.timestamp()),
                "time_end": end,
                "mitigated": block.mitigated,
            }
            for block in structure.order_blocks
        ],
        "liquidity": [
            {"price": level.price, "kind": level.kind, "label": level.label}
            for level in structure.liquidity
        ],
        "sessions": [
            {
                "name": item.name,
                "high": item.high,
                "low": item.low,
                "start": int(item.start.timestamp()),
                "end": int(item.end.timestamp()),
                "complete": item.complete,
            }
            for item in structure.sessions
        ],
        "poc": flow.poc if flow.available else None,
        "hvns": flow.hvns if flow.available else [],
        "order_flow_kind": flow.kind if flow.available else "none",
    }


def event_affects(event: CalendarEvent, instrument: Instrument) -> bool:
    return event.currency.upper() in {item.upper() for item in instrument.currencies}


def classify_events(
    events: list[CalendarEvent],
    instrument: Instrument,
    now: datetime,
    blackout_minutes: int,
) -> tuple[list[CalendarEvent], list[str]]:
    """Return blocking events and warning strings."""
    blocking: list[CalendarEvent] = []
    warnings: list[str] = []
    for event in events:
        if not event_affects(event, instrument):
            continue
        impact = (event.impact or "").lower()
        if impact not in ("high", "medium"):
            continue
        minutes = (event.time - now).total_seconds() / 60.0
        when = event.time.astimezone(timezone.utc).strftime("%H:%M UTC")
        if impact == "high" and abs(minutes) <= blackout_minutes:
            blocking.append(event)
            if minutes >= 0:
                warnings.append(
                    f"High-impact {event.currency} {event.title} at {when}, in {int(round(minutes))} min. "
                    f"Blackout is {blackout_minutes} min before and after. No new paper trade."
                )
            else:
                warnings.append(
                    f"High-impact {event.currency} {event.title} printed at {when}, {int(round(abs(minutes)))} min ago. "
                    f"Still inside the {blackout_minutes} min blackout. No new paper trade."
                )
        elif -5 <= minutes <= 12 * 60:
            phase = "in" if minutes >= 0 else "ago"
            warnings.append(
                f"{event.impact} {event.currency} {event.title} at {when} "
                f"({int(round(abs(minutes)))} min {phase})."
            )
    return blocking, warnings


def evaluate_setup(
    bars: list[Bar],
    *,
    instrument: Instrument,
    timeframe: str,
    now: datetime | None = None,
    htf_bars: list[Bar] | None = None,
    htf_name: str | None = None,
    events: list[CalendarEvent] | None = None,
    flow: OrderFlowEstimate | None = None,
    min_score: int = 55,
    blackout_minutes: int = 30,
    swing_left: int = 2,
    swing_right: int = 2,
    atr_period: int = 14,
    min_bars: int = 40,
    data: dict | None = None,
    htf_unavailable: bool = False,
    calendar_available: bool = True,
) -> CheckResult:
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    flow = flow if flow is not None else estimate_orderflow(bars)
    data = data or {}
    if len(bars) < min_bars:
        return CheckResult(
            symbol=instrument.id,
            display=instrument.name,
            timeframe=timeframe,
            call="NO TRADE",
            confidence=0,
            blocked_by_event=False,
            direction_if_clear=None,
            hypothetical=True,
            entry=bars[-1].close if bars else None,
            stop_loss=None,
            take_profit_1=None,
            take_profit_2=None,
            risk_reward_1=None,
            risk_reward_2=None,
            atr=None,
            reasons=[Reason(f"Not enough closed candles ({len(bars)} of {min_bars}) to read structure.", "Data", "info", 0)],
            warnings=[],
            levels_basis={},
            confluences=[],
            order_flow=flow.to_dict(),
            structure={},
            timeframes={"entry": {"tf": timeframe, "bias": "unclear"}, "higher": None},
            candles=_candles(bars),
            overlays={},
            data=data,
            calendar_available=calendar_available,
            lean=None,
        )
    structure = analyze_structure(
        bars,
        now=moment,
        instrument=instrument,
        swing_left=swing_left,
        swing_right=swing_right,
        atr_period=atr_period,
    )
    htf_bias = None
    if htf_bars and len(htf_bars) >= min_bars:
        htf_bias = analyze_structure(
            htf_bars,
            now=moment,
            instrument=instrument,
            swing_left=swing_left,
            swing_right=swing_right,
            atr_period=atr_period,
        ).bias
    elif htf_unavailable:
        htf_bias = None
    facts = facts_from(
        structure,
        flow,
        timeframe=timeframe,
        htf_bias=htf_bias,
        htf_name=htf_name,
        price=bars[-1].close,
    )
    call, confidence, long_pts, short_pts, reasons, tags, clear = score_facts(facts, min_score=min_score)
    warnings: list[str] = []
    if htf_unavailable:
        warnings.append(f"Higher timeframe {htf_name or ''} data unavailable.".strip())
        reasons.append(Reason("Higher timeframe data unavailable, so that confluence was left out.", "Higher TF", "info", 0))
    blocking, event_warnings = classify_events(events or [], instrument, moment, blackout_minutes)
    warnings.extend(event_warnings)
    if not calendar_available:
        warnings.append("Economic calendar data unavailable. The event blackout could not be checked.")
        reasons.append(Reason("Economic calendar data unavailable, so the event blackout was not applied.", "Calendar", "info", 0))
    blocked = bool(blocking)
    side = "long" if (clear == "LONG" or (clear is None and long_pts >= short_pts)) else "short"
    # Only draw levels when there is at least some directional lean or a real ATR.
    levels = build_levels(side, bars, structure) if structure.atr > 0 or bars else None
    hypothetical = call != "LONG" and call != "SHORT"
    if blocked and clear in ("LONG", "SHORT"):
        reasons.insert(
            0,
            Reason(
                f"No trade: a high-impact event that affects {instrument.id} is inside the {blackout_minutes}-minute blackout. "
                f"The setup underneath would have been {clear}.",
                "Calendar",
                "info",
                0,
            ),
        )
        call = "NO TRADE"
        hypothetical = True
    elif blocked:
        reasons.insert(
            0,
            Reason(
                f"No trade: a high-impact event that affects {instrument.id} is inside the {blackout_minutes}-minute blackout.",
                "Calendar",
                "info",
                0,
            ),
        )
        call = "NO TRADE"
        hypothetical = True
    direction_if_clear = clear if blocked else None
    return CheckResult(
        symbol=instrument.id,
        display=instrument.name,
        timeframe=timeframe,
        call=call,
        confidence=confidence,
        blocked_by_event=blocked,
        direction_if_clear=direction_if_clear,
        hypothetical=hypothetical,
        entry=levels.entry if levels else None,
        stop_loss=levels.stop if levels else None,
        take_profit_1=levels.tp1 if levels else None,
        take_profit_2=levels.tp2 if levels else None,
        risk_reward_1=round(levels.rr1, 2) if levels else None,
        risk_reward_2=round(levels.rr2, 2) if levels else None,
        atr=structure.atr,
        reasons=reasons,
        warnings=warnings,
        levels_basis=levels.basis if levels else {},
        confluences=tags if not blocked else [],
        order_flow=flow.to_dict(),
        structure=_structure_dict(structure),
        timeframes={
            "entry": {"tf": timeframe, "bias": structure.bias},
            "higher": {"tf": htf_name, "bias": htf_bias} if htf_name else None,
        },
        candles=_candles(bars),
        overlays=_overlays(structure, flow, bars),
        data=data,
        calendar_available=calendar_available,
        lean=clear,
        long_points=long_pts,
        short_points=short_pts,
    )
