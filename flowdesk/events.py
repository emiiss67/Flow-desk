"""Real-world event awareness: economic calendar (ForexFactory weekly JSON via faireconomy) and RSS headlines."""
from __future__ import annotations
import json
import logging
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import httpx

from .config import get_config, data_dir
from . import instruments

log = logging.getLogger("flowdesk.events")
CAL_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36 FlowDesk/0.1"
_lock = threading.Lock()
_mem: dict = {}

# Headline keyword -> extra instruments (beyond currency mapping)
TONE_UP = re.compile(r"\b(surge|soar|rall(y|ies)|jump|beat|hawkish|record high|gain|climb)s?\b", re.I)
TONE_DOWN = re.compile(r"\b(plunge|slump|tumble|drop|fall|miss|dovish|selloff|sell-off|slide|sink)s?\b", re.I)


def _cache_get(name: str, max_age: float):
    with _lock:
        hit = _mem.get(name)
    if hit and time.time() - hit[0] < max_age:
        return hit[1]
    f = data_dir() / f"cache_{name}.json"
    if f.exists() and time.time() - f.stat().st_mtime < max_age:
        try:
            val = json.loads(f.read_text())
            with _lock:
                _mem[name] = (f.stat().st_mtime, val)
            return val
        except Exception:
            pass
    return None


def _cache_put(name: str, val) -> None:
    with _lock:
        _mem[name] = (time.time(), val)
    try:
        (data_dir() / f"cache_{name}.json").write_text(json.dumps(val))
    except Exception:
        pass


def _stale(name: str):
    f = data_dir() / f"cache_{name}.json"
    if f.exists():
        try:
            return json.loads(f.read_text())
        except Exception:
            return None
    return None


def calendar() -> dict:
    """Returns {"events": [...], "source": ..., "ok": bool}. Cached (faireconomy rate-limits frequent pulls)."""
    cfg = get_config().get("events", {})
    cached = _cache_get("calendar", cfg.get("calendar_cache_minutes", 30) * 60)
    if cached is not None:
        return cached
    try:
        r = httpx.get(CAL_URL, headers={"User-Agent": UA}, timeout=15)
        r.raise_for_status()
        raw = r.json()
        evs = []
        for e in raw:
            try:
                t = datetime.fromisoformat(e["date"]).astimezone(timezone.utc)
            except Exception:
                continue
            evs.append({"title": e.get("title", ""), "ccy": e.get("country", ""), "impact": e.get("impact", ""),
                        "time": t.isoformat(), "ts": int(t.timestamp()), "forecast": e.get("forecast", ""),
                        "previous": e.get("previous", "")})
        val = {"ok": True, "source": "ForexFactory weekly calendar (faireconomy.media)", "events": evs,
               "fetched": int(time.time())}
        _cache_put("calendar", val)
        return val
    except Exception as e:
        log.warning("calendar fetch failed: %s", e)
        old = _stale("calendar")
        if old:
            old["stale"] = True
            return old
        return {"ok": False, "source": "ForexFactory weekly calendar", "events": [], "error": "data unavailable"}


def events_for(symbol: str, hours_ahead: float = 12, impacts=("High",), include_past_minutes: float = 0) -> list[dict]:
    info = instruments.info(symbol)
    ccys = set(info["ccy"])
    now = time.time()
    out = []
    for e in calendar().get("events", []):
        if e["ccy"] not in ccys or e["impact"] not in impacts:
            continue
        if now - include_past_minutes * 60 <= e["ts"] <= now + hours_ahead * 3600:
            out.append(dict(e, minutes_away=round((e["ts"] - now) / 60)))
    return sorted(out, key=lambda x: x["ts"])


def blackout(symbol: str) -> dict | None:
    """High-impact event within the configured window for this instrument -> no new entries."""
    cfg = get_config().get("events", {})
    before, after = cfg.get("block_minutes_before", 30), cfg.get("block_minutes_after", 15)
    for e in events_for(symbol, hours_ahead=before / 60, include_past_minutes=after):
        return e
    return None


def _parse_date(s: str) -> int:
    try:
        return int(parsedate_to_datetime(s).timestamp())
    except Exception:
        try:
            return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp())
        except Exception:
            return int(time.time())


def news(limit: int = 60) -> dict:
    cfg = get_config().get("events", {})
    cached = _cache_get("news", cfg.get("news_cache_minutes", 5) * 60)
    if cached is not None:
        return cached
    import feedparser
    items, errors = [], []
    for url in cfg.get("rss_feeds", []):
        try:
            r = httpx.get(url, headers={"User-Agent": UA}, timeout=12, follow_redirects=True)
            r.raise_for_status()
            feed = feedparser.parse(r.content)
            src = feed.feed.get("title", url.split("/")[2])
            for en in feed.entries[:30]:
                title = re.sub(r"\s+", " ", en.get("title", "")).strip()
                if not title:
                    continue
                items.append({"title": title, "link": en.get("link", ""), "source": src,
                              "ts": _parse_date(en.get("published", en.get("updated", "")))})
        except Exception as e:
            errors.append(f"{url.split('/')[2]}: {type(e).__name__}")
    seen, uniq = set(), []
    for it in sorted(items, key=lambda x: -x["ts"]):
        k = it["title"].lower()[:80]
        if k in seen:
            continue
        seen.add(k)
        it["symbols"] = map_headline(it["title"])
        tone = "up" if TONE_UP.search(it["title"]) else "down" if TONE_DOWN.search(it["title"]) else ""
        it["tone"] = tone  # simple keyword tone, not a sentiment model
        uniq.append(it)
    val = {"ok": bool(uniq), "items": uniq[:limit], "errors": errors, "fetched": int(time.time()),
           "source": "RSS: " + ", ".join(u.split("/")[2] for u in cfg.get("rss_feeds", []))}
    if uniq:
        _cache_put("news", val)
    else:
        old = _stale("news")
        if old:
            old["stale"] = True
            return old
        val["error"] = "data unavailable"
    return val


def map_headline(title: str) -> list[str]:
    t = " " + title.lower() + " "
    hits = []
    for i in instruments.CATALOG:
        for kw in i["kw"]:
            if kw and kw in t:
                hits.append(i["symbol"])
                break
    return hits[:8]


def news_for(symbol: str, hours: float = 24, limit: int = 5) -> list[dict]:
    sym = instruments.normalize(symbol)
    cutoff = time.time() - hours * 3600
    return [n for n in news().get("items", []) if sym in n.get("symbols", []) and n["ts"] >= cutoff][:limit]
