"""Shared data types. Nothing here talks to a broker or the network."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass(frozen=True)
class Bar:
    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class Instrument:
    id: str
    name: str
    category: str
    yahoo: str
    oanda: str | None
    pip: float
    digits: int
    currencies: tuple[str, ...]
    psych_step: float
    spread: float
    slippage: float
    aliases: tuple[str, ...] = ()

    def format_price(self, price: float | None) -> str:
        if price is None:
            return "—"
        return f"{price:.{self.digits}f}"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "yahoo": self.yahoo,
            "oanda": self.oanda,
            "pip": self.pip,
            "digits": self.digits,
            "currencies": list(self.currencies),
            "psych_step": self.psych_step,
            "spread": self.spread,
            "slippage": self.slippage,
            "aliases": list(self.aliases),
        }


@dataclass(frozen=True)
class MarketSnapshot:
    bars: list[Bar]
    source: str
    provider_symbol: str
    delay_note: str
    as_of: datetime | None


class DataUnavailable(Exception):
    """Raised when a feed cannot be read. Callers must not invent numbers."""

    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


@dataclass
class Swing:
    index: int
    time: datetime
    kind: str  # high | low
    price: float


@dataclass
class FairValueGap:
    direction: str  # bullish | bearish
    bottom: float
    top: float
    index: int
    time: datetime
    mitigated: bool


@dataclass
class OrderBlock:
    direction: str  # bullish | bearish
    low: float
    high: float
    index: int
    time: datetime
    mitigated: bool


@dataclass
class LiquidityLevel:
    price: float
    kind: str
    label: str


@dataclass
class Sweep:
    direction: str  # bullish sweep (of lows) | bearish sweep (of highs)
    level: float
    extreme: float
    index: int
    label: str


@dataclass
class SessionRange:
    name: str
    start: datetime
    end: datetime
    high: float
    low: float
    complete: bool


@dataclass
class Structure:
    bias: str
    swings: list[Swing] = field(default_factory=list)
    bos: str | None = None
    choch: str | None = None
    last_swing_high: Swing | None = None
    last_swing_low: Swing | None = None
    dealing_high: float | None = None
    dealing_low: float | None = None
    equilibrium: float | None = None
    zone: str | None = None
    ote: str | None = None
    fvgs: list[FairValueGap] = field(default_factory=list)
    order_blocks: list[OrderBlock] = field(default_factory=list)
    liquidity: list[LiquidityLevel] = field(default_factory=list)
    sweeps: list[Sweep] = field(default_factory=list)
    sessions: list[SessionRange] = field(default_factory=list)
    atr: float = 0.0
    killzone: str | None = None
    psych_level: float | None = None
    psych_near: bool = False


@dataclass
class OrderFlowEstimate:
    available: bool
    kind: str  # estimate | tick | none
    method: str
    reason: str = ""
    note: str = ""
    cumulative_delta: float | None = None
    delta_ratio: float | None = None
    volume_spike: bool = False
    last_bar_direction: str | None = None
    absorption: str | None = None
    poc: float | None = None
    hvns: list[float] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "available": self.available,
            "kind": self.kind,
            "method": self.method,
            "reason": self.reason,
            "note": self.note,
            "cumulative_delta": self.cumulative_delta,
            "delta_ratio": self.delta_ratio,
            "volume_spike": self.volume_spike,
            "last_bar_direction": self.last_bar_direction,
            "absorption": self.absorption,
            "poc": self.poc,
            "hvns": self.hvns,
        }


@dataclass
class Levels:
    entry: float
    stop: float
    tp1: float
    tp2: float
    rr1: float
    rr2: float
    basis: dict


@dataclass
class CalendarEvent:
    title: str
    currency: str
    impact: str
    time: datetime
    forecast: str
    previous: str


@dataclass
class Reason:
    text: str
    tag: str
    side: str  # long | short | info
    points: float

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "tag": self.tag,
            "side": self.side,
            "points": self.points,
        }


@dataclass
class Position:
    id: int | None
    symbol: str
    side: str
    qty: float
    qty_initial: float
    entry: float
    sl: float
    initial_sl: float
    tp1: float
    tp2: float
    tp1_hit: bool
    opened_at: datetime
    trail_distance: float | None
    sl_kind: str
    risk_amount: float
    last_mid: float | None = None
    last_bar_time: datetime | None = None
    realized: float = 0.0
    status: str = "open"
    closed_at: datetime | None = None
    exit_price: float | None = None
    exit_reason: str | None = None
    signal_id: int | None = None
    note: str = ""

    @property
    def pnl(self) -> float | None:
        if self.status != "closed":
            return None
        return self.realized


@dataclass
class AccountState:
    balance: float
    starting_balance: float
    day: date | None
    day_start: float
    realized_today: float
    paused: bool
    positions: list[Position] = field(default_factory=list)

    def open_positions(self) -> list[Position]:
        return [p for p in self.positions if p.status == "open"]


@dataclass
class Execution:
    kind: str  # open | partial | close | reject
    message: str
    position: Position | None
    pnl: float | None
