"""YAML config plus environment secrets. Secrets are never read from the file."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ALLOWED_TIMEFRAMES = ("M5", "M15", "M30", "H1", "H4", "D1")

_TF_ALIASES = {
    "5": "M5",
    "5M": "M5",
    "M5": "M5",
    "15": "M15",
    "15M": "M15",
    "M15": "M15",
    "30": "M30",
    "30M": "M30",
    "M30": "M30",
    "60": "H1",
    "1H": "H1",
    "H1": "H1",
    "60M": "H1",
    "4H": "H4",
    "H4": "H4",
    "240": "H4",
    "1D": "D1",
    "D": "D1",
    "D1": "D1",
    "1DAY": "D1",
}


def normalize_timeframe(value: str | None, default: str = "M15") -> str:
    if not value:
        return default
    key = value.strip().upper().replace(" ", "")
    found = _TF_ALIASES.get(key)
    if not found:
        raise ValueError(f"unsupported timeframe {value}")
    return found


def higher_timeframe(timeframe: str) -> str | None:
    return {
        "M5": "M15",
        "M15": "H1",
        "M30": "H1",
        "H1": "H4",
        "H4": "D1",
        "D1": None,
    }.get(timeframe)


@dataclass
class Settings:
    owner_name: str = "Trader"
    database: str = "data/flowdesk.sqlite"
    desk_key_file: str = "data/desk.key"
    catalog: str = "flowdesk/catalog.json"
    host: str = "127.0.0.1"
    port: int = 8787
    cors_origins: list[str] = field(default_factory=lambda: ["https://emiiss67.github.io"])
    starting_balance: float = 10000.0
    currency: str = "USD"
    risk_per_trade_pct: float = 1.0
    max_positions: int = 3
    daily_loss_limit_pct: float = 3.0
    trailing_enabled: bool = True
    trail_atr_mult: float = 1.5
    scanner_enabled: bool = True
    scanner_interval: int = 120
    scanner_timeframe: str = "M15"
    scanner_higher_timeframe: str = "H1"
    auto_trade: bool = True
    event_blackout_minutes: int = 30
    min_score: int = 55
    event_alert_minutes: int = 30
    swing_left: int = 2
    swing_right: int = 2
    atr_period: int = 14
    min_bars: int = 40
    watchlist: list[str] = field(default_factory=list)
    market_provider: str = "auto"
    market_cache_seconds: int = 45
    calendar_url: str = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
    calendar_cache_seconds: int = 1800
    news_cache_seconds: int = 600
    news_feeds: list[str] = field(default_factory=list)
    pages_base: str = "https://emiiss67.github.io/Flow-desk/"
    config_path: str = "config.yaml"

    @property
    def telegram_token(self) -> str:
        return os.environ.get("FLOWDESK_TELEGRAM_TOKEN", "").strip()

    @property
    def telegram_chat_id(self) -> str:
        return os.environ.get("FLOWDESK_TELEGRAM_CHAT_ID", "").strip()

    @property
    def oanda_key(self) -> str:
        return os.environ.get("OANDA_API_KEY", "").strip()

    @property
    def oanda_account(self) -> str:
        return os.environ.get("OANDA_ACCOUNT_ID", "").strip()

    @property
    def oanda_enabled(self) -> bool:
        return bool(self.oanda_key and self.oanda_account)


def _section(raw: dict, key: str) -> dict:
    value = raw.get(key) or {}
    if not isinstance(value, dict):
        raise ValueError(f"config section {key} must be a mapping")
    return value


def load_settings(path: str | None = None) -> Settings:
    config_path = path or os.environ.get("FLOWDESK_CONFIG", "config.yaml")
    file = Path(config_path)
    raw: dict = {}
    if file.exists():
        loaded = yaml.safe_load(file.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded, dict):
            raise ValueError("config root must be a mapping")
        raw = loaded
    server = _section(raw, "server")
    paper = _section(raw, "paper")
    scanner = _section(raw, "scanner")
    strategy = _section(raw, "strategy")
    market = _section(raw, "market")
    calendar = _section(raw, "calendar")
    news = _section(raw, "news")
    tunnel = _section(raw, "tunnel")
    timeframe = normalize_timeframe(str(scanner.get("timeframe", "M15")))
    higher = scanner.get("higher_timeframe")
    if higher:
        higher_tf = normalize_timeframe(str(higher))
    else:
        higher_tf = higher_timeframe(timeframe) or "H1"
    origins = server.get("cors_origins") or ["https://emiiss67.github.io"]
    return Settings(
        owner_name=str(raw.get("owner_name") or "Trader"),
        database=str(raw.get("database") or "data/flowdesk.sqlite"),
        desk_key_file=str(raw.get("desk_key_file") or "data/desk.key"),
        catalog=str(raw.get("catalog") or "flowdesk/catalog.json"),
        host=str(server.get("host") or "127.0.0.1"),
        port=int(server.get("port") or 8787),
        cors_origins=[str(item) for item in origins],
        starting_balance=float(paper.get("starting_balance", 10000)),
        currency=str(paper.get("currency") or "USD"),
        risk_per_trade_pct=float(paper.get("risk_per_trade_pct", 1)),
        max_positions=int(paper.get("max_positions", 3)),
        daily_loss_limit_pct=float(paper.get("daily_loss_limit_pct", 3)),
        trailing_enabled=bool(paper.get("trailing_enabled", True)),
        trail_atr_mult=float(paper.get("trail_atr_mult", 1.5)),
        scanner_enabled=bool(scanner.get("enabled", True)),
        scanner_interval=int(scanner.get("interval_seconds", 120)),
        scanner_timeframe=timeframe,
        scanner_higher_timeframe=higher_tf,
        auto_trade=bool(scanner.get("auto_trade", True)),
        event_blackout_minutes=int(scanner.get("event_blackout_minutes", 30)),
        min_score=int(scanner.get("min_score", 55)),
        event_alert_minutes=int(scanner.get("event_alert_minutes", 30)),
        swing_left=int(strategy.get("swing_left", 2)),
        swing_right=int(strategy.get("swing_right", 2)),
        atr_period=int(strategy.get("atr_period", 14)),
        min_bars=int(strategy.get("min_bars", 40)),
        watchlist=[str(item) for item in (raw.get("watchlist") or [])],
        market_provider=str(market.get("provider") or "auto"),
        market_cache_seconds=int(market.get("cache_seconds", 45)),
        calendar_url=str(calendar.get("url") or "https://nfs.faireconomy.media/ff_calendar_thisweek.json"),
        calendar_cache_seconds=int(calendar.get("cache_seconds", 1800)),
        news_cache_seconds=int(news.get("cache_seconds", 600)),
        news_feeds=[str(item) for item in (news.get("feeds") or [])],
        pages_base=str(tunnel.get("pages_base") or "https://emiiss67.github.io/Flow-desk/"),
        config_path=str(file),
    )
