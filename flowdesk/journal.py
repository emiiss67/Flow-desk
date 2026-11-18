"""SQLite journal: every signal and paper trade with plain-English reasons, plus bot state."""
from __future__ import annotations
import json
import sqlite3
import threading
import time
from pathlib import Path

from .config import data_dir

SCHEMA = """
CREATE TABLE IF NOT EXISTS signals (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, symbol TEXT, tf TEXT, decision TEXT, confidence REAL,
  price REAL, sl REAL, tp1 REAL, tp2 REAL, rr REAL, reasons TEXT, tags TEXT, acted INTEGER DEFAULT 0, note TEXT);
CREATE TABLE IF NOT EXISTS trades (
  id INTEGER PRIMARY KEY AUTOINCREMENT, signal_id INTEGER, symbol TEXT, tf TEXT, side TEXT, qty REAL, qty_open REAL,
  entry REAL, sl REAL, sl_initial REAL, tp1 REAL, tp2 REAL, risk_usd REAL, point_value REAL, usd_mult REAL,
  opened_ts INTEGER, closed_ts INTEGER, exit_price REAL, pnl_usd REAL DEFAULT 0, r_multiple REAL, status TEXT,
  tp1_hit INTEGER DEFAULT 0, exit_reason TEXT, reasons TEXT, tags TEXT, last_price REAL, atr REAL, fees_usd REAL DEFAULT 0);
CREATE TABLE IF NOT EXISTS fills (
  id INTEGER PRIMARY KEY AUTOINCREMENT, trade_id INTEGER, ts INTEGER, kind TEXT, price REAL, qty REAL, pnl_usd REAL);
CREATE TABLE IF NOT EXISTS equity (ts INTEGER PRIMARY KEY, balance REAL, equity REAL);
CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT);
"""


class Journal:
    def __init__(self, path: str | Path | None = None):
        self.path = str(path or data_dir() / "flowdesk.db")
        self._lock = threading.RLock()
        self.db = sqlite3.connect(self.path, check_same_thread=False, timeout=15)
        self.db.row_factory = sqlite3.Row
        if self.path != ":memory:":
            self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)
        self.db.commit()

    def q(self, sql: str, args=()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self.db.execute(sql, args).fetchall()]

    def x(self, sql: str, args=()) -> int:
        with self._lock:
            cur = self.db.execute(sql, args)
            self.db.commit()
            return cur.lastrowid

    # --- kv state ---
    def get(self, k: str, default=None):
        r = self.q("SELECT v FROM kv WHERE k=?", (k,))
        return json.loads(r[0]["v"]) if r else default

    def set(self, k: str, v) -> None:
        self.x("INSERT INTO kv(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, json.dumps(v)))

    # --- signals ---
    def add_signal(self, res: dict, acted: bool = False, note: str = "") -> int:
        lv = res.get("levels") or {}
        return self.x("INSERT INTO signals(ts,symbol,tf,decision,confidence,price,sl,tp1,tp2,rr,reasons,tags,acted,note)"
                      " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (int(time.time()), res["symbol"], res["tf"], res["decision"], res.get("confidence"),
                       res.get("price"), lv.get("sl"), lv.get("tp1"), lv.get("tp2"), lv.get("rr2"),
                       json.dumps([r["text"] for r in res.get("reasons", [])]),
                       json.dumps(sorted({r["tag"] for r in res.get("reasons", [])})), int(acted), note))

    def signals(self, limit: int = 100) -> list[dict]:
        rows = self.q("SELECT * FROM signals ORDER BY id DESC LIMIT ?", (limit,))
        for r in rows:
            r["reasons"] = json.loads(r["reasons"] or "[]")
            r["tags"] = json.loads(r["tags"] or "[]")
        return rows

    def trades(self, status: str | None = None, limit: int = 500) -> list[dict]:
        if status:
            rows = self.q("SELECT * FROM trades WHERE status=? ORDER BY id DESC LIMIT ?", (status, limit))
        else:
            rows = self.q("SELECT * FROM trades ORDER BY id DESC LIMIT ?", (limit,))
        for r in rows:
            r["reasons"] = json.loads(r["reasons"] or "[]")
            r["tags"] = json.loads(r["tags"] or "[]")
        return rows
