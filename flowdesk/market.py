"""Pluggable market data. Yahoo Finance by default, OANDA practice when configured.

Neither provider can place orders. OANDA is pinned to the practice host.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone

import httpx

from flowdesk.models import Bar, DataUnavailable, Instrument, MarketSnapshot

log = logging.getLogger("flowdesk.market")

OANDA_HOST = "https://api-fxpractice.oanda.com"

YAHOO_INTERVALS = {
    "M5": ("5m", "5d", None),
    "M15": ("15m", "60d", None),
    "M30": ("30m", "60d", None),
    "H1": ("60m", "60d", None),
    "H4": ("60m", "180d", "H4"),
    "D1": ("1d", "2y", None),
}

OANDA_GRANULARITY = {
    "M5": "M5",
    "M15": "M15",
    "M30": "M30",
    "H1": "H1",
    "H4": "H4",
    "D1": "D",
}

_DELAY = {
    "forex": "Yahoo Finance forex is indicative and can be delayed.",
    "indices": "Yahoo Finance index values can be delayed.",
    "futures": "Yahoo Finance futures are often delayed by about 10–15 minutes and follow the front contract.",
    "commodities": "Yahoo Finance futures are often delayed by about 10–15 minutes and follow the front contract.",
    "crypto": "Yahoo Finance crypto prices are aggregated and can lag the venue you watch.",
    "custom": "Yahoo Finance data for this ticker. Delay depends on the listing.",
}


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def parse_oanda_time(raw: str) -> datetime:
    text = raw.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    if "." in text:
        left, right = text.split(".", 1)
        split_at = None
        for index, char in enumerate(right):
            if char in "+-":
                split_at = index
                break
        if split_at is None:
            frac, tz = right, ""
        else:
            frac, tz = right[:split_at], right[split_at:]
        text = f"{left}.{(frac + '000000')[:6]}{tz}"
    parsed = datetime.fromisoformat(text)
    return _as_utc(parsed)


def bars_from_ohlcv_rows(rows: list[tuple[datetime, float, float, float, float, float]]) -> list[Bar]:
    bars: list[Bar] = []
    for ts, open_, high, low, close, volume in rows:
        high = max(high, open_, close, low)
        low = min(low, open_, close, high)
        if high < low:
            continue
        bars.append(
            Bar(
                time=_as_utc(ts),
                open=float(open_),
                high=float(high),
                low=float(low),
                close=float(close),
                volume=float(volume or 0),
            )
        )
    if not bars:
        raise DataUnavailable("the feed returned no usable candles")
    bars.sort(key=lambda bar: bar.time)
    return bars


def resample_h4(bars: list[Bar]) -> list[Bar]:
    buckets: dict[datetime, list[Bar]] = {}
    for bar in bars:
        ts = _as_utc(bar.time)
        hour = ts.hour - (ts.hour % 4)
        key = ts.replace(hour=hour, minute=0, second=0, microsecond=0)
        buckets.setdefault(key, []).append(bar)
    out: list[Bar] = []
    for key in sorted(buckets):
        group = buckets[key]
        out.append(
            Bar(
                time=key,
                open=group[0].open,
                high=max(item.high for item in group),
                low=min(item.low for item in group),
                close=group[-1].close,
                volume=sum(item.volume for item in group),
            )
        )
    return out


def bars_from_yahoo_frame(frame) -> list[Bar]:
    import pandas as pd

    if frame is None or len(frame) == 0:
        raise DataUnavailable("Yahoo Finance returned no candles")
    df = frame.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    lookup = {str(column).lower().replace(" ", ""): column for column in df.columns}
    required = ("open", "high", "low", "close")
    for name in required:
        if name not in lookup:
            raise DataUnavailable(f"Yahoo Finance frame is missing {name}")
    volume_col = lookup.get("volume")
    rows: list[tuple[datetime, float, float, float, float, float]] = []
    for ts, row in df.iterrows():
        open_ = row[lookup["open"]]
        close = row[lookup["close"]]
        if pd.isna(open_) or pd.isna(close):
            continue
        high = row[lookup["high"]]
        low = row[lookup["low"]]
        if pd.isna(high) or pd.isna(low):
            continue
        volume = 0.0
        if volume_col is not None and not pd.isna(row[volume_col]):
            volume = float(row[volume_col])
        stamp = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts
        rows.append((stamp, float(open_), float(high), float(low), float(close), volume))
    return bars_from_ohlcv_rows(rows)


class YahooProvider:
    name = "yahoo"

    def fetch(self, instrument: Instrument, timeframe: str, limit: int = 300) -> MarketSnapshot:
        if timeframe not in YAHOO_INTERVALS:
            raise DataUnavailable(f"unsupported timeframe {timeframe}")
        interval, period, resample = YAHOO_INTERVALS[timeframe]
        try:
            import yfinance as yf

            logging.getLogger("yfinance").setLevel(logging.CRITICAL)
            frame = yf.Ticker(instrument.yahoo).history(
                period=period,
                interval=interval,
                auto_adjust=False,
                actions=False,
            )
        except DataUnavailable:
            raise
        except Exception as exc:  # network, parse, or library failure
            raise DataUnavailable(f"Yahoo Finance request failed ({exc.__class__.__name__})") from exc
        try:
            bars = bars_from_yahoo_frame(frame)
        except DataUnavailable:
            raise DataUnavailable(f"Yahoo Finance returned no candles for {instrument.yahoo}")
        if resample == "H4":
            bars = resample_h4(bars)
        if not bars:
            raise DataUnavailable(f"Yahoo Finance returned no candles for {instrument.yahoo}")
        bars = bars[-limit:]
        return MarketSnapshot(
            bars=bars,
            source="Yahoo Finance",
            provider_symbol=instrument.yahoo,
            delay_note=_DELAY.get(instrument.category, _DELAY["custom"]),
            as_of=bars[-1].time,
        )


class OandaProvider:
    """Practice-host candles and account summary. No order routes exist here."""

    name = "oanda"

    def __init__(self, api_key: str | None = None, account_id: str | None = None):
        self.api_key = (api_key if api_key is not None else os.environ.get("OANDA_API_KEY", "")).strip()
        self.account_id = (account_id if account_id is not None else os.environ.get("OANDA_ACCOUNT_ID", "")).strip()

    @property
    def enabled(self) -> bool:
        return bool(self.api_key and self.account_id)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Accept-Datetime-Format": "RFC3339"}

    def fetch(self, instrument: Instrument, timeframe: str, limit: int = 300) -> MarketSnapshot:
        if not self.enabled:
            raise DataUnavailable("OANDA practice feed is disabled. Set OANDA_API_KEY and OANDA_ACCOUNT_ID.")
        if not instrument.oanda:
            raise DataUnavailable(f"{instrument.id} has no OANDA practice symbol")
        if timeframe not in OANDA_GRANULARITY:
            raise DataUnavailable(f"unsupported timeframe {timeframe}")
        params = {
            "granularity": OANDA_GRANULARITY[timeframe],
            "count": str(max(10, min(limit, 500))),
            "price": "M",
        }
        url = f"{OANDA_HOST}/v3/instruments/{instrument.oanda}/candles"
        try:
            response = httpx.get(url, params=params, headers=self._headers(), timeout=20)
        except httpx.HTTPError as exc:
            raise DataUnavailable(f"OANDA practice request failed ({exc.__class__.__name__})") from exc
        if response.status_code != 200:
            raise DataUnavailable(f"OANDA practice returned HTTP {response.status_code} for {instrument.oanda}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise DataUnavailable("OANDA practice returned a response that was not JSON") from exc
        rows: list[tuple[datetime, float, float, float, float, float]] = []
        for candle in payload.get("candles") or []:
            if candle.get("complete") is False:
                continue
            mid = candle.get("mid") or {}
            try:
                rows.append(
                    (
                        parse_oanda_time(candle["time"]),
                        float(mid["o"]),
                        float(mid["h"]),
                        float(mid["l"]),
                        float(mid["c"]),
                        float(candle.get("volume") or 0),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        try:
            bars = bars_from_ohlcv_rows(rows)
        except DataUnavailable:
            raise DataUnavailable(f"OANDA practice returned no candles for {instrument.oanda}")
        bars = bars[-limit:]
        return MarketSnapshot(
            bars=bars,
            source="OANDA practice",
            provider_symbol=instrument.oanda,
            delay_note="OANDA practice pricing (v20). Near-live for that practice environment, not an exchange footprint.",
            as_of=bars[-1].time,
        )

    def account_summary(self) -> dict:
        if not self.enabled:
            raise DataUnavailable("OANDA practice feed is disabled")
        url = f"{OANDA_HOST}/v3/accounts/{self.account_id}/summary"
        try:
            response = httpx.get(url, headers=self._headers(), timeout=15)
        except httpx.HTTPError as exc:
            raise DataUnavailable(f"OANDA practice account request failed ({exc.__class__.__name__})") from exc
        if response.status_code != 200:
            raise DataUnavailable(f"OANDA practice account summary returned HTTP {response.status_code}")
        body = response.json()
        account = body.get("account")
        if not isinstance(account, dict):
            raise DataUnavailable("OANDA practice account summary had no account object")
        return account


class MarketRouter:
    def __init__(self, provider_mode: str = "auto", cache_seconds: int = 45, oanda: OandaProvider | None = None):
        self.provider_mode = provider_mode
        self.cache_seconds = cache_seconds
        self.yahoo = YahooProvider()
        self.oanda = oanda or OandaProvider()
        self._cache: dict[tuple, tuple[float, MarketSnapshot]] = {}
        self._lock = threading.Lock()

    def oanda_enabled(self) -> bool:
        return self.oanda.enabled and self.provider_mode in ("auto", "oanda")

    def fetch(self, instrument: Instrument, timeframe: str, limit: int = 300) -> MarketSnapshot:
        mode = self._select(instrument)
        key = (mode, instrument.id, instrument.yahoo, instrument.oanda, timeframe, limit)
        now = time.time()
        with self._lock:
            hit = self._cache.get(key)
            if hit and now - hit[0] < self.cache_seconds:
                return hit[1]
        snapshot = self._fetch_uncached(instrument, timeframe, limit, mode)
        with self._lock:
            self._cache[key] = (time.time(), snapshot)
        return snapshot

    def _select(self, instrument: Instrument) -> str:
        if self.provider_mode == "yahoo":
            return "yahoo"
        if self.provider_mode == "oanda":
            if self.oanda.enabled and instrument.oanda:
                return "oanda"
            return "yahoo"
        if self.oanda.enabled and instrument.oanda:
            return "oanda"
        return "yahoo"

    def _fetch_uncached(self, instrument: Instrument, timeframe: str, limit: int, mode: str) -> MarketSnapshot:
        if mode == "oanda":
            try:
                return self.oanda.fetch(instrument, timeframe, limit)
            except DataUnavailable:
                if self.provider_mode == "auto":
                    log.warning("OANDA practice failed for %s; falling back to Yahoo Finance", instrument.id)
                    return self.yahoo.fetch(instrument, timeframe, limit)
                raise
        return self.yahoo.fetch(instrument, timeframe, limit)
