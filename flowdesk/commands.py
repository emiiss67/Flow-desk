"""Telegram command handlers (owner chat only)."""
from __future__ import annotations
import time

from . import events, instruments
from .config import get_config
from .strategy import check, fmt
from .telegram import esc
from . import stake
from .currency import fmt_money, account_ccy

HELP = ("<b>FlowDesk</b> (PAPER)\n"
        "/check SYMBOL [tf] - long/short call with entry, SL, TP\n"
        "/positions - open paper positions\n/pnl - P&amp;L and stats\n"
        "/pause, /resume - stop/start new entries\n/resetlimit - restart today's daily-loss window from the current balance\n/close SYMBOL - close a paper position\n"
        "/watchlist, /news, /calendar, /status, /desk")


def fmt_winrate(wr: dict | None, score=None) -> str:
    sc = f"Confluence {score}/100 (a score, not a probability)" if score is not None else ""
    if not wr or wr.get("status") != "ok":
        msg = "computing…" if wr and wr.get("status") == "computing" else "unavailable"
        return (sc + "\n" if sc else "") + f"📊 Backtest win rate: {msg}"
    if not wr.get("n"):
        return (sc + "\n" if sc else "") + f"📊 Backtest: no past {wr['direction'].lower()} setups in score band {wr['band'][0]}-{wr['band'][1]}"
    line = (f"📊 Backtest win {wr['win_rate']:.0f}% (TP1 before SL) · TP2 {wr['tp2_rate']:.0f}% · n={wr['n']} · "
            f"avg {wr['avg_r']:+.2f}R · exp {fmt_money(wr.get('expectancy_usd', 0), account_ccy())}/trade")
    if wr.get("low_sample"):
        line += "\n⚠️ low sample (n &lt; 20) - treat as anecdotal"
    ss = wr.get("setup_stats")
    if ss and ss.get("n"):
        line += (f"\n🎯 {esc(ss['setup'])} history: win {ss['win_rate']:.0f}% · n={ss['n']} · avg {ss['avg_r']:+.2f}R"
                 + (" (low sample)" if ss.get("low_sample") else ""))
    elif ss:
        line += f"\n🎯 {esc(ss['setup'])}: no past occurrences in this history"
    return (sc + "\n" if sc else "") + line


def fmt_sizing(sz: dict | None) -> str:
    if not sz:
        return ""
    if sz.get("skip"):
        return f"💰 Would skip: {esc(sz['reason'])}"
    return f"💰 Risk {sz['risk_pct']:g}% · {esc(sz['reason'])}"


def fmt_check(r: dict) -> str:
    if not r.get("ok"):
        return f"<b>{esc(instruments.display(r['symbol']))}</b>: data unavailable"
    d = r["decision"]
    icon = {"LONG": "🟢", "SHORT": "🔴"}.get(d, "⚪")
    lines = [f"{icon} <b>{esc(instruments.display(r['symbol']))} {esc(r['tf'])} - {d}</b> · PAPER",
             f"Price {fmt(r['price'])}" + (f"\n🎯 Setup: <b>{esc(r['setup'])}</b>" if r.get("setup") else ""),
             fmt_winrate(r.get("winrate"), r.get("confluence"))]
    if r.get("sizing") and r["decision"] in ("LONG", "SHORT"):
        lines.append(fmt_sizing(r["sizing"]))
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
        return "👋 FlowDesk is connected to this chat (paper trading only).\n\n" + HELP

    def cmd_help(self, a):
        return HELP

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
            st = stake.of_trade(dict(t, unrealized=u), self.b.ccy)
            pr = f" ({st['pnl_pct_of_risk']:+g}% of risk)" if st["pnl_pct_of_risk"] is not None else ""
            out.append(f"{'🟢' if sgn > 0 else '🔴'} <b>{esc(instruments.display(t['symbol']))}</b> {t['side']} @ {fmt(t['entry'])}  "
                       f"SL {fmt(t['sl'])} TP {fmt(t['tp1'])}/{fmt(t['tp2'])}  <b>{fmt_money(u, self.b.ccy)}</b>{pr}\n"
                       f"   💰 {esc(st['text'])}")
        return "\n".join(out)

    def cmd_pnl(self, a):
        from .stats import performance
        s = performance(self.j, self.b.start_balance)
        pf = s["profit_factor"] if s["profit_factor"] is not None else "-"
        c = self.b.ccy
        return (f"<b>Paper P&amp;L</b> ({c})\nBalance {fmt_money(self.b.balance, c, False)} | Equity {fmt_money(self.b.equity(), c, False)}\n"
                f"Today {fmt_money(self.b.realized_today(), c)} | Net {fmt_money(s['net'], c)}\n"
                f"Trades {s['trades']} | Win {s['win_rate']}% | PF {pf} | Max DD {fmt_money(s['max_drawdown'], c, False)}"
                + self._stake_lines(c))

    def _stake_lines(self, c):
        """What is in the market now and what went into the last closed trades."""
        op = self.b.open_trades()
        lines = []
        if op:
            risk = sum(t["risk_usd"] or 0 for t in op)
            notional = sum(stake.of_trade(t, c)["notional_eur"] for t in op)
            lines.append(f"\n<b>In the market</b>: {len(op)} open · Risk {fmt_money(risk, c, False)} · Notional {fmt_money(notional, c, False, None)}")
        last = self.j.trades("closed", limit=5)
        if last:
            lines.append("\n<b>Last closed</b>")
            for t in last:
                st = stake.of_trade(t, c)
                pr = f" ({st['pnl_pct_of_risk']:+g}% of risk)" if st["pnl_pct_of_risk"] is not None else ""
                lines.append(f"{esc(instruments.display(t['symbol']))} {t['side']} <b>{fmt_money(t['pnl_usd'] or 0, c)}</b>{pr}\n   💰 {esc(st['text'])}")
        return "\n".join(lines)

    def cmd_pause(self, a):
        self.j.set("paused", True)
        return "⏸ Paused. No new paper entries; open positions are still managed."

    def cmd_resetlimit(self, a):
        r = self.b.reset_daily_limit()
        self.j.set("paused", False)
        return (f"🔄 Daily loss limit reset. New baseline {fmt_money(r['baseline'], self.b.ccy, False)}; "
                f"the bot stops again after -{r['limit_pct']:g}% from here. (paper)")

    def cmd_resume(self, a):
        self.j.set("paused", False)
        return "▶️ Resumed. Scanning for paper entries."

    def cmd_close(self, a):
        if not a:
            return "Usage: /close SYMBOL"
        sym = instruments.normalize(a[0])
        ts = [t for t in self.b.open_trades() if t["symbol"] == sym]
        if not ts:
            return f"No open position on {esc(instruments.display(sym))}."
        df = self.p.candles(sym, ts[0]["tf"] or "15m")
        px = float(df["close"].iloc[-1])
        ev = self.b.close(ts[0]["id"], px, "manual close")
        return f"Closed {esc(instruments.display(sym))} at {fmt(px)}: <b>{fmt_money(ev['pnl'], self.b.ccy)}</b> (paper)"

    def cmd_watchlist(self, a):
        wl = get_config().get("watchlist", [])
        return "<b>Watchlist</b>\n" + "\n".join(f"• {esc(instruments.display(w['symbol']))} {esc(w.get('tf', '15m'))}" for w in wl)

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
                f"Open {len(self.b.open_trades())} | Balance {fmt_money(self.b.balance, self.b.ccy, False)}\n"
                f"Data: {esc(self.p.name)} (order flow estimated)")

    def cmd_desk(self, a):
        url = self.j.get("tunnel_url")
        from .auth import desk_key
        base = get_config().get("desk_url", "https://emiiss67.github.io/Flow-desk/")
        if not url:
            return f"Desk: {base} (API tunnel not up yet - demo mode only)"
        return f"Desk: {base}#api={url}&key={desk_key()}"
