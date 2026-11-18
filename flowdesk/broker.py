"""Paper broker. Simulated fills only - there is no connection to any real broker.

All money (balance, risk_usd, pnl_usd, fills, equity) is kept in the ACCOUNT currency (broker.account_currency,
default EUR). The historical column names still say "usd"; `usd_mult` on a trade is the quote-currency ->
account-currency multiplier (see currency.py)."""
from __future__ import annotations
import json
import math
import time
from datetime import datetime, timezone

from . import instruments
from .journal import Journal


class PaperBroker:
    def __init__(self, journal: Journal, cfg: dict | None = None):
        self.j = journal
        c = cfg or {}
        self.start_balance = float(c.get("starting_balance", 50))      # in the account currency
        self.ccy = str(c.get("account_currency", "EUR")).upper()
        self.min_qty = float(c.get("min_qty", 0) or 0)
        self.qty_step = float(c.get("qty_step", 0) or 0)
        self.max_leverage = float(c.get("max_leverage", 30) or 0)
        self.risk_pct = float(c.get("risk_pct", 0.5))
        self.max_positions = int(c.get("max_positions", 4))
        self.max_per_symbol = int(c.get("max_per_symbol", 1))
        self.max_open_risk_pct = float(c.get("max_open_risk_pct", 0) or 0)
        self.last_reject = ""
        self.daily_loss_pct = float(c.get("daily_loss_limit_pct", 2.0))
        self.tp1_close = float(c.get("tp1_close_pct", 50)) / 100
        self.trail_atr = float(c.get("trail_atr", 1.0))
        self.spread_bps = c.get("spread_bps", {}) or {}
        self.slip_bps = float(c.get("slippage_bps", 0.5))
        if self.j.get("balance") is None:
            self.j.set("balance", self.start_balance)

    # ----- accounting -----
    @property
    def balance(self) -> float:
        return float(self.j.get("balance", self.start_balance))

    def open_trades(self) -> list[dict]:
        return self.j.trades("open")

    def unrealized(self) -> float:
        tot = 0.0
        for t in self.open_trades():
            if t["last_price"] is None:
                continue
            sgn = 1 if t["side"] == "LONG" else -1
            tot += (t["last_price"] - t["entry"]) * sgn * t["qty_open"] * t["point_value"] * t["usd_mult"]
        return tot

    def equity(self) -> float:
        return self.balance + self.unrealized()

    def realized_today(self) -> float:
        day0 = int(datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
        r = self.j.q("SELECT COALESCE(SUM(pnl_usd),0) s FROM fills WHERE ts>=?", (day0,))
        return float(r[0]["s"])

    def daily_limit_hit(self) -> bool:
        return self.realized_today() <= -self.balance_day_start() * self.daily_loss_pct / 100

    def balance_day_start(self) -> float:
        return self.balance - self.realized_today()

    # ----- price helpers -----
    def cost_bps(self, symbol: str) -> float:
        cat = instruments.category_key(symbol)
        return float(self.spread_bps.get(cat, self.spread_bps.get("other", 2.0))) / 2 + self.slip_bps

    def fill_price(self, symbol: str, side: str, price: float, opening: bool) -> float:
        """Half spread + slippage against us."""
        adj = price * self.cost_bps(symbol) / 1e4
        buying = (side == "LONG") == opening
        return price + adj if buying else price - adj

    @staticmethod
    def position_size(equity: float, risk_pct: float, entry: float, sl: float, point_value: float,
                      usd_mult: float = 1.0, max_leverage: float = 0.0, qty_step: float = 0.0,
                      min_qty: float = 0.0) -> float:
        """Units so that hitting the stop loses risk_pct of equity. Fractional sizes allowed.
        Returns 0.0 (no trade) for any invalid input or when the size would fall below min_qty."""
        vals = (equity, risk_pct, entry, sl, point_value, usd_mult)
        if any(v is None or not math.isfinite(v) for v in vals):
            return 0.0
        dist = abs(entry - sl)
        if equity <= 0 or risk_pct <= 0 or dist <= 0 or point_value <= 0 or usd_mult <= 0 or entry <= 0:
            return 0.0
        qty = (equity * risk_pct / 100) / (dist * point_value * usd_mult)
        if max_leverage and max_leverage > 0:
            notional = qty * entry * point_value * usd_mult
            cap = equity * max_leverage
            if notional > cap:
                qty *= cap / notional
        if qty_step and qty_step > 0:
            qty = math.floor(qty / qty_step + 1e-9) * qty_step
        if qty <= 0 or (min_qty and qty < min_qty):
            return 0.0
        d = 6 - int(math.floor(math.log10(qty))) - 1          # round DOWN to 6 significant digits
        qty = math.floor(qty * 10 ** d * (1 + 1e-12) + 1e-9) / 10 ** d
        return qty if qty > 0 else 0.0

    # ----- orders -----
    def open_risk_usd(self) -> float:
        """What all open trades lose if every stop is hit now (trades with the stop at/beyond entry risk 0)."""
        tot = 0.0
        for t in self.open_trades():
            sgn = 1 if t["side"] == "LONG" else -1
            loss = (t["entry"] - t["sl"]) * sgn
            if loss > 0:
                tot += loss * t["qty_open"] * t["point_value"] * t["usd_mult"]
        return tot

    def can_open(self, symbol: str, setup: str | None = None) -> tuple[bool, str]:
        if self.j.get("paused", False):
            return False, "bot paused"
        opens = self.open_trades()
        mine = [t for t in opens if t["symbol"] == symbol]
        if len(mine) >= self.max_per_symbol:
            return False, ("already in a position on this symbol" if self.max_per_symbol <= 1
                           else f"max {self.max_per_symbol} positions on this symbol")
        key = setup or "structure"
        if any((t.get("setup") or "structure") == key for t in mine):
            return False, "already in this setup on this symbol"
        if len(opens) >= self.max_positions:
            return False, f"max positions ({self.max_positions}) reached"
        if self.daily_limit_hit():
            return False, "daily loss limit reached"
        if self.max_open_risk_pct and self.open_risk_usd() >= self.equity() * self.max_open_risk_pct / 100 * 0.995:
            return False, f"open-risk cap ({self.max_open_risk_pct:g}% of equity) reached"
        return True, ""

    def open(self, symbol: str, side: str, price: float, sl: float, tp1: float, tp2: float, tf: str = "",
             atr: float = 0.0, reasons=None, tags=None, signal_id: int | None = None, usd_mult: float = 1.0,
             ts: int | None = None, risk_pct: float | None = None, setup: str | None = None,
             risk_reason: str = "") -> dict | None:
        ok, why = self.can_open(symbol, setup)
        self.last_reject = why
        if not ok:
            return None
        meta = instruments.info(symbol)
        pv = float(meta["point_value"])
        entry = self.fill_price(symbol, side, price, opening=True)
        # stop must be on the losing side of the entry
        if (side == "LONG" and sl >= entry) or (side == "SHORT" and sl <= entry):
            return None
        eq = self.equity()
        rp = float(self.risk_pct if risk_pct is None else risk_pct)
        if self.max_open_risk_pct:                      # never risk more than the account can lose in total
            room = eq * self.max_open_risk_pct / 100 - self.open_risk_usd()
            if room < eq * 0.005:
                self.last_reject = f"open-risk cap ({self.max_open_risk_pct:g}% of equity) reached"
                return None
            if eq * rp / 100 > room:
                rp = 100 * room / eq
                risk_reason = (risk_reason + "; " if risk_reason else "") + f"cut to {rp:.1f}% by the {self.max_open_risk_pct:g}% open-risk cap"
        qty = self.position_size(eq, rp, entry, sl, pv, usd_mult, self.max_leverage, self.qty_step, self.min_qty)
        if qty <= 0:
            self.last_reject = "size rounds to zero"
            return None
        risk_usd = abs(entry - sl) * qty * pv * usd_mult
        if eq and risk_usd < eq * rp / 100 * 0.98:
            risk_reason = (risk_reason + "; " if risk_reason else "") + \
                f"cut to {100 * risk_usd / eq:.1f}% by the {self.max_leverage:g}x leverage cap / size step"
        ts = ts or int(time.time())
        tid = self.j.x("INSERT INTO trades(signal_id,symbol,tf,side,qty,qty_open,entry,sl,sl_initial,tp1,tp2,risk_usd,"
                       "point_value,usd_mult,opened_ts,status,reasons,tags,last_price,atr,setup,risk_pct,risk_reason) VALUES"
                       "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (signal_id, symbol, tf, side, qty, qty, entry, sl, sl, tp1, tp2, risk_usd, pv, usd_mult, ts,
                        "open", json.dumps(reasons or []), json.dumps(tags or []), price, atr, setup,
                        round(100 * risk_usd / eq, 2) if eq else rp, risk_reason))
        self.j.x("INSERT INTO fills(trade_id,ts,kind,price,qty,pnl_usd) VALUES(?,?,?,?,?,?)",
                 (tid, ts, "entry", entry, qty, 0.0))
        return self._get(tid)

    def _get(self, tid: int) -> dict:
        r = self.j.q("SELECT * FROM trades WHERE id=?", (tid,))[0]
        r["reasons"] = json.loads(r["reasons"] or "[]")
        r["tags"] = json.loads(r["tags"] or "[]")
        return r

    def _close_qty(self, t: dict, qty: float, raw_price: float, kind: str, ts: int) -> float:
        px = self.fill_price(t["symbol"], t["side"], raw_price, opening=False)
        sgn = 1 if t["side"] == "LONG" else -1
        pnl = (px - t["entry"]) * sgn * qty * t["point_value"] * t["usd_mult"]
        self.j.x("INSERT INTO fills(trade_id,ts,kind,price,qty,pnl_usd) VALUES(?,?,?,?,?,?)",
                 (t["id"], ts, kind, px, qty, pnl))
        self.j.set("balance", self.balance + pnl)
        left = max(0.0, t["qty_open"] - qty)
        tot = t["pnl_usd"] + pnl
        if left <= 1e-12:
            r_mult = tot / t["risk_usd"] if t["risk_usd"] else 0
            self.j.x("UPDATE trades SET qty_open=0,status='closed',closed_ts=?,exit_price=?,pnl_usd=?,r_multiple=?,"
                     "exit_reason=? WHERE id=?", (ts, px, tot, r_mult, kind, t["id"]))
        else:
            self.j.x("UPDATE trades SET qty_open=?,pnl_usd=? WHERE id=?", (left, tot, t["id"]))
        t["qty_open"], t["pnl_usd"] = left, tot
        return pnl

    def update(self, trade_id: int, high: float, low: float, close: float, atr: float | None = None,
               ts: int | None = None) -> list[dict]:
        """Process one bar for an open trade. Conservative: if SL and a target are both inside the bar, SL wins."""
        ts = ts or int(time.time())
        t = self._get(trade_id)
        if t["status"] != "open":
            return []
        ev = []
        long = t["side"] == "LONG"
        atr = atr or t["atr"] or 0
        hit_sl = low <= t["sl"] if long else high >= t["sl"]
        if hit_sl:
            kind = "breakeven" if t["tp1_hit"] and abs(t["sl"] - t["entry"]) < 1e-12 else \
                "trailing stop" if t["tp1_hit"] else "stop loss"
            pnl = self._close_qty(t, t["qty_open"], t["sl"], kind, ts)
            ev.append({"kind": kind, "price": t["sl"], "pnl": pnl, "trade": self._get(trade_id)})
            return ev
        if not t["tp1_hit"] and (high >= t["tp1"] if long else low <= t["tp1"]):
            q = t["qty_open"] * self.tp1_close
            pnl = self._close_qty(t, q, t["tp1"], "tp1", ts)
            new_sl = t["entry"]
            self.j.x("UPDATE trades SET tp1_hit=1, sl=? WHERE id=?", (new_sl, t["id"]))
            t["tp1_hit"], t["sl"] = 1, new_sl
            ev.append({"kind": "tp1", "price": t["tp1"], "pnl": pnl, "trade": self._get(trade_id)})
        if t["tp1_hit"] and t["qty_open"] > 0 and (high >= t["tp2"] if long else low <= t["tp2"]):
            pnl = self._close_qty(t, t["qty_open"], t["tp2"], "tp2", ts)
            ev.append({"kind": "tp2", "price": t["tp2"], "pnl": pnl, "trade": self._get(trade_id)})
            return ev
        if t["tp1_hit"] and atr and self.trail_atr > 0:
            trail = close - self.trail_atr * atr if long else close + self.trail_atr * atr
            if (long and trail > t["sl"]) or (not long and trail < t["sl"]):
                self.j.x("UPDATE trades SET sl=? WHERE id=?", (trail, t["id"]))
        self.j.x("UPDATE trades SET last_price=? WHERE id=?", (close, t["id"]))
        return ev

    def close(self, trade_id: int, price: float, reason: str = "manual", ts: int | None = None) -> dict | None:
        t = self._get(trade_id)
        if t["status"] != "open":
            return None
        pnl = self._close_qty(t, t["qty_open"], price, reason, ts or int(time.time()))
        return {"kind": reason, "price": price, "pnl": pnl, "trade": self._get(trade_id)}

    def snapshot_equity(self) -> None:
        self.j.x("INSERT OR REPLACE INTO equity(ts,balance,equity) VALUES(?,?,?)",
                 (int(time.time()), self.balance, self.equity()))
