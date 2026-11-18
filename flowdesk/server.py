"""Desk HTTP API. Read-only except /api/check, which computes and never opens a trade.

Binds to 127.0.0.1 by default. Put a tunnel in front of it; do not expose it directly.
"""

from __future__ import annotations

import logging
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from flowdesk import __version__
from flowdesk.catalog import search
from flowdesk.config import load_settings, normalize_timeframe
from flowdesk.engine import AmbiguousSymbol, Runtime, UnknownSymbol, account_view, run_check
from flowdesk.events import NewsClient, event_public
from flowdesk.models import DataUnavailable

log = logging.getLogger("flowdesk.api")


def ensure_desk_key(path: str) -> str:
    file = Path(path)
    file.parent.mkdir(parents=True, exist_ok=True)
    if file.exists():
        existing = file.read_text(encoding="utf-8").strip()
        if existing:
            return existing
    key = secrets.token_urlsafe(24)
    file.write_text(key + "\n", encoding="utf-8")
    try:
        os.chmod(file, 0o600)
    except OSError:
        pass
    print(f"FlowDesk desk key created at {file}")
    return key


def create_app(runtime: Runtime, desk_key: str, news: NewsClient | None = None) -> FastAPI:
    settings = runtime.settings
    news_client = news or NewsClient(settings.news_feeds, settings.news_cache_seconds)
    app = FastAPI(title="FlowDesk", version=__version__, docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    def authorized(request: Request) -> None:
        provided = request.headers.get("x-flowdesk-key") or request.query_params.get("key") or ""
        if not provided or not secrets.compare_digest(provided, desk_key):
            raise HTTPException(status_code=401, detail="unauthorized")

    @app.get("/")
    def root():
        return {"ok": True, "service": "flowdesk", "paper": True, "version": __version__}

    @app.get("/api/health")
    def health(request: Request):
        authorized(request)
        state = runtime.store.load_state()
        return {
            "ok": True,
            "paper": True,
            "name": "FlowDesk",
            "version": __version__,
            "paused": state.paused,
            "provider": settings.market_provider,
            "oanda_enabled": runtime.market.oanda_enabled(),
            "server_time": datetime.now(timezone.utc).isoformat(),
        }

    @app.get("/api/status")
    def status(request: Request):
        authorized(request)
        state = runtime.store.load_state()
        oanda_account = {"enabled": runtime.market.oanda_enabled()}
        if runtime.market.oanda_enabled():
            try:
                summary = runtime.market.oanda.account_summary()
                oanda_account.update(
                    {
                        "available": True,
                        "alias": summary.get("alias"),
                        "currency": summary.get("currency"),
                        "balance": summary.get("balance"),
                        "note": "OANDA practice balance is informational. Paper fills do not use it.",
                    }
                )
            except DataUnavailable as exc:
                oanda_account.update({"available": False, "error": "data unavailable", "detail": exc.detail})
        return {
            "paper": True,
            "paused": state.paused,
            "balance": state.balance,
            "currency": settings.currency,
            "watchlist": settings.watchlist,
            "timeframe": settings.scanner_timeframe,
            "auto_trade": settings.auto_trade,
            "scanner_enabled": settings.scanner_enabled,
            "risk_per_trade_pct": settings.risk_per_trade_pct,
            "max_positions": settings.max_positions,
            "daily_loss_limit_pct": settings.daily_loss_limit_pct,
            "min_score": settings.min_score,
            "event_blackout_minutes": settings.event_blackout_minutes,
            "last_scan_at": runtime.store.get_kv("last_scan_at"),
            "provider": settings.market_provider,
            "oanda": oanda_account,
            "host": settings.host,
            "port": settings.port,
        }

    @app.get("/api/dashboard")
    def dashboard(request: Request):
        authorized(request)
        board = runtime.store.dashboard()
        view = account_view(runtime)
        state = runtime.store.load_state()
        limit = state.day_start * (settings.daily_loss_limit_pct / 100.0)
        used = 0.0 if limit <= 0 else max(0.0, -state.realized_today) / limit * 100.0
        if state.paused:
            status_today = "Paused"
        elif state.realized_today <= -limit + 1e-9:
            status_today = "Loss limit"
        else:
            status_today = "Clean"
        equity = None
        if view["unrealized"] is not None:
            equity = state.balance + view["unrealized"]
        board.update(
            {
                "owner_name": settings.owner_name,
                "currency": settings.currency,
                "equity": equity,
                "unrealized": view["unrealized"],
                "open_positions": len(view["positions"]),
                "daily_loss_limit": limit,
                "daily_loss_used_pct": used,
                "status_today": status_today,
                "watchlist_count": len(settings.watchlist),
                "positions": view["positions"],
            }
        )
        board.pop("_limit_unused", None)
        return board

    @app.get("/api/positions")
    def positions(request: Request):
        authorized(request)
        return account_view(runtime)

    @app.get("/api/signals")
    def signals(request: Request, limit: int = 50):
        authorized(request)
        return {"paper": True, "signals": runtime.store.list_signals(max(1, min(limit, 200)))}

    @app.get("/api/journal")
    def journal(request: Request, limit: int = 100):
        authorized(request)
        entries = runtime.store.list_signals(max(1, min(limit, 300)))
        trades = runtime.store.list_trades(limit=300)
        by_signal = {trade["signal_id"]: trade for trade in trades if trade.get("signal_id")}
        for entry in entries:
            entry["trade"] = by_signal.get(entry["id"])
        return {"paper": True, "entries": entries}

    @app.get("/api/performance")
    def performance(request: Request):
        authorized(request)
        return runtime.store.performance()

    @app.get("/api/calendar")
    def calendar(request: Request):
        authorized(request)
        payload = runtime.calendar.load()
        if not payload.get("available"):
            return JSONResponse(status_code=200, content=payload)
        public = []
        for row in payload["events"]:
            from datetime import datetime as dt

            event = __import__("flowdesk.models", fromlist=["CalendarEvent"]).CalendarEvent(
                title=row["title"],
                currency=row["currency"],
                impact=row["impact"],
                time=dt.fromisoformat(row["time"]),
                forecast=row.get("forecast") or "",
                previous=row.get("previous") or "",
            )
            public.append(event_public(event, runtime.catalog))
        return {
            "available": True,
            "error": None,
            "detail": payload.get("detail"),
            "stale": payload.get("stale", False),
            "as_of": payload.get("as_of"),
            "events": public,
        }

    @app.get("/api/news")
    def news(request: Request):
        authorized(request)
        return news_client.load(runtime.catalog)

    @app.get("/api/watchlist")
    def watchlist(request: Request):
        authorized(request)
        details = []
        for symbol in settings.watchlist:
            try:
                details.append(runtime.resolve(symbol).to_dict())
            except (AmbiguousSymbol, UnknownSymbol):
                details.append({"id": symbol, "name": symbol, "error": "unknown symbol"})
        return {"symbols": settings.watchlist, "details": details}

    @app.get("/api/instruments")
    def instruments(request: Request, q: str = "", category: str = ""):
        authorized(request)
        found = search(q, category or None, runtime.catalog)
        return {"instruments": [item.to_dict() for item in found[:80]]}

    def _chart_payload(symbol: str, timeframe: str | None):
        try:
            tf = normalize_timeframe(timeframe, settings.scanner_timeframe)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        try:
            result = run_check(runtime, symbol, tf, source="chart", journal=False)
        except AmbiguousSymbol as exc:
            return JSONResponse(
                status_code=400,
                content={
                    "error": "ambiguous symbol",
                    "candidates": [item.to_dict() for item in exc.candidates[:12]],
                },
            )
        except UnknownSymbol:
            return JSONResponse(status_code=400, content={"error": "unknown symbol"})
        except DataUnavailable as exc:
            return JSONResponse(status_code=503, content={"error": "data unavailable", "detail": exc.detail})
        return {
            "paper_only": True,
            "symbol": result.symbol,
            "display": result.display,
            "timeframe": result.timeframe,
            "candles": result.candles,
            "overlays": result.overlays,
            "order_flow": result.order_flow,
            "structure": result.structure,
            "data": result.data,
        }

    @app.get("/api/candles")
    def candles(request: Request, symbol: str, timeframe: str = "M15"):
        authorized(request)
        payload = _chart_payload(symbol, timeframe)
        if isinstance(payload, JSONResponse):
            return payload
        return {
            "symbol": payload["symbol"],
            "timeframe": payload["timeframe"],
            "candles": payload["candles"],
            "data": payload["data"],
            "order_flow": payload["order_flow"],
        }

    @app.get("/api/chart")
    def chart(request: Request, symbol: str, timeframe: str = "M15"):
        authorized(request)
        return _chart_payload(symbol, timeframe)

    def _check(symbol: str, timeframe: str | None):
        try:
            tf = normalize_timeframe(timeframe, settings.scanner_timeframe)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        try:
            result = run_check(runtime, symbol, tf, source="check", journal=True)
        except AmbiguousSymbol as exc:
            return JSONResponse(
                status_code=400,
                content={
                    "error": "ambiguous symbol",
                    "candidates": [item.to_dict() for item in exc.candidates[:12]],
                },
            )
        except UnknownSymbol:
            return JSONResponse(status_code=400, content={"error": "unknown symbol"})
        except DataUnavailable as exc:
            return JSONResponse(status_code=503, content={"error": "data unavailable", "detail": exc.detail})
        body = result.to_dict()
        body["placed_trade"] = False
        return body

    @app.api_route("/api/check", methods=["GET", "POST"])
    async def check(request: Request, symbol: str | None = None, timeframe: str | None = None):
        authorized(request)
        if request.method == "POST":
            try:
                payload = await request.json()
            except Exception:
                payload = {}
            if isinstance(payload, dict):
                symbol = symbol or payload.get("symbol")
                timeframe = timeframe or payload.get("timeframe")
        if not symbol:
            raise HTTPException(status_code=400, detail="symbol is required")
        return _check(symbol, timeframe)

    return app


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = load_settings()
    if settings.host not in ("127.0.0.1", "localhost", "::1"):
        log.warning("server host is %s; the intended bind is 127.0.0.1 behind a tunnel", settings.host)
    key = ensure_desk_key(settings.desk_key_file)
    runtime = Runtime(settings)
    app = create_app(runtime, key)
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
