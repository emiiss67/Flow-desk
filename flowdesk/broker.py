"""Paper broker.

Fills exist only inside this ledger. Stops are checked against bar highs and
lows. If a stop and a target are both touched in the same bar, the stop wins.
"""

from __future__ import annotations

from datetime import datetime

from flowdesk.models import AccountState, Bar, Execution, Position


def signed_pnl(side: str, entry: float, exit_price: float, qty: float) -> float:
    if side == "long":
        return (exit_price - entry) * qty
    if side == "short":
        return (entry - exit_price) * qty
    raise ValueError(f"unknown side {side}")


class PaperBroker:
    def __init__(self, risk_pct: float, max_positions: int, daily_loss_limit_pct: float):
        self.risk_pct = risk_pct
        self.max_positions = max_positions
        self.daily_loss_limit_pct = daily_loss_limit_pct

    def roll_day(self, state: AccountState, now: datetime) -> None:
        day = now.date()
        if state.day != day:
            state.day = day
            state.day_start = state.balance
            state.realized_today = 0.0

    def entry_fill(self, side: str, mid: float, spread: float, slippage: float) -> float:
        half = spread / 2.0
        if side == "long":
            return mid + half + slippage
        if side == "short":
            return mid - half - slippage
        raise ValueError(side)

    def market_exit(self, side: str, mid: float, spread: float, slippage: float) -> float:
        half = spread / 2.0
        if side == "long":
            return mid - half - slippage
        if side == "short":
            return mid + half + slippage
        raise ValueError(side)

    def stop_fill(self, side: str, stop: float, slippage: float) -> float:
        if side == "long":
            return stop - slippage
        if side == "short":
            return stop + slippage
        raise ValueError(side)

    def quantity(self, balance: float, entry: float, stop_exit: float) -> float | None:
        risk = balance * (self.risk_pct / 100.0)
        distance = abs(entry - stop_exit)
        if distance <= 0 or risk <= 0:
            return None
        return risk / distance

    def unrealized(self, position: Position, mid: float, spread: float, slippage: float) -> float | None:
        if position.status != "open" or mid is None:
            return None
        exit_price = self.market_exit(position.side, mid, spread, slippage)
        return signed_pnl(position.side, position.entry, exit_price, position.qty)

    def open_position(
        self,
        state: AccountState,
        *,
        symbol: str,
        side: str,
        mid: float | None,
        sl: float,
        tp1: float,
        tp2: float,
        spread: float,
        slippage: float,
        now: datetime,
        trail_distance: float | None = None,
        signal_id: int | None = None,
        note: str = "",
        last_bar_time: datetime | None = None,
    ) -> Execution:
        self.roll_day(state, now)
        if state.paused:
            return Execution("reject", "paused", None, None)
        if len(state.open_positions()) >= self.max_positions:
            return Execution("reject", "max positions", None, None)
        limit = state.day_start * (self.daily_loss_limit_pct / 100.0)
        if state.realized_today <= -limit + 1e-9:
            return Execution("reject", "daily loss limit", None, None)
        if any(pos.symbol == symbol and pos.status == "open" for pos in state.positions):
            return Execution("reject", "already open", None, None)
        if mid is None or mid <= 0:
            return Execution("reject", "no price", None, None)
        if side not in ("long", "short"):
            return Execution("reject", "invalid stop", None, None)
        entry = self.entry_fill(side, mid, spread, slippage)
        stop_exit = self.stop_fill(side, sl, slippage)
        if side == "long" and not (sl < entry and stop_exit < entry and tp1 > entry and tp2 > tp1):
            return Execution("reject", "invalid stop", None, None)
        if side == "short" and not (sl > entry and stop_exit > entry and tp1 < entry and tp2 < tp1):
            return Execution("reject", "invalid stop", None, None)
        qty = self.quantity(state.balance, entry, stop_exit)
        if qty is None or qty <= 0:
            return Execution("reject", "invalid stop", None, None)
        risk_amount = abs(entry - stop_exit) * qty
        position = Position(
            id=None,
            symbol=symbol,
            side=side,
            qty=qty,
            qty_initial=qty,
            entry=entry,
            sl=sl,
            initial_sl=sl,
            tp1=tp1,
            tp2=tp2,
            tp1_hit=False,
            opened_at=now,
            trail_distance=trail_distance,
            sl_kind="initial",
            risk_amount=risk_amount,
            last_mid=mid,
            last_bar_time=last_bar_time,
            signal_id=signal_id,
            note=note,
        )
        state.positions.append(position)
        return Execution("open", "opened", position, 0.0)

    def close_market(
        self,
        state: AccountState,
        symbol: str,
        mid: float | None,
        spread: float,
        slippage: float,
        now: datetime,
    ) -> Execution:
        position = next((pos for pos in state.open_positions() if pos.symbol == symbol), None)
        if position is None:
            return Execution("reject", "no open position", None, None)
        if mid is None or mid <= 0:
            return Execution("reject", "no price", None, None)
        exit_price = self.market_exit(position.side, mid, spread, slippage)
        return self._close(state, position, exit_price, "manual", now)

    def on_bar(self, state: AccountState, symbol: str, bar: Bar, now: datetime, slippage: float) -> list[Execution]:
        self.roll_day(state, now)
        events: list[Execution] = []
        for position in list(state.open_positions()):
            if position.symbol != symbol:
                continue
            if position.last_bar_time is not None and bar.time <= position.last_bar_time:
                position.last_mid = bar.close
                continue
            position.last_mid = bar.close
            position.last_bar_time = bar.time
            events.extend(self._manage(state, position, bar, now, slippage))
        return events

    def _manage(self, state: AccountState, position: Position, bar: Bar, now: datetime, slippage: float) -> list[Execution]:
        if position.side == "long":
            stop_hit = bar.low <= position.sl
            tp1_hit = (not position.tp1_hit) and bar.high >= position.tp1
            tp2_hit = bar.high >= position.tp2
        else:
            stop_hit = bar.high >= position.sl
            tp1_hit = (not position.tp1_hit) and bar.low <= position.tp1
            tp2_hit = bar.low <= position.tp2
        # A target beyond TP2 implies TP1 was traded if it sits between entry and TP2.
        if tp2_hit and not position.tp1_hit:
            tp1_hit = True
        if stop_hit:
            reason = self._stop_reason(position)
            fill = self.stop_fill(position.side, position.sl, slippage)
            return [self._close(state, position, fill, reason, now)]
        events: list[Execution] = []
        if tp1_hit and tp2_hit:
            events.append(self._partial_tp1(state, position, now))
            if position.status == "open":
                events.append(self._close(state, position, position.tp2, "take-profit 2", now))
            return events
        if tp1_hit:
            events.append(self._partial_tp1(state, position, now))
        elif tp2_hit and position.tp1_hit:
            events.append(self._close(state, position, position.tp2, "take-profit 2", now))
            return events
        if position.status == "open" and position.trail_distance and position.trail_distance > 0:
            self._trail(position, bar)
        return events

    def _stop_reason(self, position: Position) -> str:
        if position.sl_kind == "trail":
            return "trailing stop"
        if position.sl_kind == "breakeven":
            return "breakeven stop"
        return "stop-loss"

    def _partial_tp1(self, state: AccountState, position: Position, now: datetime) -> Execution:
        qty = position.qty * 0.5
        pnl = signed_pnl(position.side, position.entry, position.tp1, qty)
        position.qty -= qty
        position.tp1_hit = True
        position.realized += pnl
        state.balance += pnl
        state.realized_today += pnl
        if position.side == "long":
            if position.entry > position.sl:
                position.sl = position.entry
                position.sl_kind = "breakeven"
        elif position.entry < position.sl:
            position.sl = position.entry
            position.sl_kind = "breakeven"
        return Execution("partial", "take-profit 1", position, pnl)

    def _trail(self, position: Position, bar: Bar) -> None:
        distance = position.trail_distance or 0.0
        if position.side == "long":
            candidate = bar.high - distance
            if candidate > position.sl:
                position.sl = candidate
                position.sl_kind = "trail"
        else:
            candidate = bar.low + distance
            if candidate < position.sl:
                position.sl = candidate
                position.sl_kind = "trail"

    def _close(self, state: AccountState, position: Position, exit_price: float, reason: str, now: datetime) -> Execution:
        pnl = signed_pnl(position.side, position.entry, exit_price, position.qty)
        state.balance += pnl
        state.realized_today += pnl
        position.realized += pnl
        position.qty = 0.0
        position.status = "closed"
        position.exit_price = exit_price
        position.exit_reason = reason
        position.closed_at = now
        return Execution("close", reason, position, pnl)
