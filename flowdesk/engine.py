"""Check and scan orchestration. Checking never opens a paper trade."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from flowdesk.broker import PaperBroker
from pathlib import Path

from flowdesk.catalog import load_catalog, resolve
from flowdesk.config import Settings, higher_timeframe, normalize_timeframe
from flowdesk.events import CalendarClient
from flowdesk.market import MarketRouter
from flowdesk.models import Bar, DataUnavailable, Instrument
from flowdesk.orderflow import estimate_orderflow
from flowdesk.store import Store
from flowdesk.strategy import CheckResult, evaluate_setup

log = logging.getLogger("flowdesk.engine")

TF_SECONDS = {"M5": 300, "M15": 900, "M30": 1800, "H1": 3600, "H4": 14400, "D1": 86400}


class AmbiguousSymbol(Exception):
    def __init__(self, candidates: list[Instrument]):
        self.candidates = candidates
        super().__init__("ambiguous symbol")


class UnknownSymbol(Exception):
    pass


def signal_bars(bars: list[Bar], timeframe: str, now: datetime) -> list[Bar]:
    duration = TF_SECONDS.get(timeframe, 900)
    closed = [bar for bar in bars if bar.time.timestamp() + duration <= now.timestamp() + 1]
    if closed:
        return closed
    return bars[:-1] if len(bars) > 1 else list(bars)


def closed_after(bars: list[Bar], timeframe: str, now: datetime, after: datetime | None) -> list[Bar]:
    closed = signal_bars(bars, timeframe, now)
    if after is None:
        return closed[-1:]
    fresh = [bar for bar in closed if bar.time > after]
    return fresh


class Runtime:
    def __init__(self, settings: Settings, store: Store | None = None, market: MarketRouter | None = None, calendar: CalendarClient | None = None):
        self.settings = settings
        catalog_file = Path(settings.catalog) if settings.catalog else None
        self.catalog = load_catalog(str(catalog_file) if catalog_file and catalog_file.exists() else None)
        self.store = store or Store(settings.database, settings.starting_balance)
        self.market = market or MarketRouter(settings.market_provider, settings.market_cache_seconds)
        cache_file = str(self.store.path.parent / "cache" / "ff_calendar.json")
        self.calendar = calendar or CalendarClient(
            settings.calendar_url,
            settings.calendar_cache_seconds,
            cache_file=cache_file,
        )
        self.broker = PaperBroker(
            settings.risk_per_trade_pct,
            settings.max_positions,
            settings.daily_loss_limit_pct,
        )

    def resolve(self, query: str) -> Instrument:
        instrument, candidates = resolve(query, self.catalog)
        if instrument is None and candidates:
            raise AmbiguousSymbol(candidates)
        if instrument is None:
            raise UnknownSymbol(query)
        return instrument


def run_check(
    runtime: Runtime,
    symbol: str,
    timeframe: str | None = None,
    *,
    source: str = "check",
    journal: bool = True,
    now: datetime | None = None,
) -> CheckResult:
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    tf = normalize_timeframe(timeframe, runtime.settings.scanner_timeframe)
    instrument = runtime.resolve(symbol)
    snapshot = runtime.market.fetch(instrument, tf, limit=400)
    bars = signal_bars(snapshot.bars, tf, moment)
    htf_name = higher_timeframe(tf)
    htf_bars = None
    htf_unavailable = False
    if htf_name:
        try:
            htf_snap = runtime.market.fetch(instrument, htf_name, limit=400)
            htf_bars = signal_bars(htf_snap.bars, htf_name, moment)
        except DataUnavailable:
            htf_unavailable = True
    events, calendar_ok = runtime.calendar.typed_events()
    flow = estimate_orderflow(bars)
    if instrument.category == "custom":
        delay = snapshot.delay_note + " Spread is not modeled for an unknown ticker (treated as 0)."
    else:
        delay = snapshot.delay_note
    result = evaluate_setup(
        bars,
        instrument=instrument,
        timeframe=tf,
        now=moment,
        htf_bars=htf_bars,
        htf_name=htf_name,
        events=events if calendar_ok else [],
        flow=flow,
        min_score=runtime.settings.min_score,
        blackout_minutes=runtime.settings.event_blackout_minutes,
        swing_left=runtime.settings.swing_left,
        swing_right=runtime.settings.swing_right,
        atr_period=runtime.settings.atr_period,
        min_bars=runtime.settings.min_bars,
        htf_unavailable=htf_unavailable,
        calendar_available=calendar_ok,
        data={
            "source": snapshot.source,
            "symbol": snapshot.provider_symbol,
            "delay": delay,
            "as_of": snapshot.as_of.astimezone(timezone.utc).isoformat() if snapshot.as_of else None,
            "spread": instrument.spread,
            "slippage": instrument.slippage,
        },
    )
    if journal:
        result.signal_id = runtime.store.add_signal(result, source=source, acted=False)
    return result


def _note(result: CheckResult) -> str:
    parts = [reason.text for reason in result.reasons if reason.points > 0][:4]
    return " ".join(parts)[:500]


def scan_once(runtime: Runtime, now: datetime | None = None) -> list[str]:
    """Update paper positions and maybe open new ones. Returns alert lines."""
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    settings = runtime.settings
    state = runtime.store.load_state()
    alerts: list[str] = []
    tf = settings.scanner_timeframe
    symbols = list(dict.fromkeys([pos.symbol for pos in state.open_positions()] + list(settings.watchlist)))
    snapshots = {}
    for symbol in symbols:
        try:
            instrument = runtime.resolve(symbol)
        except (AmbiguousSymbol, UnknownSymbol):
            log.warning("watchlist symbol %s is not in the catalog", symbol)
            continue
        try:
            snapshots[symbol] = (instrument, runtime.market.fetch(instrument, tf, limit=400))
        except DataUnavailable as exc:
            log.warning("data unavailable for %s: %s", symbol, exc.detail)
            continue
        if symbol not in {pos.symbol for pos in state.open_positions()}:
            continue
        instrument, snapshot = snapshots[symbol]
        for bar in closed_after(
            snapshot.bars,
            tf,
            moment,
            next((pos.last_bar_time for pos in state.open_positions() if pos.symbol == symbol), None),
        ):
            events = runtime.broker.on_bar(state, symbol, bar, bar.time, instrument.slippage)
            for event in events:
                if event.kind == "close" and event.position is not None:
                    pnl = event.pnl or 0
                    alerts.append(
                        f"PAPER EXIT {event.position.symbol} {event.message}\n"
                        f"{pnl:+.2f} {settings.currency}\n"
                        f"balance {state.balance:.2f}"
                    )
                elif event.kind == "partial" and event.position is not None:
                    alerts.append(
                        f"PAPER {event.position.symbol} take-profit 1\n"
                        f"{(event.pnl or 0):+.2f} {settings.currency} booked, stop to breakeven"
                    )
        if snapshot.bars:
            for position in state.open_positions():
                if position.symbol == symbol:
                    position.last_mid = snapshot.bars[-1].close
    # New signals after management, so a stop-out frees a slot in the same pass.
    if settings.scanner_enabled:
        for symbol in settings.watchlist:
            if symbol not in snapshots:
                continue
            instrument, snapshot = snapshots[symbol]
            if any(pos.symbol == symbol and pos.status == "open" for pos in state.positions):
                continue
            try:
                result = run_check(runtime, symbol, tf, source="scanner", journal=True, now=moment)
            except DataUnavailable as exc:
                log.warning("check failed for %s: %s", symbol, exc.detail)
                continue
            if (
                not settings.auto_trade
                or state.paused
                or result.call not in ("LONG", "SHORT")
                or result.blocked_by_event
                or not result.calendar_available
            ):
                continue
            if result.entry is None or result.stop_loss is None or result.take_profit_1 is None or result.take_profit_2 is None:
                continue
            side = "long" if result.call == "LONG" else "short"
            closed = signal_bars(snapshot.bars, tf, moment)
            anchor = closed[-1] if closed else snapshot.bars[-1]
            trail = None
            if settings.trailing_enabled and settings.trail_atr_mult > 0 and result.atr:
                trail = result.atr * settings.trail_atr_mult
            opened = runtime.broker.open_position(
                state,
                symbol=instrument.id,
                side=side,
                mid=anchor.close,
                sl=result.stop_loss,
                tp1=result.take_profit_1,
                tp2=result.take_profit_2,
                spread=instrument.spread,
                slippage=instrument.slippage,
                now=moment,
                trail_distance=trail,
                note=_note(result),
                last_bar_time=anchor.time,
            )
            if opened.kind == "open" and opened.position is not None:
                signal_id = getattr(result, "signal_id", None)
                if signal_id:
                    opened.position.signal_id = signal_id
                    runtime.store.mark_signal_acted(signal_id)
                alerts.append(
                    f"PAPER {result.call} {instrument.id} {tf}\n"
                    f"entry {instrument.format_price(opened.position.entry)}\n"
                    f"SL {instrument.format_price(opened.position.sl)}\n"
                    f"TP1 {instrument.format_price(opened.position.tp1)} ({result.risk_reward_1}R)\n"
                    f"TP2 {instrument.format_price(opened.position.tp2)}\n"
                    f"score {result.confidence}"
                )
            else:
                log.info("did not open %s: %s", symbol, opened.message)
    state.paused = runtime.store.is_paused()
    runtime.store.persist(state)
    equity = state.balance
    marks_known = True
    for position in state.open_positions():
        instrument = snapshots.get(position.symbol, (None, None))[0]
        if instrument is None or position.last_mid is None:
            marks_known = False
            break
        unreal = runtime.broker.unrealized(position, position.last_mid, instrument.spread, instrument.slippage)
        if unreal is None:
            marks_known = False
            break
        equity += unreal
    if marks_known:
        runtime.store.snapshot_equity(state.balance, equity, moment)
    runtime.store.set_kv("last_scan_at", moment.isoformat())
    alerts.extend(event_alerts(runtime, moment))
    return alerts


def event_alerts(runtime: Runtime, now: datetime) -> list[str]:
    events, ok = runtime.calendar.typed_events()
    if not ok:
        return []
    window = runtime.settings.event_alert_minutes
    sent_raw = runtime.store.get_kv("alerted_events", "[]")
    try:
        import json

        sent = set(json.loads(sent_raw or "[]"))
    except json.JSONDecodeError:
        sent = set()
    lines = []
    watch = []
    for symbol in runtime.settings.watchlist:
        try:
            watch.append(runtime.resolve(symbol))
        except (AmbiguousSymbol, UnknownSymbol):
            continue
    for event in events:
        if event.impact.lower() != "high":
            continue
        minutes = (event.time - now).total_seconds() / 60.0
        if minutes < 0 or minutes > window:
            continue
        affected = [inst.id for inst in watch if event.currency.upper() in inst.currencies]
        if not affected:
            continue
        key = f"{event.currency}|{event.title}|{event.time.isoformat()}"
        if key in sent:
            continue
        when = event.time.astimezone(timezone.utc).strftime("%H:%M UTC")
        lines.append(
            f"EVENT {event.currency} {event.title} at {when} ({int(round(minutes))}m)\n"
            f"blackout for {', '.join(affected)}"
        )
        sent.add(key)
    if lines:
        import json

        runtime.store.set_kv("alerted_events", json.dumps(list(sent)[-500:]))
    return lines


def manual_close(runtime: Runtime, symbol: str, now: datetime | None = None) -> tuple[bool, str]:
    moment = now or datetime.now(timezone.utc)
    try:
        instrument = runtime.resolve(symbol)
    except AmbiguousSymbol as exc:
        names = ", ".join(item.id for item in exc.candidates[:8])
        return False, f"Ambiguous symbol. Candidates: {names}"
    except UnknownSymbol:
        return False, "Unknown symbol."
    try:
        snapshot = runtime.market.fetch(instrument, runtime.settings.scanner_timeframe, limit=5)
    except DataUnavailable as exc:
        return False, f"data unavailable ({exc.detail})"
    if not snapshot.bars:
        return False, "data unavailable (no candles)"
    state = runtime.store.load_state()
    closed = runtime.broker.close_market(
        state,
        instrument.id,
        snapshot.bars[-1].close,
        instrument.spread,
        instrument.slippage,
        moment,
    )
    if closed.kind != "close" or closed.position is None:
        return False, closed.message
    runtime.store.persist(state)
    pnl = closed.pnl or 0
    return True, (
        f"Closed {instrument.id} at {instrument.format_price(closed.position.exit_price)}\n"
        f"pnl {pnl:+.2f} {runtime.settings.currency}\n"
        f"balance {state.balance:.2f}"
    )


def account_view(runtime: Runtime) -> dict:
    state = runtime.store.load_state()
    positions = []
    unrealized_total = 0.0
    unrealized_known = True
    for position in state.open_positions():
        try:
            instrument = runtime.resolve(position.symbol)
        except (AmbiguousSymbol, UnknownSymbol):
            instrument = None
        unrealized = None
        if instrument and position.last_mid is not None:
            unrealized = runtime.broker.unrealized(position, position.last_mid, instrument.spread, instrument.slippage)
            if unrealized is None:
                unrealized_known = False
            else:
                unrealized_total += unrealized
        else:
            unrealized_known = False
        positions.append(
            {
                "id": position.id,
                "symbol": position.symbol,
                "side": position.side,
                "qty": position.qty,
                "entry": position.entry,
                "sl": position.sl,
                "tp1": position.tp1,
                "tp2": position.tp2,
                "tp1_hit": position.tp1_hit,
                "opened_at": position.opened_at.isoformat(),
                "last_mid": position.last_mid,
                "unrealized": unrealized,
                "trail_distance": position.trail_distance,
                "sl_kind": position.sl_kind,
                "risk_amount": position.risk_amount,
                "note": position.note,
            }
        )
    return {
        "paper": True,
        "balance": state.balance,
        "paused": state.paused,
        "unrealized": unrealized_total if unrealized_known else None,
        "positions": positions,
    }
