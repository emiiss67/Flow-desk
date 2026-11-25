"""FlowDesk bot process: scanner loop (paper entries + management) and Telegram control.

Run:  python -m flowdesk.bot
"""
from __future__ import annotations
import logging
import signal
import threading
import time

from . import events, instruments
from .broker import PaperBroker
from .commands import Commands, fmt_check
from .config import get_config
from .data import get_provider, DataUnavailable
from .ict import killzone
from .journal import Journal
from .strategy import check, fmt
from .commands import fmt_winrate
from .currency import FxConverter, migrate, fmt_money
from .telegram import Telegram, esc

log = logging.getLogger("flowdesk.bot")


class Bot:
    def __init__(self, journal: Journal | None = None, tg: Telegram | None = None):
        self.cfg = get_config()
        self.j = journal or Journal()
        self.b = PaperBroker(self.j, self.cfg.get("broker"))
        self.p = get_provider()
        self.fx = FxConverter(self.p, self.j)
        try:
            mig = migrate(self.j, self.fx, self.b.ccy, self.b.start_balance)
            if mig:
                log.info("journal currency converted: %s", mig)
        except Exception as e:
            log.warning("currency migration postponed: %s", e)
        self.tg = tg or Telegram()
        self.cmds = Commands(self.j, self.b, self.p, self.tg)
        self.cmds.fx = self.fx
        self.stop = threading.Event()

    # ---------- alerts ----------
    def alert(self, text: str) -> None:
        """Unsolicited messages (signals, entries, exits, events). Off unless telegram.auto_alerts is true -
        everything stays visible in the desk (Signals / Positions / Journal)."""
        if self.tg.enabled and (self.cfg.get("telegram", {}) or {}).get("auto_alerts", False):
            self.tg.send(text)

    def usd_mult(self, symbol: str, price: float, ts: int | None = None) -> float | None:
        """Quote-currency -> account-currency multiplier (name kept for compatibility)."""
        return self.fx.mult(symbol, price, self.b.ccy, ts)

    def refresh_fx(self) -> None:
        """Re-mark open trades at the current FX rate so their P&L is converted at the time it is realised."""
        for t in self.b.open_trades():
            m = self.usd_mult(t["symbol"], t["last_price"] or t["entry"])
            if m and abs(m - (t["usd_mult"] or 0)) > 1e-12:
                self.j.x("UPDATE trades SET usd_mult=? WHERE id=?", (m, t["id"]))

    # ---------- position management ----------
    def manage(self) -> None:
        try:
            self.refresh_fx()
        except Exception as e:
            log.warning("fx refresh failed: %s", e)
        for t in self.b.open_trades():
            try:
                df = self.p.candles(t["symbol"], t["tf"] or "15m")
            except DataUnavailable:
                continue
            last = self.j.get(f"last_bar_{t['id']}", t["opened_ts"])
            bars = df[df.index.map(lambda x: int(x.timestamp())) >= last]
            if bars.empty:
                continue
            for ts, r in bars.iterrows():
                evs = self.b.update(t["id"], float(r.high), float(r.low), float(r.close), ts=int(ts.timestamp()))
                for ev in evs:
                    tr = ev["trade"]
                    emoji = "✅" if ev["pnl"] >= 0 else "❌"
                    self.alert(f"{emoji} <b>{esc(instruments.display(tr['symbol']))}</b> {tr['side']} {esc(ev['kind'])} at "
                               f"{fmt(ev['price'])}: <b>{fmt_money(ev['pnl'], self.b.ccy)}</b> (paper)"
                               + (f"\nTrade total {fmt_money(tr['pnl_usd'], self.b.ccy)}" if tr["status"] == "closed" else
                                  "\nRest running, stop moved to breakeven"))
                if self.b._get(t["id"])["status"] != "open":
                    break
            self.j.set(f"last_bar_{t['id']}", int(bars.index[-1].timestamp()))

    # ---------- scanning ----------
    def scan_once(self) -> None:
        """Scan the whole watchlist; several positions can open in one cycle (limits: max_positions,
        max_per_symbol with different setups, open-risk cap, daily loss limit). Every candidate passes the
        learned rules (data/learned_rules.json) first: disabled strategies, blocked loss buckets, per-symbol edge."""
        from . import backtest, learning, regime, sizing, strategies as S
        sc = self.cfg.get("scanner", {})
        rules = learning.load_rules()
        from . import quality
        from .data import closed_bars
        closed_only = bool(quality.cfg(self.cfg).get("closed_bars_only", True))
        for w in self.cfg.get("watchlist", []):
            sym, tf = instruments.normalize(w["symbol"]), w.get("tf", "15m")
            try:
                r = check(sym, tf, with_chart=False, winrate="off", closed_only=closed_only)
            except Exception as e:
                log.warning("check %s failed: %s", sym, e)
                continue
            R = None
            try:
                cdf = self.p.candles(sym, tf)
                R = S.rows(S.indicators(closed_bars(cdf, sym, tf) if closed_only else cdf,
                                        S.peer_frame(self.p, sym, tf, closed_bars if closed_only else None), tail=8))
            except Exception as e:
                log.debug("indicators %s failed: %s", sym, e)
            if r.get("ok") and r["decision"] in ("LONG", "SHORT"):
                setup = r.get("setup")
                stream = learning.SETUP_KEYS.get(setup) if setup else learning.CORE
                feats = S.features(R, len(R) - 1, r["decision"], None, r["confluence"]) if R else {}
                key = f"sig_{sym}_{tf}_{setup or 'structure'}"
                if self.j.get(key) != [r["last_bar"], r["decision"]]:
                    self.j.set(key, [r["last_bar"], r["decision"]])
                    try:  # cached win rate (pre-warmed in the background, never blocks the scan)
                        r["winrate"] = backtest.winrate(sym, tf, r["decision"], r["confluence"], mode="cached", setup=setup)
                    except Exception as e:
                        log.warning("winrate %s failed: %s", sym, e)
                        r["winrate"] = {"status": "unavailable"}
                    self._enter(r, sym, tf, setup, stream, feats, rules, sc)
            if not R or not r.get("ok") or r.get("blackout"):
                continue          # news-straddle avoidance: no extra-strategy entries in a high-impact event window
            for name in S.STRATEGIES:
                st = rules.get("strategies", {}).get(name) or {}
                if not st.get("enabled") and not regime.switched_on(rules, name):
                    continue
                sg = S.signal(name, R, len(R) - 1, st.get("params"))
                if not sg:
                    continue
                key = f"sig_{sym}_{tf}_{name}"
                if self.j.get(key) == [r["last_bar"], sg["side"]]:
                    continue
                self.j.set(key, [r["last_bar"], sg["side"]])
                from .strategy import decimals
                dp = decimals(sg["entry"])
                lv = {k: round(sg[k], dp) for k in ("entry", "sl", "tp1", "tp2")}
                lv["rr2"] = round(sg["rr"], 2)
                label = learning.NAMES[name]
                res = {"symbol": sym, "tf": tf, "decision": sg["side"], "confluence": None, "price": r["price"], "levels": lv,
                       "live_price": r.get("live_price"),
                       "atr": sg["atr"], "setup": label,
                       "reasons": [{"text": S.STRATEGIES[name]["desc"], "tag": label}],
                       "winrate": learning.stats_for(rules, name, sym)}
                self._enter(res, sym, tf, label, name, S.features(R, len(R) - 1, sg["side"], sg["sl_atr"]), rules, sc)

    def _quality(self, r: dict, sym: str, stream: str, feats: dict) -> tuple[bool, str]:
        from . import quality
        return quality.fill_check(r, sym, stream, feats, self.cfg)

    def _enter(self, r: dict, sym: str, tf: str, setup, stream: str, feats: dict, rules: dict, sc: dict) -> None:
        from . import learning, sizing
        sz = sizing.choose(r["winrate"], self.cfg)
        r["sizing"] = sz
        ok, why = learning.allow(rules, stream, sym, {k: v for k, v in feats.items()}, r.get("confluence"))
        if ok:
            ok, why = self._quality(r, sym, stream, feats)
        if ok:
            ok, why = self.b.can_open(sym, setup, r["decision"])
        if ok and sc.get("require_killzone") and not killzone():
            ok, why = False, "outside killzone"
        if ok and sz["skip"]:
            ok, why = False, sz["reason"]
        t = None
        mult = self.usd_mult(sym, r["levels"]["entry"]) if ok else None
        if ok and not mult:
            ok, why = False, f"no FX rate to convert {sym} into {self.b.ccy}"
        if ok:
            lv = r["levels"]
            t = self.b.open(sym, r["decision"], lv["entry"], lv["sl"], lv["tp1"], lv["tp2"], tf=tf, atr=r["atr"],
                            reasons=[x["text"] for x in r["reasons"]], tags=sorted({x["tag"] for x in r["reasons"]}),
                            usd_mult=mult, risk_pct=sz["risk_pct"], setup=setup,
                            risk_reason=sz["reason"], strategy=stream, features=feats)
            if not t:
                ok, why = False, self.b.last_reject or "order rejected"
        if t:
            r["sizing"] = {"risk_pct": t["risk_pct"], "reason": t["risk_reason"]}
        sid = self.j.add_signal(r, acted=bool(t), note="" if t else why)
        if t:
            self.j.x("UPDATE trades SET signal_id=? WHERE id=?", (sid, t["id"]))
            log.info("paper entry %s %s %s risk %.1f%% (%s)", sym, stream, t["side"], t["risk_pct"] or 0, t["risk_reason"])
            self.alert(f"📥 <b>Paper entry</b> {esc(instruments.display(sym))} {t['side']} @ {fmt(t['entry'])}"
                       + (f" · 🎯 {esc(setup)}" if setup else "") + "\n"
                       f"SL {fmt(t['sl'])} | TP1 {fmt(t['tp1'])} | TP2 {fmt(t['tp2'])} | risk {fmt_money(t['risk_usd'], self.b.ccy, False)}")

    def learning_loop(self) -> None:
        """Nightly learning cycle (~02:00 UTC) and on request from the desk (kv learn_request)."""
        from . import learning
        lc = self.cfg.get("learning", {}) or {}
        hour = int(lc.get("nightly_hour_utc", 2))
        while not self.stop.is_set():
            try:
                now = time.gmtime()
                today = time.strftime("%Y-%m-%d", now)
                req = self.j.get("learn_request")
                due = lc.get("enabled", True) and now.tm_hour >= hour and self.j.get("learn_last_day") != today
                if req or due:
                    self.j.set("learn_status", {"state": "running", "since": int(time.time()), "by": "desk" if req else "nightly"})
                    self.j.set("learn_request", None)
                    try:
                        rr = learning.run_cycle(journal=self.j, progress=lambda m: self.j.set(
                            "learn_status", {"state": "running", "since": int(time.time()), "step": m}))
                        self.j.set("learn_status", {"state": "done", "at": int(time.time()), "version": rr["version"],
                                                    "changes": len(rr.get("changes", []))})
                        log.info("learning cycle v%s: %s", rr["version"], rr.get("note"))
                    except Exception as e:
                        log.exception("learning cycle failed: %s", e)
                        self.j.set("learn_status", {"state": "failed", "at": int(time.time()), "error": type(e).__name__})
                    if due:
                        self.j.set("learn_last_day", today)
            except Exception as e:
                log.warning("learning loop: %s", e)
            self.stop.wait(30)

    def prewarm_loop(self) -> None:
        """Keep watchlist win rates fresh so entries and desk checks never wait for the ~1 min replay."""
        from . import backtest
        every = float(self.cfg.get("sizing", {}).get("prewarm_minutes", 50)) * 60
        while not self.stop.is_set():
            for w in self.cfg.get("watchlist", []):
                if self.stop.is_set():
                    return
                sym, tf = instruments.normalize(w["symbol"]), w.get("tf", "15m")
                a = backtest.age(sym, tf)
                if a is not None and a < every:
                    continue
                try:
                    t0 = time.time()
                    d = backtest.compute(sym, tf)
                    log.info("prewarmed win rate %s %s (%s, %.0fs)", sym, tf, "ok" if d.get("ok") else "no data", time.time() - t0)
                except Exception as e:
                    log.warning("prewarm %s failed: %s", sym, type(e).__name__)
            self.stop.wait(60)

    def event_alerts(self) -> None:
        ccys = set()
        for w in self.cfg.get("watchlist", []):
            ccys.update(instruments.info(w["symbol"])["ccy"])
        sent = set(self.j.get("event_alerts_sent", []))
        now = time.time()
        for e in events.calendar().get("events", []):
            if e["impact"] != "High" or e["ccy"] not in ccys:
                continue
            k = f"{e['ccy']}|{e['title']}|{e['ts']}"
            if 0 < e["ts"] - now <= 30 * 60 and k not in sent:
                syms = [instruments.display(w["symbol"]) for w in self.cfg.get("watchlist", []) if e["ccy"] in instruments.info(w["symbol"])["ccy"]]
                self.alert(f"⚠️ <b>{esc(e['ccy'])} {esc(e['title'])}</b> in {round((e['ts'] - now) / 60)} min "
                           f"(high impact). No new entries on {esc(', '.join(syms))} around it.")
                sent.add(k)
        self.j.set("event_alerts_sent", sorted(sent)[-200:])

    def loop(self) -> None:
        interval = self.cfg.get("scanner", {}).get("interval_seconds", 120)
        while not self.stop.is_set():
            t0 = time.time()
            for step in (self.manage, self.scan_once, self.event_alerts, self.b.snapshot_equity):
                try:
                    step()
                except Exception as e:
                    log.exception("step %s failed: %s", step.__name__, e)
            self.j.set("bot_heartbeat", int(time.time()))
            self.stop.wait(max(5, interval - (time.time() - t0)))

    # ---------- telegram ----------
    def _claim_owner(self, chat: str) -> None:
        """No chat id configured yet: the first private chat that messages the bot becomes the owner (stored in
        kv and .env). Every other chat is ignored afterwards."""
        self.tg.chat_id = chat
        self.j.set("owner_chat_id", chat)
        try:
            from .config import ROOT
            env = ROOT / ".env"
            lines = env.read_text().splitlines() if env.exists() else []
            lines = [l for l in lines if not l.startswith("FLOWDESK_TELEGRAM_CHAT_ID=")] + [f"FLOWDESK_TELEGRAM_CHAT_ID={chat}"]
            env.write_text("\n".join(lines) + "\n")
            env.chmod(0o600)
        except Exception as e:
            log.warning("could not write chat id to .env: %s", type(e).__name__)
        log.info("owner chat claimed (first private chat to message the bot)")

    def handle_update(self, u: dict) -> bool:
        msg = u.get("message") or {}
        c = msg.get("chat") or {}
        chat = str(c.get("id", ""))
        text = (msg.get("text") or "").strip()
        if not chat:
            return False
        if not self.tg.chat_id:
            if c.get("type") != "private":
                return False
            self._claim_owner(chat)
        if chat != self.tg.chat_id:
            log.info("update %s ignored: not the owner chat", u.get("update_id"))
            return False  # answer ONLY the owner's chat
        cmd = text.split()[0].split("@")[0].lower() if text.startswith("/") else "(text)"
        if cmd == "/signal":
            self.tg.send("🔎 Reading the latest finished candles...", chat)
        if cmd == "/check":
            self.tg.send("🔎 Checking... (first check of a symbol also replays its history for the win rate, ~1 min)", chat)
        reply = self.cmds.handle(text) if text.startswith("/") else self.cmds.handle("/help")
        ok = self.tg.send(reply, chat)
        log.info("handled update %s cmd=%s reply=%s", u.get("update_id"), cmd, "sent" if ok else "FAILED")
        return ok

    def telegram_loop(self) -> None:
        if not self.tg.token:
            log.info("telegram disabled (no FLOWDESK_TELEGRAM_TOKEN)")
            return
        if not self.tg.chat_id and self.j.get("owner_chat_id"):
            self.tg.chat_id = str(self.j.get("owner_chat_id"))
        self.tg.call("deleteWebhook", drop_pending_updates=False)   # long polling needs no webhook
        log.info("telegram polling started (%s)", "owner chat set" if self.tg.chat_id else "waiting for the owner to press Start")
        while not self.stop.is_set():
            for u in self.tg.updates():
                try:
                    self.handle_update(u)
                except Exception as e:
                    log.warning("update %s failed: %s", u.get("update_id"), type(e).__name__)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    bot = Bot()
    signal.signal(signal.SIGTERM, lambda *_: bot.stop.set())
    threading.Thread(target=bot.telegram_loop, daemon=True).start()
    threading.Thread(target=bot.prewarm_loop, daemon=True).start()
    threading.Thread(target=bot.learning_loop, daemon=True).start()
    log.info("FlowDesk bot started (PAPER). Watchlist: %s", [w["symbol"] for w in bot.cfg.get("watchlist", [])])
    try:
        bot.loop()
    except KeyboardInterrupt:
        bot.stop.set()


if __name__ == "__main__":
    main()
