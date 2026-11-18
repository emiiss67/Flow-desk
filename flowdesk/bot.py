"""Telegram control. Only the configured chat is answered. Paper actions only."""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import httpx

from flowdesk.config import Settings, load_settings, normalize_timeframe
from flowdesk.engine import AmbiguousSymbol, Runtime, UnknownSymbol, account_view, manual_close, run_check, scan_once
from flowdesk.events import NewsClient
from flowdesk.models import DataUnavailable

log = logging.getLogger("flowdesk.bot")

HELP = (
    "FlowDesk paper desk\n"
    "/check SYMBOL [tf]\n"
    "/positions\n"
    "/pnl\n"
    "/pause\n"
    "/resume\n"
    "/close SYMBOL\n"
    "/watchlist\n"
    "/news\n"
    "/calendar\n"
    "/status"
)


class BotContext:
    def __init__(self, runtime: Runtime, chat_id: str | None, chat_file: str):
        self.runtime = runtime
        self.chat_id = chat_id or None
        self.chat_file = Path(chat_file)
        if self.chat_id is None and self.chat_file.exists():
            saved = self.chat_file.read_text(encoding="utf-8").strip()
            self.chat_id = saved or None

    def claim_chat(self, chat_id: int | str) -> None:
        self.chat_id = str(chat_id)
        self.chat_file.parent.mkdir(parents=True, exist_ok=True)
        self.chat_file.write_text(self.chat_id + "\n", encoding="utf-8")
        try:
            os.chmod(self.chat_file, 0o600)
        except OSError:
            pass


def _allowed(ctx: BotContext, chat_id) -> bool:
    return ctx.chat_id is not None and str(chat_id) == str(ctx.chat_id)


def _money(value: float | None, currency: str) -> str:
    if value is None:
        return "—"
    return f"{value:+.2f} {currency}" if not isinstance(value, str) else value


def handle_text(text: str, chat_id, ctx: BotContext) -> str | None:
    raw = (text or "").strip()
    if not raw:
        return None
    if ctx.chat_id is None:
        if raw.split()[0].split("@")[0] == "/start":
            ctx.claim_chat(chat_id)
            return (
                "FlowDesk paper desk.\n"
                f"Your chat id is {chat_id}.\n"
                "Saved. Only this chat can use this bot.\n"
                "You can also set FLOWDESK_TELEGRAM_CHAT_ID to this value."
            )
        return None
    if not _allowed(ctx, chat_id):
        return None
    head, _, rest = raw.partition(" ")
    command = head.split("@")[0].lower()
    rest = rest.strip()
    settings = ctx.runtime.settings
    if command in ("/start", "/help"):
        return HELP
    if command == "/status":
        state = ctx.runtime.store.load_state()
        return (
            "FlowDesk paper\n"
            f"scanner {'on' if settings.scanner_enabled else 'off'} · "
            f"{'paused' if state.paused else 'running'}\n"
            f"watchlist {len(settings.watchlist)} · tf {settings.scanner_timeframe}\n"
            f"auto {'on' if settings.auto_trade else 'off'}\n"
            f"balance {state.balance:.2f} {settings.currency}\n"
            f"last scan {ctx.runtime.store.get_kv('last_scan_at') or '—'}\n"
            f"provider {settings.market_provider}"
            + (" · OANDA practice" if ctx.runtime.market.oanda_enabled() else "")
        )
    if command == "/pause":
        ctx.runtime.store.set_paused(True)
        return "Scanner paused. Open paper positions still respect stops."
    if command == "/resume":
        ctx.runtime.store.set_paused(False)
        return "Scanner resumed. New paper entries are allowed again."
    if command == "/watchlist":
        return "Watchlist\n" + "\n".join(settings.watchlist)
    if command == "/positions":
        view = account_view(ctx.runtime)
        if not view["positions"]:
            return f"No open paper positions.\nBalance {view['balance']:.2f} {settings.currency}"
        lines = [f"{len(view['positions'])} open · balance {view['balance']:.2f}"]
        for pos in view["positions"]:
            try:
                inst = ctx.runtime.resolve(pos["symbol"])
                fmt = inst.format_price
            except (AmbiguousSymbol, UnknownSymbol):
                fmt = lambda price: f"{price:.5f}" if price is not None else "—"
            upnl = pos["unrealized"]
            upnl_text = "uPnL —" if upnl is None else f"uPnL {upnl:+.2f}"
            lines.append(
                f"{pos['symbol']} {pos['side']} @ {fmt(pos['entry'])} "
                f"SL {fmt(pos['sl'])} TP {fmt(pos['tp1'])} {upnl_text}"
            )
        return "\n".join(lines)
    if command == "/pnl":
        perf = ctx.runtime.store.performance()
        view = account_view(ctx.runtime)
        state = ctx.runtime.store.load_state()
        limit = state.day_start * settings.daily_loss_limit_pct / 100.0
        win = "—" if perf["win_rate"] is None else f"{perf['win_rate']:.0f}%"
        if perf["profit_factor"] is None:
            pf = "—" if not perf["no_losses"] else "no losses yet"
        else:
            pf = f"{perf['profit_factor']:.2f}"
        unreal = view["unrealized"]
        unreal_text = "—" if unreal is None else f"{unreal:+.2f}"
        return (
            f"Balance {state.balance:.2f} {settings.currency}\n"
            f"Open uPnL {unreal_text}\n"
            f"Today {state.realized_today:+.2f} / limit {limit:.0f}\n"
            f"Net {perf['net']:+.2f} · win {win} · PF {pf}\n"
            "PAPER"
        )
    if command == "/close":
        if not rest:
            return "Usage: /close EURUSD"
        _ok, message = manual_close(ctx.runtime, rest.split()[0])
        return message
    if command == "/check":
        if not rest:
            return "Usage: /check EURUSD M15"
        parts = rest.split()
        tf = None
        if len(parts) > 1:
            try:
                tf = normalize_timeframe(parts[1])
            except ValueError:
                return "Timeframe must be M5, M15, M30, H1, H4, or D1."
        try:
            result = run_check(ctx.runtime, parts[0], tf, source="telegram", journal=True)
        except AmbiguousSymbol as exc:
            names = ", ".join(item.id for item in exc.candidates[:8])
            return f"Ambiguous. Try one of: {names}"
        except UnknownSymbol:
            return "Unknown symbol."
        except DataUnavailable as exc:
            return f"data unavailable ({exc.detail})"
        return format_check(result)
    if command == "/news":
        client = NewsClient(settings.news_feeds, settings.news_cache_seconds)
        payload = client.load(ctx.runtime.catalog)
        if not payload.get("available"):
            return "News data unavailable."
        lines = []
        for item in payload["items"][:5]:
            lines.append(item["title"][:180])
        return "\n".join(lines) if lines else "News data unavailable."
    if command == "/calendar":
        payload = ctx.runtime.calendar.load()
        if not payload.get("available"):
            return "Calendar data unavailable."
        now = datetime.now(timezone.utc)
        lines = []
        for row in payload["events"]:
            impact = (row.get("impact") or "").lower()
            if impact not in ("high", "medium"):
                continue
            try:
                when = datetime.fromisoformat(row["time"])
            except ValueError:
                continue
            if when < now:
                continue
            stamp = when.astimezone(timezone.utc).strftime("%d %b %H:%M UTC")
            lines.append(f"{row['impact']} {row['currency']} {row['title']} · {stamp}")
            if len(lines) >= 6:
                break
        if payload.get("stale"):
            lines.append("(cached calendar)")
        return "\n".join(lines) if lines else "No upcoming high or medium events in the feed."
    return "Unknown command. /help"


def format_check(result) -> str:
    warnings = "\n".join(result.warnings[:3])
    reason = next((item.text for item in result.reasons if item.points > 0), None)
    if reason is None and result.reasons:
        reason = result.reasons[0].text
    lines = [
        f"{result.call} {result.symbol} {result.timeframe}",
        f"score {result.confidence}",
    ]
    if result.blocked_by_event and result.direction_if_clear:
        lines.append(f"setup underneath: {result.direction_if_clear}")
    if result.entry is not None:
        lines.append(f"entry {result.entry:.6g}")
        lines.append(f"SL {result.stop_loss:.6g}")
        lines.append(f"TP1 {result.take_profit_1:.6g} ({result.risk_reward_1}R)")
        lines.append(f"TP2 {result.take_profit_2:.6g}")
    if result.hypothetical and result.call == "NO TRADE":
        lines.append("reference levels only")
    if reason:
        lines.append(reason[:280])
    if warnings:
        lines.append(warnings[:400])
    flow = result.order_flow or {}
    if flow.get("available"):
        lines.append("order flow: estimate, not tick data")
    elif flow.get("reason"):
        lines.append(f"order flow unavailable: {flow['reason']}")
    src = (result.data or {}).get("source")
    if src:
        lines.append(src)
    lines.append("PAPER · no order sent")
    return "\n".join(lines)


def get_updates(token: str, offset: int | None, timeout: int = 25) -> list[dict]:
    params = {"timeout": timeout, "allowed_updates": '["message"]'}
    if offset is not None:
        params["offset"] = offset
    response = httpx.get(
        f"https://api.telegram.org/bot{token}/getUpdates",
        params=params,
        timeout=timeout + 10,
    )
    response.raise_for_status()
    body = response.json()
    if not body.get("ok"):
        raise RuntimeError("telegram getUpdates was not ok")
    return body.get("result") or []


def send_message(token: str, chat_id: str, text: str) -> None:
    httpx.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": text[:4000], "disable_web_page_preview": True},
        timeout=20,
    )


async def telegram_loop(token: str, ctx: BotContext) -> None:
    offset_raw = ctx.runtime.store.get_kv("tg_offset")
    offset = int(offset_raw) if offset_raw and offset_raw.isdigit() else None
    while True:
        try:
            updates = await asyncio.to_thread(get_updates, token, offset, 25)
        except Exception:
            log.exception("telegram poll failed")
            await asyncio.sleep(5)
            continue
        for update in updates:
            offset = int(update["update_id"]) + 1
            ctx.runtime.store.set_kv("tg_offset", str(offset))
            message = update.get("message") or {}
            chat = (message.get("chat") or {}).get("id")
            text = message.get("text") or ""
            if chat is None:
                continue
            try:
                reply = await asyncio.to_thread(handle_text, text, chat, ctx)
            except Exception:
                log.exception("telegram command failed")
                reply = "Command failed. The paper book was not changed by an incomplete order."
            if reply and ctx.chat_id is not None and str(chat) == str(ctx.chat_id):
                try:
                    await asyncio.to_thread(send_message, token, str(chat), reply)
                except Exception:
                    log.exception("telegram send failed")


async def scanner_loop(runtime: Runtime, token: str, ctx: BotContext) -> None:
    while True:
        alerts: list[str] = []
        try:
            alerts = await asyncio.to_thread(scan_once, runtime)
        except Exception:
            log.exception("scan failed")
        chat_id = ctx.chat_id
        if token and chat_id:
            for line in alerts:
                try:
                    await asyncio.to_thread(send_message, token, chat_id, line)
                except Exception:
                    log.exception("alert send failed")
        await asyncio.sleep(max(15, runtime.settings.scanner_interval))


async def async_main(settings: Settings) -> None:
    runtime = Runtime(settings)
    chat_file = str(runtime.store.path.parent / "telegram_chat_id")
    ctx = BotContext(runtime, settings.telegram_chat_id or None, chat_file)
    tasks = [asyncio.create_task(scanner_loop(runtime, settings.telegram_token, ctx))]
    if settings.telegram_token:
        tasks.append(asyncio.create_task(telegram_loop(settings.telegram_token, ctx)))
    else:
        log.warning("FLOWDESK_TELEGRAM_TOKEN is empty. Scanner will run without Telegram.")
    await asyncio.gather(*tasks)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = load_settings()
    asyncio.run(async_main(settings))


if __name__ == "__main__":
    main()
