"""Market data providers (pluggable). Default: Yahoo Finance via yfinance (free; futures may be delayed)."""
from __future__ import annotations
import logging
import threading
import time
from abc import ABC, abstractmethod

import pandas as pd

from .config import get_config, secret

log = logging.getLogger("flowdesk.data")

TIMEFRAMES = {  # tf -> (yahoo interval, yahoo period, resample rule or None)
    "1m": ("1m", "5d", None),
    "5m": ("5m", "30d", None),
    "15m": ("15m", "45d", None),
    "30m": ("30m", "45d", None),
    "1h": ("1h", "180d", None),
    "4h": ("1h", "365d", "4h"),
    "1d": ("1d", "3y", None),
}
HTF = {"1m": "15m", "5m": "1h", "15m": "1h", "30m": "4h", "1h": "4h", "4h": "1d", "1d": "1d"}


TF_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "1d": 86400}


def delay_seconds(symbol: str) -> int:
    """Yahoo futures / index quotes run about 10 minutes behind; forex and crypto are live."""
    return 660 if symbol.endswith("=F") or symbol.startswith("^") else 0


def closed_bars(df: pd.DataFrame, symbol: str, tf: str, now: float | None = None) -> pd.DataFrame:
    """Drop the still-forming candle(s): a bar counts only once its close time (+ the feed delay) has passed.
    The backtest only ever sees closed bars, so live signals must too (a forming candle can flip before it closes)."""
    import time as _t
    if df is None or df.empty:
        return df
    now = _t.time() if now is None else now
    cut = now - TF_SECONDS.get(tf, 900) - delay_seconds(symbol)
    ts = df.index.map(lambda x: x.timestamp())
    return df[ts <= cut]


class DataUnavailable(Exception):
    pass


def resample(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.resample(rule, label="left", closed="left", origin="epoch").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
    return out.dropna(subset=["open", "close"])


class MarketDataProvider(ABC):
    name = "base"
    delayed_note = ""

    @abstractmethod
    def candles(self, symbol: str, tf: str) -> pd.DataFrame:
        """Return OHLCV with a tz-aware UTC DatetimeIndex and lowercase columns."""


class YahooProvider(MarketDataProvider):
    name = "Yahoo Finance"
    delayed_note = "Free Yahoo data. Futures/indices can be delayed 10-15 min; forex volume is not provided."

    def __init__(self, cache_seconds: int = 45):
        self.cache_seconds = cache_seconds
        self._cache: dict = {}
        self._lock = threading.Lock()

    def _fetch(self, symbol: str, interval: str, period: str) -> pd.DataFrame:
        import yfinance as yf
        key = (symbol, interval, period)
        with self._lock:
            hit = self._cache.get(key)
            if hit and time.time() - hit[0] < self.cache_seconds:
                return hit[1]
        try:
            df = yf.Ticker(symbol).history(period=period, interval=interval, auto_adjust=False, prepost=True)
        except Exception as e:  # network or yahoo errors
            raise DataUnavailable(f"Yahoo request failed for {symbol}: {e}") from e
        if df is None or df.empty:
            raise DataUnavailable(f"No data from Yahoo for {symbol}")
        df = df.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]].copy()
        df.index = pd.to_datetime(df.index, utc=True)
        df = df[~df.index.duplicated(keep="last")].dropna(subset=["open", "high", "low", "close"])
        df["volume"] = df["volume"].fillna(0).astype(float)
        with self._lock:
            self._cache[key] = (time.time(), df)
        return df

    def candles(self, symbol: str, tf: str) -> pd.DataFrame:
        if tf not in TIMEFRAMES:
            raise ValueError(f"unsupported timeframe {tf}")
        interval, period, rule = TIMEFRAMES[tf]
        df = self._fetch(symbol, interval, period)
        if rule:
            df = resample(df, rule)
        return df


class OandaProvider(MarketDataProvider):
    """OANDA v20 practice API - prices only (enabled only when OANDA_API_KEY and OANDA_ACCOUNT_ID are set)."""
    name = "OANDA practice"
    delayed_note = "OANDA practice prices (live). Volume is tick count, not exchange volume."
    GRAN = {"1m": "M1", "5m": "M5", "15m": "M15", "30m": "M30", "1h": "H1", "4h": "H4", "1d": "D"}
    MAP = {"GC=F": "XAU_USD", "SI=F": "XAG_USD", "CL=F": "WTICO_USD", "BZ=F": "BCO_USD", "NG=F": "NATGAS_USD",
           "ES=F": "SPX500_USD", "^GSPC": "SPX500_USD", "NQ=F": "NAS100_USD", "^NDX": "NAS100_USD",
           "YM=F": "US30_USD", "^DJI": "US30_USD", "^GDAXI": "DE30_EUR", "^FTSE": "UK100_GBP", "^N225": "JP225_USD",
           "RTY=F": "US2000_USD", "HG=F": "XCU_USD", "BTC-USD": "BTC_USD"}

    def __init__(self, fallback: MarketDataProvider):
        self.key = secret("OANDA_API_KEY")
        self.env = secret("OANDA_ENV") or "practice"
        self.fallback = fallback
        host = "api-fxpractice.oanda.com" if self.env == "practice" else "api-fxtrade.oanda.com"
        self.base = f"https://{host}/v3"

    def instrument(self, symbol: str) -> str | None:
        if symbol.endswith("=X") and len(symbol) == 8:
            return f"{symbol[:3]}_{symbol[3:6]}"
        return self.MAP.get(symbol)

    def candles(self, symbol: str, tf: str) -> pd.DataFrame:
        import httpx
        inst = self.instrument(symbol)
        if not inst:
            return self.fallback.candles(symbol, tf)
        try:
            r = httpx.get(f"{self.base}/instruments/{inst}/candles",
                          params={"granularity": self.GRAN[tf], "count": 500, "price": "M"},
                          headers={"Authorization": f"Bearer {self.key}"}, timeout=15)
            r.raise_for_status()
            rows = [{"time": c["time"], "open": float(c["mid"]["o"]), "high": float(c["mid"]["h"]),
                     "low": float(c["mid"]["l"]), "close": float(c["mid"]["c"]), "volume": float(c["volume"])}
                    for c in r.json().get("candles", [])]
        except Exception as e:
            log.warning("OANDA failed (%s), falling back to Yahoo", e)
            return self.fallback.candles(symbol, tf)
        if not rows:
            raise DataUnavailable(f"No OANDA data for {symbol}")
        df = pd.DataFrame(rows)
        df.index = pd.to_datetime(df.pop("time"), utc=True)
        return df


_provider: MarketDataProvider | None = None


def get_provider() -> MarketDataProvider:
    global _provider
    if _provider is None:
        cfg = get_config().get("data", {})
        yahoo = YahooProvider(cfg.get("cache_seconds", 45))
        if cfg.get("provider") == "oanda" or (secret("OANDA_API_KEY") and secret("OANDA_ACCOUNT_ID")):
            _provider = OandaProvider(yahoo) if secret("OANDA_API_KEY") and secret("OANDA_ACCOUNT_ID") else yahoo
        else:
            _provider = yahoo
    return _provider


def set_provider(p: MarketDataProvider | None) -> None:
    global _provider
    _provider = p
