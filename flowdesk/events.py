"""Economic calendar and headline feeds.

Failures stay failures. A stale cache is returned only when it is labeled stale.
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlparse
import xml.etree.ElementTree as ET

import httpx

from flowdesk.models import CalendarEvent, DataUnavailable, Instrument

log = logging.getLogger("flowdesk.events")

KEYWORDS = {
    "EUR": ["eur", "euro", "ecb", "lagarde"],
    "USD": ["usd", "dollar", "fed", "fomc", "powell", "nfp", "cpi", "treasury", "fomc"],
    "GBP": ["gbp", "sterling", "boe"],
    "JPY": ["jpy", "yen", "boj"],
    "CHF": ["chf", "snb", "swiss franc"],
    "AUD": ["aud", "rba", "aussie"],
    "CAD": ["cad", "boc", "loonie"],
    "NZD": ["nzd", "rbnz", "kiwi"],
    "XAU": ["gold", "xau"],
    "XAG": ["silver", "xag"],
    "BTC": ["bitcoin", "btc"],
    "ETH": ["ethereum", "ether", "eth"],
}
INDEX_WORDS = ["s&p", "nasdaq", "dow", "stocks", "wall street", "dax", "ftse", "nikkei"]
OIL_WORDS = ["crude", "wti", "opec", "brent", "oil"]


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def parse_calendar_payload(payload) -> list[CalendarEvent]:
    if isinstance(payload, dict):
        rows = payload.get("events") or payload.get("data")
    else:
        rows = payload
    if not isinstance(rows, list):
        raise DataUnavailable("calendar payload was not a list of events")
    events: list[CalendarEvent] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        title = str(row.get("title") or "").strip()
        raw_time = row.get("date") or row.get("time")
        if not title or not raw_time:
            continue
        try:
            moment = _aware(datetime.fromisoformat(str(raw_time).replace("Z", "+00:00")))
        except ValueError:
            continue
        events.append(
            CalendarEvent(
                title=title,
                currency=str(row.get("country") or row.get("currency") or "").upper(),
                impact=str(row.get("impact") or "Low"),
                time=moment,
                forecast=str(row.get("forecast") or ""),
                previous=str(row.get("previous") or ""),
            )
        )
    events.sort(key=lambda item: item.time)
    return events


def event_public(event: CalendarEvent, instruments: list[Instrument] | tuple[Instrument, ...]) -> dict:
    from flowdesk.strategy import event_affects

    affects = [inst.id for inst in instruments if event_affects(event, inst)]
    return {
        "title": event.title,
        "currency": event.currency,
        "impact": event.impact,
        "time": event.time.astimezone(timezone.utc).isoformat(),
        "forecast": event.forecast,
        "previous": event.previous,
        "affects": affects,
    }


class CalendarClient:
    def __init__(self, url: str, cache_seconds: int = 1800, cache_file: str | None = None, fetcher=None):
        self.url = url
        self.cache_seconds = cache_seconds
        self.cache_file = Path(cache_file) if cache_file else None
        self.fetcher = fetcher or self._http
        self._memory: dict | None = None

    def _http(self) -> str:
        try:
            response = httpx.get(self.url, timeout=20, headers={"User-Agent": "FlowDesk/0.1"})
        except httpx.HTTPError as exc:
            raise DataUnavailable(f"calendar request failed ({exc.__class__.__name__})") from exc
        if response.status_code != 200:
            raise DataUnavailable(f"calendar request returned HTTP {response.status_code}")
        return response.text

    def load(self) -> dict:
        now = time.time()
        if self._memory and now - self._memory["fetched_at"] < self.cache_seconds:
            return self._public_from_memory()
        cached = self._read_file()
        try:
            body = self.fetcher()
            payload = json.loads(body)
            events = parse_calendar_payload(payload)
        except (DataUnavailable, json.JSONDecodeError, ValueError) as exc:
            detail = exc.detail if isinstance(exc, DataUnavailable) else "calendar payload could not be parsed"
            if cached:
                self._memory = cached
                result = self._public_from_memory()
                result["stale"] = True
                result["detail"] = f"Using the cached calendar. Fresh fetch failed: {detail}"
                return result
            return {
                "available": False,
                "error": "data unavailable",
                "detail": detail,
                "events": [],
                "stale": False,
                "as_of": None,
            }
        self._memory = {
            "fetched_at": now,
            "events": [
                {
                    "title": event.title,
                    "currency": event.currency,
                    "impact": event.impact,
                    "time": event.time.isoformat(),
                    "forecast": event.forecast,
                    "previous": event.previous,
                }
                for event in events
            ],
        }
        self._write_file(self._memory)
        return self._public_from_memory()

    def typed_events(self) -> tuple[list[CalendarEvent], bool]:
        payload = self.load()
        if not payload.get("available"):
            return [], False
        events = []
        for row in payload["events"]:
            events.append(
                CalendarEvent(
                    title=row["title"],
                    currency=row["currency"],
                    impact=row["impact"],
                    time=_aware(datetime.fromisoformat(row["time"])),
                    forecast=row.get("forecast") or "",
                    previous=row.get("previous") or "",
                )
            )
        return events, True

    def _public_from_memory(self) -> dict:
        memory = self._memory or {"events": [], "fetched_at": None}
        return {
            "available": True,
            "error": None,
            "detail": None,
            "stale": False,
            "as_of": datetime.fromtimestamp(memory["fetched_at"], timezone.utc).isoformat() if memory.get("fetched_at") else None,
            "events": memory["events"],
        }

    def _read_file(self) -> dict | None:
        if not self.cache_file or not self.cache_file.exists():
            return None
        try:
            return json.loads(self.cache_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def _write_file(self, payload: dict) -> None:
        if not self.cache_file:
            return
        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            self.cache_file.write_text(json.dumps(payload), encoding="utf-8")
        except OSError:
            log.warning("could not write calendar cache")


def _contains(text: str, keyword: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])", text) is not None


def headline_score(title: str, instrument: Instrument) -> int:
    text = title.lower()
    score = 0
    for currency in instrument.currencies:
        for keyword in KEYWORDS.get(currency.upper(), []):
            if _contains(text, keyword):
                score += 2
                break
    if instrument.category in ("indices", "futures") and any(_contains(text, word) for word in INDEX_WORDS):
        score += 1
    if instrument.id == "CL" and any(_contains(text, word) for word in OIL_WORDS):
        score += 2
    return score


def parse_feed(xml_text: str, source: str) -> list[dict]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise DataUnavailable(f"{source} was not valid RSS or Atom") from exc
    items: list[dict] = []
    for node in root.findall(".//item"):
        title = (node.findtext("title") or "").strip()
        if not title:
            continue
        items.append(
            {
                "title": title,
                "link": (node.findtext("link") or "").strip(),
                "published": (node.findtext("pubDate") or "").strip(),
                "source": source,
            }
        )
    atom = "{http://www.w3.org/2005/Atom}"
    for node in root.findall(f".//{atom}entry"):
        title = (node.findtext(f"{atom}title") or "").strip()
        if not title:
            continue
        link = ""
        for link_node in node.findall(f"{atom}link"):
            link = link_node.attrib.get("href") or ""
            if link:
                break
        items.append(
            {
                "title": title,
                "link": link,
                "published": (node.findtext(f"{atom}updated") or node.findtext(f"{atom}published") or "").strip(),
                "source": source,
            }
        )
    return items


def _published_sort_key(value: str) -> float:
    if not value:
        return 0.0
    try:
        return parsedate_to_datetime(value).timestamp()
    except (TypeError, ValueError, IndexError):
        pass
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


class NewsClient:
    def __init__(self, feeds: list[str], cache_seconds: int = 600, fetcher=None):
        self.feeds = feeds
        self.cache_seconds = cache_seconds
        self.fetcher = fetcher or self._http
        self._memory: dict | None = None

    def _http(self, url: str) -> str:
        try:
            response = httpx.get(url, timeout=15, headers={"User-Agent": "FlowDesk/0.1"}, follow_redirects=True)
        except httpx.HTTPError as exc:
            raise DataUnavailable(f"news request failed ({exc.__class__.__name__})") from exc
        if response.status_code != 200:
            raise DataUnavailable(f"news request returned HTTP {response.status_code}")
        return response.text

    def load(self, instruments: list[Instrument] | tuple[Instrument, ...]) -> dict:
        now = time.time()
        if self._memory and now - self._memory["fetched_at"] < self.cache_seconds:
            return self._decorate(self._memory["items"], instruments, partial=self._memory.get("partial"))
        if not self.feeds:
            return {"available": False, "error": "data unavailable", "detail": "no news feeds configured", "items": []}
        collected: list[dict] = []
        errors: list[str] = []
        for url in self.feeds:
            source = urlparse(url).netloc or url
            try:
                if self.fetcher is self._http:
                    body = self._http(url)
                else:
                    body = self.fetcher(url)
                collected.extend(parse_feed(body, source))
            except DataUnavailable as exc:
                errors.append(f"{source}: {exc.detail}")
        if not collected:
            return {
                "available": False,
                "error": "data unavailable",
                "detail": "; ".join(errors) or "no headlines",
                "items": [],
            }
        # De-duplicate by title.
        seen: set[str] = set()
        unique: list[dict] = []
        for item in collected:
            key = item["title"].strip().lower()
            if key in seen:
                continue
            seen.add(key)
            unique.append(item)
        unique.sort(key=lambda item: _published_sort_key(item.get("published") or ""), reverse=True)
        self._memory = {"fetched_at": now, "items": unique[:40], "partial": "; ".join(errors) if errors else None}
        return self._decorate(self._memory["items"], instruments, partial=self._memory["partial"])

    def _decorate(self, items: list[dict], instruments, partial: str | None) -> dict:
        decorated = []
        for item in items:
            scored = []
            for inst in instruments:
                score = headline_score(item["title"], inst)
                if score > 0:
                    scored.append((score, inst.id))
            scored.sort(key=lambda pair: (-pair[0], pair[1]))
            decorated.append(
                {
                    "title": item["title"],
                    "link": item.get("link") or "",
                    "published": item.get("published") or "",
                    "source": item.get("source") or "",
                    "matches": [inst_id for _, inst_id in scored[:8]],
                    "score": scored[0][0] if scored else 0,
                }
            )
        return {
            "available": True,
            "error": None,
            "detail": partial,
            "items": decorated,
        }
