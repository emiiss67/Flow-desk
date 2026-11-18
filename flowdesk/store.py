"""SQLite journal for signals, paper trades, and the account."""

from __future__ import annotations

import json
import sqlite3
from datetime import date as date_cls
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flowdesk.models import AccountState, Position
from flowdesk.strategy import CheckResult

SCHEMA = """
CREATE TABLE IF NOT EXISTS account (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    balance REAL NOT NULL,
    starting_balance REAL NOT NULL,
    day TEXT,
    day_start REAL NOT NULL,
    realized_today REAL NOT NULL,
    paused INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    qty REAL NOT NULL,
    qty_initial REAL NOT NULL,
    entry REAL NOT NULL,
    sl REAL NOT NULL,
    initial_sl REAL NOT NULL,
    tp1 REAL NOT NULL,
    tp2 REAL NOT NULL,
    tp1_hit INTEGER NOT NULL DEFAULT 0,
    opened_at TEXT NOT NULL,
    closed_at TEXT,
    exit_price REAL,
    exit_reason TEXT,
    trail_distance REAL,
    sl_kind TEXT NOT NULL,
    risk_amount REAL NOT NULL,
    last_mid REAL,
    last_bar_time TEXT,
    realized REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    signal_id INTEGER,
    note TEXT
);
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    call TEXT NOT NULL,
    confidence INTEGER,
    entry REAL,
    stop_loss REAL,
    tp1 REAL,
    tp2 REAL,
    rr REAL,
    reasons_json TEXT,
    warnings_json TEXT,
    source TEXT,
    acted INTEGER NOT NULL DEFAULT 0,
    payload_json TEXT
);
CREATE TABLE IF NOT EXISTS equity (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    balance REAL NOT NULL,
    equity REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS kv (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class Store:
    def __init__(self, path: str, starting_balance: float = 10000.0):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.starting_balance = starting_balance
        with self._connect() as conn:
            conn.executescript(SCHEMA)
            row = conn.execute("SELECT id FROM account WHERE id = 1").fetchone()
            if row is None:
                now = _iso(datetime.now(timezone.utc))
                conn.execute(
                    """
                    INSERT INTO account (id, balance, starting_balance, day, day_start, realized_today, paused)
                    VALUES (1, ?, ?, NULL, ?, 0, 0)
                    """,
                    (starting_balance, starting_balance, starting_balance),
                )
                conn.execute(
                    "INSERT INTO equity (ts, balance, equity) VALUES (?, ?, ?)",
                    (now, starting_balance, starting_balance),
                )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def load_state(self) -> AccountState:
        with self._connect() as conn:
            account = conn.execute("SELECT * FROM account WHERE id = 1").fetchone()
            rows = conn.execute("SELECT * FROM trades WHERE status = 'open' ORDER BY id").fetchall()
        day = date_cls.fromisoformat(account["day"]) if account["day"] else None
        return AccountState(
            balance=account["balance"],
            starting_balance=account["starting_balance"],
            day=day,
            day_start=account["day_start"],
            realized_today=account["realized_today"],
            paused=bool(account["paused"]),
            positions=[self._position_from_row(row) for row in rows],
        )

    def persist(self, state: AccountState) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE account
                SET balance = ?, day = ?, day_start = ?, realized_today = ?, paused = ?
                WHERE id = 1
                """,
                (
                    state.balance,
                    state.day.isoformat() if state.day else None,
                    state.day_start,
                    state.realized_today,
                    1 if state.paused else 0,
                ),
            )
            for position in state.positions:
                self._upsert_position(conn, position)

    def _upsert_position(self, conn: sqlite3.Connection, position: Position) -> None:
        values = (
            position.symbol,
            position.side,
            position.qty,
            position.qty_initial,
            position.entry,
            position.sl,
            position.initial_sl,
            position.tp1,
            position.tp2,
            1 if position.tp1_hit else 0,
            _iso(position.opened_at),
            _iso(position.closed_at),
            position.exit_price,
            position.exit_reason,
            position.trail_distance,
            position.sl_kind,
            position.risk_amount,
            position.last_mid,
            _iso(position.last_bar_time),
            position.realized,
            position.status,
            position.signal_id,
            position.note,
        )
        if position.id is None:
            cursor = conn.execute(
                """
                INSERT INTO trades (
                    symbol, side, qty, qty_initial, entry, sl, initial_sl, tp1, tp2, tp1_hit,
                    opened_at, closed_at, exit_price, exit_reason, trail_distance, sl_kind,
                    risk_amount, last_mid, last_bar_time, realized, status, signal_id, note
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
            position.id = int(cursor.lastrowid)
        else:
            conn.execute(
                """
                UPDATE trades SET
                    symbol=?, side=?, qty=?, qty_initial=?, entry=?, sl=?, initial_sl=?, tp1=?, tp2=?,
                    tp1_hit=?, opened_at=?, closed_at=?, exit_price=?, exit_reason=?, trail_distance=?,
                    sl_kind=?, risk_amount=?, last_mid=?, last_bar_time=?, realized=?, status=?,
                    signal_id=?, note=?
                WHERE id=?
                """,
                (*values, position.id),
            )

    def _position_from_row(self, row: sqlite3.Row) -> Position:
        return Position(
            id=row["id"],
            symbol=row["symbol"],
            side=row["side"],
            qty=row["qty"],
            qty_initial=row["qty_initial"],
            entry=row["entry"],
            sl=row["sl"],
            initial_sl=row["initial_sl"],
            tp1=row["tp1"],
            tp2=row["tp2"],
            tp1_hit=bool(row["tp1_hit"]),
            opened_at=_parse(row["opened_at"]) or datetime.now(timezone.utc),
            trail_distance=row["trail_distance"],
            sl_kind=row["sl_kind"],
            risk_amount=row["risk_amount"],
            last_mid=row["last_mid"],
            last_bar_time=_parse(row["last_bar_time"]),
            realized=row["realized"] or 0.0,
            status=row["status"],
            closed_at=_parse(row["closed_at"]),
            exit_price=row["exit_price"],
            exit_reason=row["exit_reason"],
            signal_id=row["signal_id"],
            note=row["note"] or "",
        )

    def add_signal(self, result: CheckResult, source: str, acted: bool = False) -> int:
        payload = result.to_dict()
        payload.pop("candles", None)
        payload.pop("overlays", None)
        now = _iso(datetime.now(timezone.utc))
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO signals (
                    ts, symbol, timeframe, call, confidence, entry, stop_loss, tp1, tp2, rr,
                    reasons_json, warnings_json, source, acted, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    now,
                    result.symbol,
                    result.timeframe,
                    result.call,
                    result.confidence,
                    result.entry,
                    result.stop_loss,
                    result.take_profit_1,
                    result.take_profit_2,
                    result.risk_reward_1,
                    json.dumps([reason.to_dict() for reason in result.reasons]),
                    json.dumps(result.warnings),
                    source,
                    1 if acted else 0,
                    json.dumps(payload),
                ),
            )
            return int(cursor.lastrowid)

    def mark_signal_acted(self, signal_id: int) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE signals SET acted = 1 WHERE id = ?", (signal_id,))

    def list_signals(self, limit: int = 50) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM signals ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._signal_dict(row) for row in rows]

    def _signal_dict(self, row: sqlite3.Row) -> dict:
        return {
            "id": row["id"],
            "ts": row["ts"],
            "symbol": row["symbol"],
            "timeframe": row["timeframe"],
            "call": row["call"],
            "confidence": row["confidence"],
            "entry": row["entry"],
            "stop_loss": row["stop_loss"],
            "tp1": row["tp1"],
            "tp2": row["tp2"],
            "rr": row["rr"],
            "reasons": json.loads(row["reasons_json"] or "[]"),
            "warnings": json.loads(row["warnings_json"] or "[]"),
            "source": row["source"],
            "acted": bool(row["acted"]),
        }

    def list_trades(self, limit: int = 100, status: str | None = None) -> list[dict]:
        query = "SELECT * FROM trades"
        args: list = []
        if status:
            query += " WHERE status = ?"
            args.append(status)
        query += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, args).fetchall()
        return [self._trade_dict(row) for row in rows]

    def _trade_dict(self, row: sqlite3.Row) -> dict:
        realized = row["realized"] or 0.0
        return {
            "id": row["id"],
            "symbol": row["symbol"],
            "side": row["side"],
            "qty": row["qty"],
            "qty_initial": row["qty_initial"],
            "entry": row["entry"],
            "sl": row["sl"],
            "initial_sl": row["initial_sl"],
            "tp1": row["tp1"],
            "tp2": row["tp2"],
            "tp1_hit": bool(row["tp1_hit"]),
            "opened_at": row["opened_at"],
            "closed_at": row["closed_at"],
            "exit_price": row["exit_price"],
            "exit_reason": row["exit_reason"],
            "trail_distance": row["trail_distance"],
            "sl_kind": row["sl_kind"],
            "risk_amount": row["risk_amount"],
            "last_mid": row["last_mid"],
            "realized": realized,
            "pnl": realized if row["status"] == "closed" else None,
            "status": row["status"],
            "signal_id": row["signal_id"],
            "note": row["note"] or "",
            "r_multiple": (realized / row["risk_amount"]) if row["status"] == "closed" and row["risk_amount"] else None,
        }

    def snapshot_equity(self, balance: float, equity: float, now: datetime | None = None, min_seconds: int = 900) -> None:
        moment = now or datetime.now(timezone.utc)
        with self._connect() as conn:
            last = conn.execute("SELECT ts FROM equity ORDER BY id DESC LIMIT 1").fetchone()
            if last:
                previous = _parse(last["ts"])
                if previous and (moment - previous).total_seconds() < min_seconds:
                    return
            conn.execute(
                "INSERT INTO equity (ts, balance, equity) VALUES (?, ?, ?)",
                (_iso(moment), balance, equity),
            )

    def equity_curve(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute("SELECT ts, balance, equity FROM equity ORDER BY id").fetchall()
        return [{"t": row["ts"], "balance": row["balance"], "equity": row["equity"]} for row in rows]

    def get_kv(self, key: str, default: str | None = None) -> str | None:
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
        if row is None:
            return default
        return row["value"]

    def set_kv(self, key: str, value: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO kv (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    def is_paused(self) -> bool:
        with self._connect() as conn:
            row = conn.execute("SELECT paused FROM account WHERE id = 1").fetchone()
        return bool(row["paused"]) if row else False

    def set_paused(self, paused: bool) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE account SET paused = ? WHERE id = 1", (1 if paused else 0,))

    def performance(self) -> dict:
        with self._connect() as conn:
            account = conn.execute("SELECT * FROM account WHERE id = 1").fetchone()
            closed = conn.execute(
                "SELECT * FROM trades WHERE status = 'closed' ORDER BY closed_at"
            ).fetchall()
            curve = conn.execute("SELECT ts, balance, equity FROM equity ORDER BY id").fetchall()
        starting = account["starting_balance"]
        wins = [row for row in closed if (row["realized"] or 0) > 0]
        losses = [row for row in closed if (row["realized"] or 0) < 0]
        net = sum((row["realized"] or 0) for row in closed)
        gross_win = sum(row["realized"] for row in wins)
        gross_loss = abs(sum(row["realized"] for row in losses))
        win_rate = (len(wins) / (len(wins) + len(losses)) * 100) if (wins or losses) else None
        profit_factor = (gross_win / gross_loss) if gross_loss > 0 else None
        r_values = [
            (row["realized"] or 0) / row["risk_amount"]
            for row in closed
            if row["risk_amount"]
        ]
        avg_r = sum(r_values) / len(r_values) if r_values else None
        peak = starting
        max_dd = 0.0
        max_dd_pct = 0.0
        points = []
        for row in curve:
            equity = row["equity"]
            peak = max(peak, equity)
            drawdown = peak - equity
            if drawdown > max_dd:
                max_dd = drawdown
                max_dd_pct = (drawdown / peak * 100) if peak else 0.0
            points.append({"t": row["ts"], "balance": row["balance"], "equity": equity})
        if not points:
            points = [{"t": _iso(datetime.now(timezone.utc)), "balance": starting, "equity": starting}]
        weekday = [{"day": name, "pnl": 0.0, "trades": 0} for name in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")]
        for row in closed:
            closed_at = _parse(row["closed_at"])
            if not closed_at:
                continue
            bucket = weekday[closed_at.weekday()]
            bucket["pnl"] += row["realized"] or 0
            bucket["trades"] += 1
        streak = []
        for row in closed[-12:]:
            pnl = row["realized"] or 0
            streak.append("W" if pnl > 0 else "L" if pnl < 0 else "B")
        last = [self._trade_dict(row) for row in list(reversed(closed))[:20]]
        return {
            "paper": True,
            "starting_balance": starting,
            "balance": account["balance"],
            "net": net,
            "win_rate": win_rate,
            "profit_factor": profit_factor,
            "profit_factor_note": None if profit_factor is not None or not closed else None,
            "no_losses": bool(closed) and gross_loss == 0 and gross_win > 0,
            "max_drawdown": max_dd,
            "max_drawdown_pct": max_dd_pct,
            "trades": len(closed),
            "wins": len(wins),
            "losses": len(losses),
            "avg_r": avg_r,
            "equity": points,
            "by_weekday": weekday,
            "last_trades": last,
            "streak": streak,
        }

    def dashboard(self) -> dict:
        perf = self.performance()
        now = datetime.now(timezone.utc)
        start = (now - timedelta(days=30)).isoformat()
        with self._connect() as conn:
            account = conn.execute("SELECT * FROM account WHERE id = 1").fetchone()
            recent = conn.execute(
                "SELECT realized FROM trades WHERE status = 'closed' AND closed_at >= ?",
                (start,),
            ).fetchall()
            signals_today = conn.execute(
                "SELECT COUNT(*) AS n FROM signals WHERE ts >= ?",
                (now.date().isoformat(),),
            ).fetchone()["n"]
            trades_today = conn.execute(
                "SELECT COUNT(*) AS n FROM trades WHERE opened_at >= ?",
                (now.date().isoformat(),),
            ).fetchone()["n"]
            open_rows = conn.execute("SELECT * FROM trades WHERE status = 'open'").fetchall()
        net_30 = sum((row["realized"] or 0) for row in recent)
        limit = account["day_start"] * 0  # placeholder replaced by caller when settings are known
        unrealized = None
        if not open_rows:
            unrealized = 0.0
        status = "Paused" if account["paused"] else "Clean"
        return {
            "paper": True,
            "balance": account["balance"],
            "starting_balance": account["starting_balance"],
            "equity": None if unrealized is None else account["balance"] + unrealized,
            "unrealized": unrealized,
            "net_pnl": account["balance"] - account["starting_balance"],
            "net_pnl_30d": net_30,
            "open_positions": len(open_rows),
            "daily_realized": account["realized_today"],
            "day_start": account["day_start"],
            "paused": bool(account["paused"]),
            "win_rate": perf["win_rate"],
            "profit_factor": perf["profit_factor"],
            "no_losses": perf["no_losses"],
            "max_drawdown": perf["max_drawdown"],
            "max_drawdown_pct": perf["max_drawdown_pct"],
            "streak": perf["streak"],
            "last_trades": perf["last_trades"][:8],
            "signals_today": signals_today,
            "trades_today": trades_today,
            "status_today": status,
            "open_risk": sum((row["risk_amount"] or 0) * ((row["qty"] / row["qty_initial"]) if row["qty_initial"] else 0) for row in open_rows),
            "_limit_unused": limit,
        }
