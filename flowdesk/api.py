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


@app.middleware("http")
async def auth_mw(request: Request, call_next):
    if request.method == "OPTIONS" or request.url.path == "/health":
        return await call_next(request)
    key = request.headers.get("x-desk-key") or request.query_params.get("key")
    if not check_key(key):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return await call_next(request)


@app.get("/health")
def health():
    return {"ok": True, "paper": True, "version": __version__}


@app.get("/api/check")
def api_check(symbol: str = Query(..., max_length=24), tf: str = "15m"):
    if tf not in TIMEFRAMES:
        raise HTTPException(400, f"tf must be one of {list(TIMEFRAMES)}")
    try:
        return run_check(symbol, tf)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/chart")
def api_chart(symbol: str = Query(..., max_length=24), tf: str = "15m"):
    r = api_check(symbol, tf)
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


@app.get("/api/positions")
def api_positions():
    return {"positions": _positions(), "paper": True}


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
    return {"trades": ts}


@app.get("/api/performance")
def api_performance():
    b = B()
    p = performance(J(), b.start_balance)
    eq = J().q("SELECT ts, equity FROM equity ORDER BY ts DESC LIMIT 2000")
    p["equity_snapshots"] = [{"time": r["ts"], "value": round(r["equity"], 2)} for r in reversed(eq)]
    p["balance"], p["equity"], p["start_balance"] = round(b.balance, 2), round(b.equity(), 2), b.start_balance
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
        "plan": [f"Risk {bc.get('risk_pct', 0.5)}% per trade",
                 f"Max {bc.get('max_positions', 4)} open positions",
                 f"Stop after -{bc.get('daily_loss_limit_pct', 2)}% day",
                 f"No entries {cfg.get('events', {}).get('block_minutes_before', 30)} min before high-impact news",
                 f"Min confluence {cfg.get('strategy', {}).get('min_score', 55)}/100",
                 f"TP1 closes {bc.get('tp1_close_pct', 50)}%, stop to breakeven"],
        "upcoming_events": ev, "watchlist": cfg.get("watchlist", []),
        "source": get_provider().name,
    }


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
