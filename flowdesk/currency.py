"""Account currency: converts P&L / position size from each instrument's quote currency into the account
currency (default EUR) with live FX rates from the market-data provider, plus a one-time migration of an
existing journal that was kept in USD.

Rates are cached for a few minutes; the last known rate for every pair is also stored in the journal so a
data outage falls back to it. If no rate has ever been seen, callers get None (the bot then skips the entry
rather than guessing a number)."""
from __future__ import annotations
import logging
import shutil
import threading
import time

import pandas as pd

from . import instruments

log = logging.getLogger("flowdesk.currency")

SYMBOL = {"EUR": "€", "USD": "$", "GBP": "£", "JPY": "¥", "CHF": "CHF ", "AUD": "A$", "CAD": "C$", "NZD": "NZ$"}
# non-forex instruments that are not priced in USD (everything else in the catalog is USD)
QUOTE_OVERRIDE = {"^GDAXI": "EUR", "^STOXX50E": "EUR", "^FCHI": "EUR", "^FTSE": "GBP", "^N225": "JPY", "^HSI": "HKD"}


def symbol_for(ccy: str) -> str:
    return SYMBOL.get((ccy or "").upper(), (ccy or "") + " ")


def quote_ccy(symbol: str) -> str:
    i = instruments.info(symbol)
    if i["category"] == "Forex":
        return i["symbol"].replace("=X", "")[3:6]
    return QUOTE_OVERRIDE.get(i["symbol"], "USD")


class FxConverter:
    def __init__(self, provider, journal=None, ttl: float = 600):
        self.p, self.j, self.ttl = provider, journal, ttl
        self._cache: dict = {}
        self._lock = threading.Lock()

    # ---- raw series ----
    def _series(self, ticker: str, tf: str) -> pd.Series | None:
        key = (ticker, tf)
        with self._lock:
            hit = self._cache.get(key)
            if hit and time.time() - hit[0] < self.ttl:
                return hit[1]
        try:
            df = self.p.candles(ticker, tf)
            s = df["close"].astype(float).dropna()
            s = s[s > 0]
            if s.empty:
                s = None
        except Exception as e:  # DataUnavailable, network...
            log.info("fx %s %s unavailable: %s", ticker, tf, e)
            s = None
        with self._lock:
            self._cache[key] = (time.time(), s)
        return s

    @staticmethod
    def _at(s: pd.Series, ts: int | None) -> float | None:
        if s is None or s.empty:
            return None
        if ts is None:
            return float(s.iloc[-1])
        t = pd.Timestamp(int(ts), unit="s", tz="UTC")
        i = s.index.searchsorted(t, side="right") - 1      # last bar at or before ts, else the nearest (first) bar
        return float(s.iloc[max(0, i)])

    def _pair(self, a: str, b: str, ts: int | None) -> float | None:
        """Price of 1 unit of a in b from a Yahoo pair (direct or inverse)."""
        old = ts is not None and ts < time.time() - 170 * 86400   # the 1h history covers ~180 days
        for tf in (("1d",) if old else ("1h", "1d")):
            for tk, inv in ((f"{a}{b}=X", False), (f"{b}{a}=X", True)):
                v = self._at(self._series(tk, tf), ts)
                if v:
                    return 1.0 / v if inv else v
        return None

    def rate(self, a: str, b: str, ts: int | None = None) -> float | None:
        """Multiplier converting an amount in currency a into currency b (at ts, or now)."""
        a, b = a.upper(), b.upper()
        if a == b:
            return 1.0
        r = self._pair(a, b, ts)
        if r is None and "USD" not in (a, b):
            r1, r2 = self._pair(a, "USD", ts), self._pair("USD", b, ts)
            r = r1 * r2 if r1 and r2 else None
        k = f"fx_last_{a}{b}"
        if r is not None:
            if ts is None and self.j is not None:
                self.j.set(k, {"rate": r, "ts": int(time.time())})
            return r
        last = self.j.get(k) if self.j is not None else None
        if last:
            log.warning("fx %s->%s unavailable, using last known %.6f from %s", a, b, last["rate"], last["ts"])
            return float(last["rate"])
        return None

    def mult(self, symbol: str, price: float | None, account: str, ts: int | None = None) -> float | None:
        """Account-currency value of a 1.0 P&L in the instrument's quote currency."""
        account = account.upper()
        q = quote_ccy(symbol)
        if q == account:
            return 1.0
        i = instruments.info(symbol)
        if i["category"] == "Forex" and price and i["symbol"].replace("=X", "")[:3] == account:
            return 1.0 / price          # e.g. EURUSD in a EUR account: USD -> EUR at the pair's own price
        return self.rate(q, account, ts)


def migrate(j, fx: FxConverter, target: str, start_balance: float) -> dict | None:
    """Convert a journal kept in another currency (legacy = USD) to `target`, each amount at the FX rate of
    its own time (nearest available bar). Balance = starting balance (now in target) + converted realized P&L.
    Makes a backup copy of the database first. Returns a summary, or None if nothing had to be done."""
    target = target.upper()
    cur = (j.get("account_currency") or "").upper()
    has_trades = bool(j.q("SELECT 1 FROM trades LIMIT 1"))
    if cur == target:
        return None
    if not cur and not has_trades:
        j.set("account_currency", target)
        j.set("balance", float(start_balance)) if j.get("balance") is None else None
        return None
    cur = cur or "USD"
    now = int(time.time())
    r_now = fx.rate(cur, target)
    if r_now is None:
        raise RuntimeError(f"no {cur}->{target} rate available yet; journal left in {cur}")
    if j.path != ":memory:":
        bak = f"{j.path}.bak-{cur.lower()}-{now}"
        with j._lock:
            j.db.commit()
            dst = __import__("sqlite3").connect(bak)
            j.db.backup(dst)
            dst.close()
        log.info("journal backup before currency migration: %s", bak)
    R = lambda ts: (fx.rate(cur, target, int(ts)) if ts else None) or r_now
    with j._lock:
        db = j.db
        db.execute("BEGIN IMMEDIATE")
        try:
            row = db.execute("SELECT v FROM kv WHERE k='account_currency'").fetchone()
            if row and __import__("json").loads(row[0]).upper() == target:
                db.rollback()
                return None
            fills = db.execute("SELECT id, trade_id, ts, pnl_usd FROM fills ORDER BY ts, id").fetchall()
            per_trade, conv = {}, []
            for f in fills:
                v = (f["pnl_usd"] or 0.0) * R(f["ts"])
                conv.append((f["ts"], v))
                db.execute("UPDATE fills SET pnl_usd=? WHERE id=?", (v, f["id"]))
                per_trade[f["trade_id"]] = per_trade.get(f["trade_id"], 0.0) + v
            for t in db.execute("SELECT id, status, opened_ts, risk_usd, usd_mult, fees_usd FROM trades").fetchall():
                r_open = R(t["opened_ts"])
                r_mult = R(None) if t["status"] == "open" else r_open
                db.execute("UPDATE trades SET risk_usd=?, usd_mult=?, fees_usd=?, pnl_usd=? WHERE id=?",
                           ((t["risk_usd"] or 0) * r_open, (t["usd_mult"] or 1.0) * r_mult, (t["fees_usd"] or 0) * r_open,
                            per_trade.get(t["id"], 0.0), t["id"]))
            # equity history: rebuild balance from the converted fills, keep the open P&L part converted at its time
            k, cum = 0, 0.0
            for e in db.execute("SELECT ts, balance, equity FROM equity ORDER BY ts").fetchall():
                while k < len(conv) and conv[k][0] <= e["ts"]:
                    cum += conv[k][1]; k += 1
                bal = float(start_balance) + cum
                db.execute("UPDATE equity SET balance=?, equity=? WHERE ts=?",
                           (bal, bal + ((e["equity"] or 0) - (e["balance"] or 0)) * R(e["ts"]), e["ts"]))
            new_bal = float(start_balance) + sum(v for _, v in conv)
            js = __import__("json").dumps
            db.execute("INSERT INTO kv(k,v) VALUES('balance',?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (js(new_bal),))
            db.execute("INSERT INTO kv(k,v) VALUES('account_currency',?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (js(target),))
            summary = {"from": cur, "to": target, "ts": now, "fills": len(conv), "balance": round(new_bal, 2),
                       "rate_now": round(R(None), 6)}
            db.execute("INSERT INTO kv(k,v) VALUES('currency_migration',?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (js(summary),))
            db.commit()
        except Exception:
            db.rollback()
            raise
    log.info("journal converted %s -> %s: %s", cur, target, summary)
    return summary


def stored_ccy(j, default: str = "EUR") -> str:
    """Currency the journal's money columns are in (legacy journals without the marker are USD)."""
    c = j.get("account_currency")
    if c:
        return str(c).upper()
    return "USD" if j.q("SELECT 1 FROM trades LIMIT 1") else default.upper()


def fmt_money(v: float | None, ccy: str = "EUR", sign: bool = True, dp: int | None = 2) -> str:
    """'+€12.40' / '-€3.10' / '€50.00' style for Telegram replies; dp=None -> no decimals from 100 up ('€1,630')."""
    if v is None:
        return "-"
    s = symbol_for(ccy)
    pre = "-" if v < 0 else ("+" if sign and v > 0 else "")
    if dp is None:
        dp = 0 if abs(v) >= 100 else 2
    return f"{pre}{s}{abs(v):,.{dp}f}"


def account_ccy(cfg: dict | None = None) -> str:
    from .config import get_config
    c = cfg if cfg is not None else get_config()
    return str((c.get("broker") or {}).get("account_currency", "EUR")).upper()
