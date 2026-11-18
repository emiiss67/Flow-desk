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


NEWS_V = 2  # bump when filtering/tagging changes so old caches are ignored


def news(limit: int = 60) -> dict:
    cfg = get_config().get("events", {})
    cached = _cache_get("news", cfg.get("news_cache_minutes", 5) * 60)
    if cached is not None and cached.get("v") == NEWS_V:
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
    seen, uniq, dropped = set(), [], 0
    for it in sorted(items, key=lambda x: -x["ts"]):
        k = it["title"].lower()[:80]
        if k in seen:
            continue
        seen.add(k)
        if relevance(it["title"]) <= 0:
            dropped += 1
            continue
        it["symbols"] = map_headline(it["title"])
        it["why"] = why_it_matters(it["title"])
        tone = "up" if TONE_UP.search(it["title"]) else "down" if TONE_DOWN.search(it["title"]) else ""
        it["tone"] = tone  # simple keyword tone, not a sentiment model
        uniq.append(it)
    val = {"ok": bool(uniq), "items": uniq[:limit], "errors": errors, "fetched": int(time.time()), "filtered_out": dropped, "v": NEWS_V,
           "source": "RSS: " + ", ".join(u.split("/")[2] for u in cfg.get("rss_feeds", []))}
    if uniq:
        _cache_put("news", val)
    else:
        old = _stale("news")
        if old and old.get("v") == NEWS_V:
            old["stale"] = True
            return old
        val["error"] = "data unavailable"
    return val


# ---- headline relevance: drop personal-finance / advice / lifestyle stories, tag only markets they really move ----
_W = lambda *ws: re.compile(r"\b(" + "|".join(ws) + r")\b", re.I)
JUNK = _W(r"my (husband|wife|son|daughter|mother|father|mom|dad|brother|sister|parents|boyfriend|girlfriend|partner|kids?)",
          r"husband", r"wife", r"retire[ds]?", r"retirement", r"inheritance", r"inherit(ed)?", r"widow(ed)?", r"divorce",
          r"401\(?k\)?", r"roth", r"\bira\b", r"social security", r"annuit(y|ies)", r"estate plan\w*", r"will and trust",
          r"dear \w+", r"moneyist", r"should i", r"am i", r"can i", r"how (much|do i|to save)", r"credit score", r"credit card debt",
          r"mortgage rates? today", r"best (cd|savings|credit card|mortgage)\w*", r"savings account", r"budget(ing)? tips?",
          r"horoscope", r"recipe", r"celebrit\w+", r"movie", r"box office", r"netflix series", r"nfl", r"nba", r"super bowl",
          r"oscars?", r"grammys?", r"concerts?", r"album", r"taylor swift", r"tour dates?", r"tv show", r"wedding", r"dating", r"travel deals?", r"vacation", r"podcast", r"quiz", r"sponsored",
          r"opinion", r"op-ed", r"letters?", r"my (stocks|portfolio|money|savings|house|home|job|boss)", r"has me", r"real estate",
          r"video games?", r"gta( \d)?", r"tiktok", r"viral", r"lunch", r"medicare")
MOVERS = _W(r"fed", r"fomc", r"powell", r"rate (cut|hike|decision)s?", r"interest rates?", r"inflation", r"cpi", r"ppi", r"pce",
            r"jobs report", r"payrolls?", r"nfp", r"unemployment", r"jobless", r"gdp", r"recession", r"pmi", r"retail sales",
            r"treasur(y|ies)", r"yields?", r"bonds?", r"ecb", r"lagarde", r"boe", r"bank of england", r"boj", r"bank of japan",
            r"snb", r"rba", r"central bank", r"tariffs?", r"trade war", r"sanctions?", r"opec\+?", r"crude", r"oil", r"brent",
            r"gold", r"silver", r"copper", r"dollar", r"euro", r"yen", r"sterling", r"pound", r"forex", r"fx", r"currenc(y|ies)",
            r"stocks?", r"futures", r"s&p", r"nasdaq", r"dow", r"wall street", r"equities", r"earnings", r"guidance", r"nvidia",
            r"apple", r"microsoft", r"tesla", r"bitcoin", r"crypto", r"ether(eum)?", r"china", r"stimulus", r"default", r"debt ceiling",
            r"shutdown", r"geopolitic\w*", r"war", r"ceasefire", r"rally", r"sell-?off", r"slump", r"surge", r"plunge", r"volatility",
            r"dax", r"ftse", r"nikkei", r"economy", r"jobs", r"employment", r"wages", r"exports?", r"(consumer|wholesale) prices",
            r"rate hikes?", r"hikes? rates", r"intervention")
# headline topic -> markets; only these specific rules tag markets (no generic 'stocks' -> every index)
TAG_RULES = [
    (_W(r"ecb", r"lagarde", r"euro", r"eurozone"), ["EURUSD=X"]),
    (_W(r"germany", r"german", r"dax"), ["^GDAXI", "EURUSD=X"]),
    (_W(r"boe", r"bank of england", r"bailey", r"sterling", r"pound", r"gilts?"), ["GBPUSD=X"]),
    (_W(r"ftse"), ["^FTSE"]),
    (_W(r"boj", r"bank of japan", r"ueda", r"yen"), ["USDJPY=X"]),
    (_W(r"nikkei"), ["^N225"]),
    (_W(r"rba", r"aussie", r"australian dollar"), ["AUDUSD=X"]),
    (_W(r"bank of canada", r"loonie", r"canadian dollar"), ["USDCAD=X"]),
    (_W(r"snb", r"swiss franc"), ["USDCHF=X"]),
    (_W(r"rbnz", r"new zealand dollar", r"kiwi"), ["NZDUSD=X"]),
    (_W(r"s&p", r"wall street", r"stocks?", r"equities", r"stock market"), ["ES=F"]),
    (_W(r"nasdaq", r"tech stocks?", r"nvidia", r"apple", r"microsoft", r"alphabet", r"amazon", r"meta", r"tesla", r"chipmakers?", r"semiconductors?", r"\bai\b"), ["NQ=F"]),
    (_W(r"dow", r"dow jones"), ["YM=F"]),
    (_W(r"russell", r"small[- ]caps?"), ["RTY=F"]),
    (_W(r"gold", r"bullion"), ["GC=F"]),
    (_W(r"silver"), ["SI=F"]),
    (_W(r"oil", r"crude", r"opec\+?", r"wti", r"brent"), ["CL=F"]),
    (_W(r"natural gas", r"lng"), ["NG=F"]),
    (_W(r"copper"), ["HG=F"]),
    (_W(r"bitcoin", r"btc", r"crypto"), ["BTC-USD"]),
    (_W(r"ether(eum)?"), ["ETH-USD"]),
    (_W(r"uk", r"united kingdom", r"britain", r"british"), ["GBPUSD=X"]),
    (_W(r"japan", r"japanese"), ["USDJPY=X"]),
    (_W(r"australia", r"australian"), ["AUDUSD=X"]),
    (_W(r"canada", r"canadian"), ["USDCAD=X"]),
]
BROAD_RULES = [  # applied after the specific ones, so 'Silver ... amid Fed bets' is tagged Silver first
    (_W(r"fed", r"fomc", r"powell", r"us inflation", r"cpi", r"pce", r"payrolls?", r"nfp", r"jobs report", r"jobless",
        r"u\.?s\.? (economy|jobs|inflation)", r"(consumer|wholesale) prices", r"adp", r"jobs"), ["EURUSD=X", "USDJPY=X", "GC=F", "ES=F"]),
    (_W(r"treasur(y|ies)", r"yields?", r"bonds?"), ["ZN=F", "USDJPY=X"]),
    (_W(r"dollar", r"greenback"), ["EURUSD=X", "USDJPY=X"]),
]
WHY = [  # first match wins; short plain-English reason the headline can move prices
    (_W(r"fed", r"fomc", r"powell", r"rate (cut|hike|decision)s?", r"central bank", r"ecb", r"boe", r"boj", r"bank of (england|japan|canada)", r"snb", r"rba"),
     "Interest-rate news moves currencies, gold and stock indices."),
    (_W(r"inflation", r"cpi", r"ppi", r"pce"), "Inflation data changes rate expectations, so the dollar, gold and stocks react."),
    (_W(r"payrolls?", r"nfp", r"jobs report", r"jobless", r"unemployment"), "Jobs data is one of the biggest monthly movers for the dollar and US stocks."),
    (_W(r"gdp", r"recession", r"pmi", r"retail sales"), "Growth data shifts how strong the economy looks, which moves currencies and stocks."),
    (_W(r"tariffs?", r"trade war", r"sanctions?"), "Trade barriers hit company profits and currencies of the countries involved."),
    (_W(r"opec\+?", r"crude", r"oil", r"brent", r"wti"), "Supply and demand news moves oil prices."),
    (_W(r"treasur(y|ies)", r"yields?", r"bonds?"), "Bond yields drive the dollar and how much investors pay for stocks."),
    (_W(r"earnings", r"guidance", r"nvidia", r"apple", r"microsoft", r"tesla"), "Big company results can move the whole index they are in."),
    (_W(r"gold", r"bullion"), "Gold moves on the dollar, rates and fear in markets."),
    (_W(r"bitcoin", r"crypto"), "Crypto prices react quickly to regulation and risk mood."),
    (_W(r"war", r"ceasefire", r"geopolitic\w*", r"attack"), "Conflict news makes investors buy safe havens (gold, yen) and sell riskier assets."),
]


def relevance(title: str) -> int:
    """>0 = market-moving enough to show. Advice columns, personal stories and entertainment score below zero."""
    t = title or ""
    return len(MOVERS.findall(t)) - 3 * len(JUNK.findall(t))


def map_headline(title: str) -> list[str]:
    hits: list[str] = []
    for rules in (TAG_RULES, BROAD_RULES):      # broad (Fed / dollar / yields) only when nothing specific matched
        for rx, syms in rules:
            if rx.search(title or ""):
                hits += [x for x in syms if x not in hits]
        if hits:
            break
    return hits[:4]


def why_it_matters(title: str) -> str:
    for rx, txt in WHY:
        if rx.search(title or ""):
            return txt
    return ""


def news_for(symbol: str, hours: float = 24, limit: int = 5) -> list[dict]:
    sym = instruments.normalize(symbol)
    cutoff = time.time() - hours * 3600
    return [n for n in news().get("items", []) if sym in n.get("symbols", []) and n["ts"] >= cutoff][:limit]
