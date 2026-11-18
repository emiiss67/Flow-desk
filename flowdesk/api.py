"""FastAPI read/compute API for the desk. Binds to 127.0.0.1; exposed only through the cloudflared tunnel.

All endpoints require the desk key (header X-Desk-Key or ?key=). /api/check is compute-only."""
from __future__ import annotations
import time

from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import events, instruments, __version__
from .auth import check_key, desk_key
from .broker import PaperBroker
from .config import get_config, api_port
from .data import get_provider, TIMEFRAMES, DataUnavailable
from .journal import Journal
from .stats import performance
from .strategy import check as run_check

import logging
log = logging.getLogger("flowdesk.api")
cfg = get_config()
app = FastAPI(title="FlowDesk API", version=__version__, docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(CORSMiddleware, allow_origins=cfg.get("api", {}).get("cors_origins", []),
                   allow_methods=["GET"], allow_headers=["X-Desk-Key"], max_age=600)
_j: Journal | None = None
desk_key()  # generate the desk access key on first run (stored server-side, 0600)


def J() -> Journal:
    global _j
    if _j is None:
        _j = Journal()
    return _j


def B() -> PaperBroker:
    return PaperBroker(J(), cfg.get("broker"))


_fx = None


def FX():
    global _fx
    if _fx is None:
        from .currency import FxConverter
        _fx = FxConverter(get_provider(), J())
    return _fx


def _cur() -> dict:
    """Currency the money fields are in (the journal's stored currency; EUR once converted)."""
    from .currency import stored_ccy, symbol_for
    c = stored_ccy(J(), (cfg.get("broker") or {}).get("account_currency", "EUR"))
    return {"currency": c, "currency_symbol": symbol_for(c).strip() if c != "CHF" else "CHF"}


def _size_info(r: dict) -> None:
    """Add the account-currency risk amount + paper size to a check result's sizing block."""
    sz, lv = r.get("sizing"), r.get("levels")
    if not sz or not lv or sz.get("skip") or r.get("decision") not in ("LONG", "SHORT"):
        return
    try:
        b = B()
        eq = b.equity()
        m = FX().mult(r["symbol"], lv["entry"], b.ccy)
        pv = float(instruments.info(r["symbol"])["point_value"])
        if m:
            q = b.position_size(eq, float(sz["risk_pct"]), lv["entry"], lv["sl"], pv, m, b.max_leverage, b.qty_step, b.min_qty)
            sz.update(risk_amount=round(abs(lv["entry"] - lv["sl"]) * q * pv * m, 2), qty=q, fx_mult=round(m, 6),
                      quote_ccy=__import__("flowdesk.currency", fromlist=["quote_ccy"]).quote_ccy(r["symbol"]), **_cur())
    except Exception as e:  # sizing preview is best effort
        log.info("size preview failed: %s", e)


@app.middleware("http")
async def auth_mw(request: Request, call_next):
    if request.method == "OPTIONS" or request.url.path == "/health":
        return await call_next(request)
    key = request.headers.get("x-desk-key") or request.query_params.get("key")
    if not check_key(key):
        r = JSONResponse({"error": "unauthorized"}, status_code=401)
        origin = request.headers.get("origin")
        if origin and origin in cfg.get("api", {}).get("cors_origins", []):
            r.headers["Access-Control-Allow-Origin"] = origin   # so the desk can tell "bad key" from "unreachable"
            r.headers["Vary"] = "Origin"
        return r
    return await call_next(request)


@app.get("/health")
def health():
    from .config import ROOT
    try:
        rev = (ROOT / ".deployed_rev").read_text().strip()[:7]       # written by deploy/autodeploy.sh
    except OSError:
        rev = None
    return {"ok": True, "paper": True, "version": __version__, "rev": rev}


_last_notify: dict = {}


def _notify_check(r: dict) -> None:
    """Desk Check pressed -> one concise Telegram message (waits for the win rate if it is still computing)."""
    import threading

    def work():
        from . import backtest, sizing
        from .commands import fmt_check
        from .telegram import Telegram
        try:
            wr = r.get("winrate") or {}
            if wr.get("status") == "computing":
                for _ in range(60):                       # up to ~3 min
                    time.sleep(3)
                    if backtest.cached(r["symbol"], r["tf"]):
                        break
                side = r["decision"] if r["decision"] in ("LONG", "SHORT") else (r.get("watch") or {}).get("bias", "LONG")
                su = next((x["name"] for x in r.get("setups", []) if x["side"] == side.lower()), None)
                r["winrate"] = backtest.winrate(r["symbol"], r["tf"], side, r["confluence"], mode="cached", setup=su)
                r["sizing"] = sizing.choose(r["winrate"], cfg)
            tg = Telegram()
            if not tg.chat_id:
                tg.chat_id = str(J().get("owner_chat_id") or "")
            if tg.token and tg.chat_id:
                ok = tg.send("🖥 <i>Desk check</i>\n" + fmt_check(r))
                log.info("desk check %s %s sent to telegram: %s", r["symbol"], r["tf"], ok)
        except Exception as e:
            log.warning("desk check notify failed: %s", type(e).__name__)

    threading.Thread(target=work, daemon=True).start()


@app.get("/api/check")
def api_check(symbol: str = Query(..., max_length=24), tf: str = "15m", notify: int = 0):
    """notify=1 (desk Check button): also send the result to the owner's Telegram chat."""
    if tf not in TIMEFRAMES:
        raise HTTPException(400, f"tf must be one of {list(TIMEFRAMES)}")
    try:
        r = run_check(symbol, tf, winrate="async")
    except ValueError as e:
        raise HTTPException(400, str(e))
    if notify and r.get("ok"):
        k = (r["symbol"], tf)
        if time.time() - _last_notify.get(k, 0) > 20:     # double-click guard
            _last_notify[k] = time.time()
            _notify_check({x: v for x, v in r.items() if x != "chart"})
            r["telegram"] = "sent"
        else:
            r["telegram"] = "skipped (sent moments ago)"
    _size_info(r)
    r.update(_cur())
    return r


@app.get("/api/winrate")
def api_winrate(symbol: str = Query(..., max_length=24), tf: str = "15m", direction: str = "LONG",
                score: float = Query(60, ge=0, le=100), setup: str | None = Query(None, max_length=60),
                entry: float | None = None, sl: float | None = None):
    """Historical walk-forward win rate for a direction + Confluence-score band (async: poll until status=ok)."""
    from . import backtest
    if tf not in TIMEFRAMES:
        raise HTTPException(400, f"tf must be one of {list(TIMEFRAMES)}")
    direction = direction.upper()
    if direction not in ("LONG", "SHORT"):
        raise HTTPException(400, "direction must be LONG or SHORT")
    try:
        from . import sizing
        w = backtest.winrate(symbol, tf, direction, score, mode="async", setup=setup)
        if w.get("status") == "ok":
            w["sizing"] = sizing.choose(w, cfg)
            if entry and sl:
                _size_info({"symbol": instruments.normalize(symbol), "decision": direction, "sizing": w["sizing"],
                            "levels": {"entry": entry, "sl": sl}})
        w.update(_cur())
        return w
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/chart")
def api_chart(symbol: str = Query(..., max_length=24), tf: str = "15m"):
    if tf not in TIMEFRAMES:
        raise HTTPException(400, f"tf must be one of {list(TIMEFRAMES)}")
    r = run_check(symbol, tf, winrate="off")
    return {k: r.get(k) for k in ("symbol", "name", "tf", "ok", "source", "source_note", "chart", "price",
                                  "decision", "levels", "error", "volume_source")}


@app.get("/api/instruments")
def api_instruments(q: str = "", category: str | None = None):
    return {"categories": ["Forex", "Indices", "Futures", "Commodities", "Crypto"],
            "items": instruments.search(q, category), "free_text": True,
            "hint": "Any Yahoo Finance ticker works, e.g. AAPL, ^IXIC, EURNOK=X, LE=F"}


def _positions():
    out = []
    for t in B().open_trades():
        sgn = 1 if t["side"] == "LONG" else -1
        u = (t["last_price"] - t["entry"]) * sgn * t["qty_open"] * t["point_value"] * t["usd_mult"] if t["last_price"] else 0
        out.append(dict(t, unrealized=round(u, 2), realized=round(t["pnl_usd"] or 0, 2)))
    return out


def _session():
    """Today's session (UTC day): live PnL widget + session summary card."""
    b, j = B(), J()
    from datetime import datetime, timezone
    day0 = int(datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
    closed = j.q("SELECT pnl_usd FROM trades WHERE status='closed' AND closed_ts>=?", (day0,))
    pos = _positions()
    wins = sum(1 for t in closed if (t["pnl_usd"] or 0) > 0)
    losses = sum(1 for t in closed if (t["pnl_usd"] or 0) < 0)
    n = len(closed)
    open_pnl = round(sum(p["unrealized"] for p in pos), 2)
    closed_pnl = round(b.realized_today(), 2)
    return {"since": day0, "open_pnl": open_pnl, "closed_pnl": closed_pnl, "in_trade": bool(pos), "open_positions": len(pos),
            "net": round(closed_pnl + open_pnl, 2), "trades": n, "wins": wins, "losses": losses,
            "win_rate": round(100 * wins / n, 1) if n else None, "paper": True, **_cur()}


@app.get("/api/session")
def api_session():
    return _session()


@app.get("/api/positions")
def api_positions():
    return {"positions": _positions(), "paper": True, **_cur()}


@app.get("/api/signals")
def api_signals(limit: int = 100):
    return {"signals": J().signals(min(limit, 500))}


@app.get("/api/journal")
def api_journal(limit: int = 300, symbol: str | None = None, side: str | None = None):
    ts = [t for t in J().trades(limit=min(limit, 2000))]
    if symbol:
        ts = [t for t in ts if t["symbol"] == instruments.normalize(symbol)]
    if side:
        ts = [t for t in ts if t["side"] == side.upper()]
    return {"trades": ts, **_cur()}


@app.get("/api/performance")
def api_performance():
    b = B()
    p = performance(J(), b.start_balance)
    eq = J().q("SELECT ts, equity FROM equity ORDER BY ts DESC LIMIT 2000")
    p["equity_snapshots"] = [{"time": r["ts"], "value": round(r["equity"], 2)} for r in reversed(eq)]
    p["balance"], p["equity"], p["start_balance"] = round(b.balance, 2), round(b.equity(), 2), b.start_balance
    p.update(_cur())
    return p


@app.get("/api/dashboard")
def api_dashboard():
    b, j = B(), J()
    perf = performance(j, b.start_balance)
    hb = j.get("bot_heartbeat", 0)
    today_sig = j.q("SELECT COUNT(*) n, SUM(acted) a FROM signals WHERE ts>=?", (int(time.time()) - 86400,))[0]
    blocked = j.q("SELECT COUNT(*) n FROM signals WHERE acted=0 AND ts>=?", (int(time.time()) - 86400,))[0]["n"]
    bc = cfg.get("broker", {})
    ev = []
    try:
        now = time.time()
        ev = [e for e in events.calendar().get("events", []) if e["impact"] == "High" and e["ts"] >= now][:5]
    except Exception:
        pass
    return {
        "paper": True, "balance": round(b.balance, 2), "equity": round(b.equity(), 2), "start_balance": b.start_balance,
        "today_pnl": round(b.realized_today(), 2), "net": perf["net"], "win_rate": perf["win_rate"],
        "profit_factor": perf["profit_factor"], "trades": perf["trades"], "streak": perf["streak"],
        "best_streak": perf["best_streak"], "last_trades": perf["last_trades"], "daily_30": perf["daily_30"],
        "heatmap": perf["heatmap"], "open_positions": _positions(),
        "status": "paused" if j.get("paused", False) else ("running" if hb and time.time() - hb < 900 else "offline"),
        "heartbeat": hb, "daily_limit_hit": b.daily_limit_hit(),
        "signals_24h": today_sig["n"] or 0, "entries_24h": today_sig["a"] or 0, "blocked_24h": blocked,
        "plan": _plan(),
        "upcoming_events": ev, "watchlist": cfg.get("watchlist", []),
        "source": get_provider().name,
        "session": _session(), **_cur(),
    }


def _plan() -> list[str]:
    """Today's plan lines, built from the live config on every request (so config changes show instantly)."""
    c = get_config()
    bc = c.get("broker", {}) or {}
    return [_risk_plan(c),
            f"Max {bc.get('max_positions', 4)} open positions · total open risk ≤ {float(bc.get('max_open_risk_pct', 0) or 0):g}% of equity",
            f"Stop after -{float(bc.get('daily_loss_limit_pct', 30)):g}% day",
            f"No entries {(c.get('events', {}) or {}).get('block_minutes_before', 30)} min before high-impact news",
            f"Min confluence {(c.get('strategy', {}) or {}).get('min_score', 55)}/100 (learning may raise it)",
            f"TP1 closes {bc.get('tp1_close_pct', 50)}%, stop to breakeven"]


@app.get("/api/config")
def api_config():
    """Trading settings the desk displays (read-only, from config.yaml + learned rules). No secrets, no keys."""
    from . import learning, sizing
    c = get_config()
    bc, sc = c.get("broker", {}) or {}, c.get("strategy", {}) or {}
    sz = sizing.settings(c)
    rules = learning.load_rules()
    keys = ("account_currency", "starting_balance", "max_positions", "max_per_symbol", "max_open_risk_pct", "daily_loss_limit_pct",
            "max_leverage", "tp1_close_pct", "trail_atr", "slippage_bps", "spread_bps")
    return {"ok": True, "paper": True, "plan": _plan(), "sizing": {k: sz.get(k) for k in (
                "enabled", "low_sample_n", "base_risk_pct", "negative_risk_pct", "skip_expectancy_r", "skip_min_n", "tiers")},
            "broker": {k: bc.get(k) for k in keys}, "strategy": {k: sc.get(k) for k in ("min_score", "min_margin", "lookback_bars")},
            "events": {k: (c.get("events", {}) or {}).get(k) for k in ("block_minutes_before", "block_minutes_after", "warn_hours")},
            "learning": {"version": rules.get("version", 0), "strategies": {k: {"name": learning.NAMES.get(k, k), "enabled": bool(v.get("enabled")),
                         "params": v.get("params", {})} for k, v in rules.get("strategies", {}).items()}},
            "scanner": {k: (c.get("scanner", {}) or {}).get(k) for k in ("interval_seconds", "require_killzone")},
            "watchlist": c.get("watchlist", []), **_cur()}


def _risk_plan(c: dict | None = None) -> str:
    """Risk line for Today's plan, from the live win-rate sizing tiers (not the legacy broker.risk_pct)."""
    c = c or get_config()
    sz = c.get("sizing", {}) or {}
    tiers = sz.get("tiers") or []
    if not sz.get("enabled", True) or not tiers:
        return f"Risk {c.get('broker', {}).get('risk_pct', 10)}% per trade"
    pcts = [float(t[1]) for t in tiers] + [float(sz.get("negative_risk_pct", min(float(t[1]) for t in tiers)))]
    return (f"Risk {min(pcts):g}-{max(pcts):g}% per trade by backtest win rate "
            f"({float(sz.get('base_risk_pct', 15)):g}% until a setup has {int(sz.get('low_sample_n', 20))}+ trades)")


@app.get("/api/reset_daily")
def api_reset_daily(confirm: int = 0):
    """Owner action from the desk: restart today's daily-loss window from the current balance (limit % unchanged)."""
    if confirm != 1:
        raise HTTPException(400, "add confirm=1")
    r = B().reset_daily_limit()
    J().set("paused", False)
    return dict(r, ok=True, paper=True, **_cur())


@app.get("/api/learning")
def api_learning():
    """Learned rules for the desk Learning tab: strategies (enabled, validation/test stats), blocks, changes, history."""
    from . import learning
    r = learning.load_rules()
    j = J()
    risk_eur = None
    try:                                                  # rough € per 1R at the base risk, so R can be read as money
        b = B()
        base = float((get_config().get("sizing", {}) or {}).get("base_risk_pct", 15))
        risk_eur = round(b.balance * base / 100, 2)
    except Exception:
        pass
    return {"ok": True, "paper": True, "rules": r, "names": learning.NAMES, "descriptions": {k: v["desc"] for k, v in
            learning.S.STRATEGIES.items()},
            "history": learning.history(), "status": j.get("learn_status"), "requested": bool(j.get("learn_request")),
            "eur_per_r": risk_eur, "base_risk_pct": float((get_config().get("sizing", {}) or {}).get("base_risk_pct", 15)), **_cur()}


@app.get("/api/learning/run")
def api_learning_run(confirm: int = 0):
    if confirm != 1:
        raise HTTPException(400, "add confirm=1")
    J().set("learn_request", int(time.time()))
    return {"ok": True, "queued": True, "note": "the bot runs the learning cycle within a minute (takes ~1 min)"}


@app.get("/api/learning/rollback")
def api_learning_rollback(version: int, confirm: int = 0):
    from . import learning
    if confirm != 1:
        raise HTTPException(400, "add confirm=1")
    try:
        r = learning.rollback(version)
    except FileNotFoundError:
        raise HTTPException(404, "no such version")
    return {"ok": True, "version": r["version"], "note": r["note"]}


@app.get("/api/calendar")
def api_calendar():
    return events.calendar()


@app.get("/api/news")
def api_news(symbol: str | None = None):
    n = events.news()
    if symbol:
        sym = instruments.normalize(symbol)
        n = dict(n, items=[i for i in n.get("items", []) if sym in i.get("symbols", [])])
    return n


def main():
    import uvicorn
    a = cfg.get("api", {})
    uvicorn.run(app, host=a.get("host", "127.0.0.1"), port=api_port(), log_level="info",
                proxy_headers=False)


if __name__ == "__main__":
    main()
