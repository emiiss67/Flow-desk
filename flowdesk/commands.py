"""Telegram command handlers (owner chat only)."""
from __future__ import annotations
import time

from . import events, instruments
from .config import get_config
from .strategy import check, fmt
from .telegram import esc

HELP = ("<b>FlowDesk</b> (PAPER)\n"
        "/check SYMBOL [tf] - long/short call with entry, SL, TP\n"
        "/positions - open paper positions\n/pnl - P&amp;L and stats\n"
        "/pause, /resume - stop/start new entries\n/close SYMBOL - close a paper position\n"
        "/watchlist, /news, /calendar, /status, /desk")


def fmt_check(r: dict) -> str:
    if not r.get("ok"):
        return f"<b>{esc(r['symbol'])}</b>: data unavailable"
    d = r["decision"]
    icon = {"LONG": "🟢", "SHORT": "🔴"}.get(d, "⚪")
    lines = [f"{icon} <b>{esc(r['symbol'])} {esc(r['tf'])} - {d}</b> ({r['confidence']}% conf) · PAPER",
             f"Price {fmt(r['price'])}"]
    if "levels" in r:
        lv = r["levels"]
        lines.append(f"Entry {fmt(lv['entry'])} | SL {fmt(lv['sl'])}\nTP1 {fmt(lv['tp1'])} ({lv['rr1']}R) | "
                     f"TP2 {fmt(lv['tp2'])} ({lv['rr2']}R)")
    elif r.get("watch"):
        w = r["watch"]
        lines.append(f"Lean {w['bias'].lower()}, not enough confluence (L {r['scores']['long']} / S {r['scores']['short']})")
    for x in r.get("reasons", [])[:5]:
        lines.append(f"• {esc(x['text'])}")
    for w in r.get("warnings", [])[:2]:
        lines.append(f"⚠️ {esc(w['text'])}")
    lines.append(f"<i>{esc(r['source'])}; order flow estimated</i>")
    return "\n".join(lines)


class Commands:
    def __init__(self, journal, broker, provider, tg):
        self.j, self.b, self.p, self.tg = journal, broker, provider, tg

    def handle(self, text: str) -> str:
        parts = text.strip().split()
        if not parts:
            return HELP
        cmd = parts[0].split("@")[0].lower()
        args = parts[1:]
        try:
            fn = getattr(self, "cmd_" + cmd.lstrip("/"), None)
            return fn(args) if fn else HELP
        except Exception as e:
            return f"Error: {esc(type(e).__name__)}"

    def cmd_start(self, a):
        return HELP

    cmd_help = cmd_start

    def cmd_check(self, a):
        if not a:
            return "Usage: /check EURUSD [15m]"
        tf = a[1] if len(a) > 1 else "15m"
        return fmt_check(check(a[0], tf, with_chart=False))

    def cmd_positions(self, a):
        ts = self.b.open_trades()
        if not ts:
            return "No open paper positions."
        out = []
        for t in ts:
            sgn = 1 if t["side"] == "LONG" else -1
            u = (t["last_price"] - t["entry"]) * sgn * t["qty_open"] * t["point_value"] * t["usd_mult"] if t["last_price"] else 0
            out.append(f"{'🟢' if sgn > 0 else '🔴'} <b>{esc(t['symbol'])}</b> {t['side']} @ {fmt(t['entry'])}  "
                       f"SL {fmt(t['sl'])} TP {fmt(t['tp1'])}/{fmt(t['tp2'])}  <b>{u:+,.2f} USD</b>")
        return "\n".join(out)

    def cmd_pnl(self, a):
        from .stats import performance
        s = performance(self.j, self.b.start_balance)
        pf = s["profit_factor"] if s["profit_factor"] is not None else "-"
        return (f"<b>Paper P&amp;L</b>\nBalance {self.b.balance:,.2f} | Equity {self.b.equity():,.2f}\n"
                f"Today {self.b.realized_today():+,.2f} | Net {s['net']:+,.2f}\n"
                f"Trades {s['trades']} | Win {s['win_rate']}% | PF {pf} | Max DD {s['max_drawdown']:,.2f}")

    def cmd_pause(self, a):
        self.j.set("paused", True)
        return "⏸ Paused. No new paper entries; open positions are still managed."

    def cmd_resume(self, a):
        self.j.set("paused", False)
        return "▶️ Resumed. Scanning for paper entries."

    def cmd_close(self, a):
        if not a:
            return "Usage: /close SYMBOL"
        sym = instruments.normalize(a[0])
        ts = [t for t in self.b.open_trades() if t["symbol"] == sym]
        if not ts:
            return f"No open position on {esc(sym)}."
        df = self.p.candles(sym, ts[0]["tf"] or "15m")
        px = float(df["close"].iloc[-1])
        ev = self.b.close(ts[0]["id"], px, "manual close")
        return f"Closed {esc(sym)} at {fmt(px)}: <b>{ev['pnl']:+,.2f} USD</b> (paper)"

    def cmd_watchlist(self, a):
        wl = get_config().get("watchlist", [])
        return "<b>Watchlist</b>\n" + "\n".join(f"• {esc(w['symbol'])} {esc(w.get('tf', '15m'))}" for w in wl)

    def cmd_news(self, a):
        n = events.news()
        if not n.get("items"):
            return "News: data unavailable"
        return "<b>Headlines</b>\n" + "\n".join(f"• {esc(i['title'])} <i>({esc(i['source'])})</i>" for i in n["items"][:8])

    def cmd_calendar(self, a):
        c = events.calendar()
        if not c.get("ok"):
            return "Calendar: data unavailable"
        now = time.time()
        up = [e for e in c["events"] if e["impact"] == "High" and e["ts"] >= now - 900][:10]
        if not up:
            return "No more high-impact events this week."
        lines = []
        for e in up:
            m = (e["ts"] - now) / 60
            when = f"in {m:.0f}m" if m < 120 else f"in {m / 60:.1f}h"
            lines.append(f"🔴 {esc(e['ccy'])} {esc(e['title'])} - {when}")
        return "<b>High-impact events</b>\n" + "\n".join(lines)

    def cmd_status(self, a):
        hb = self.j.get("bot_heartbeat", 0)
        age = time.time() - hb if hb else None
        st = "paused" if self.j.get("paused", False) else "running"
        return (f"<b>FlowDesk</b> {st} · PAPER\nLast scan {f'{age:.0f}s ago' if age is not None else 'never'}\n"
                f"Open {len(self.b.open_trades())} | Balance {self.b.balance:,.2f} USD\n"
                f"Data: {esc(self.p.name)} (order flow estimated)")

    def cmd_desk(self, a):
        url = self.j.get("tunnel_url")
        from .auth import desk_key
        base = get_config().get("desk_url", "https://emiiss67.github.io/Flow-desk/")
        if not url:
            return f"Desk: {base} (API tunnel not up yet - demo mode only)"
        return f"Desk: {base}#api={url}&key={desk_key()}"
