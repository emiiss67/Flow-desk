"""End-of-day sessions: flat before each market's daily close, no new entries near it (owner request 2026-11-26).

Every session ends at `close_time` New York time (17:00 NY = the CME Globex daily halt and the FX / metals / energy /
index-futures rollover; the zone is handled with zoneinfo, so US daylight-saving changes move the Vilnius time but never the
NY time). The bot goes flat `flat_minutes_before` (default 15 -> 16:45 NY) before it, at the market price with the normal
spread + slippage, reason 'EOD close', and opens nothing from `no_entry_minutes_before` (default 45 -> 16:15 NY) until the
market reopens (`reopen_time`, 18:00 NY; after the Friday close: Sunday 18:00 NY).

  * FX, metals (GC), energy (CL), index futures (NQ/ES/YM/RTY): Mon-Fri sessions, weekend closed.
  * Crypto (BTC) trades 24/7, so it simply uses the same daily cut (flat 16:45 NY, no entries 16:15-17:00 NY, trades again
    from 17:00 NY, weekends included). One consistent 'trading day' for the review.
  * `early_closes` lists exchange holiday hours (date in NY time, symbols, close_time); the flat / no-entry times follow.
Everything is configurable under `eod:` in config.yaml (`enabled: false` turns it all off; per-symbol `overrides`)."""
from __future__ import annotations

import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from . import instruments
from .config import get_config

VILNIUS = ZoneInfo("Europe/Vilnius")
DEFAULTS = {"enabled": True, "tz": "America/New_York", "close_time": "17:00", "flat_minutes_before": 15,
            "no_entry_minutes_before": 45, "reopen_time": "18:00", "weekend_closed": True}
_clock = time.time          # tests replace this (conftest) so entry-time tests never depend on the wall clock


def now() -> float:
    return float(_clock())


def cfg(c: dict | None = None) -> dict:
    g = dict(DEFAULTS)
    g.update(((c or get_config()).get("eod") or {}))
    return g


def settings(symbol: str, c: dict | None = None) -> dict:
    """Per-symbol settings: base eod config, then the category block (Crypto...), then overrides[symbol]."""
    g = cfg(c)
    sym = instruments.normalize(symbol)
    out = {k: g[k] for k in DEFAULTS}
    cat = instruments.info(sym).get("category")
    out.update(((g.get("categories") or {}).get(cat)) or {})
    out.update(((g.get("overrides") or {}).get(sym)) or {})
    out["symbol"], out["category"], out["tz"] = sym, cat, g["tz"]
    out["early_closes"] = [e for e in (g.get("early_closes") or []) if sym in [instruments.normalize(s) for s in e.get("symbols", [])]]
    return out


def _hm(s: str) -> tuple[int, int]:
    h, m = str(s).split(":")
    return int(h), int(m)


def _at(d: date, hhmm: str, tz: ZoneInfo) -> datetime:
    h, m = _hm(hhmm)
    return datetime(d.year, d.month, d.day, h, m, tzinfo=tz)


def sessions(symbol: str, ts: float | None = None, c: dict | None = None) -> list[dict]:
    """Session ends around `ts` (NY dates today-3 .. today+3), oldest first:
    {date, close, flat, no_entry, reopen} as Unix timestamps."""
    s = settings(symbol, c)
    tz = ZoneInfo(s["tz"])
    ts = now() if ts is None else ts
    today = datetime.fromtimestamp(ts, tz).date()
    early = {str(e["date"]): e for e in s["early_closes"]}
    out = []
    for k in range(-3, 4):
        d = today + timedelta(days=k)
        if s["weekend_closed"] and d.weekday() >= 5:
            continue                                           # Sat/Sun: no session end (Sunday reopens at 18:00 NY)
        e = early.get(d.isoformat())
        close = _at(d, (e or {}).get("close_time") or s["close_time"], tz)
        rt = (e or {}).get("reopen_time") or s["reopen_time"]
        if s["weekend_closed"] and d.weekday() == 4:
            reopen = _at(d + timedelta(days=2), rt, tz)         # Friday close -> Sunday reopen
        else:
            reopen = max(_at(d, rt, tz), close)
        out.append({"date": d.isoformat(), "close": int(close.timestamp()),
                    "flat": int((close - timedelta(minutes=float(s["flat_minutes_before"]))).timestamp()),
                    "no_entry": int((close - timedelta(minutes=float(s["no_entry_minutes_before"]))).timestamp()),
                    "reopen": int(reopen.timestamp())})
    return out


def status(symbol: str, ts: float | None = None, c: dict | None = None) -> dict:
    """Where the symbol is in its trading day. state: open | no_entry (flat soon, no new entries) | flat (must be flat /
    market closed). Includes the current or next session end."""
    s = settings(symbol, c)
    ts = now() if ts is None else ts
    if not s.get("enabled", True):
        return {"enabled": False, "state": "open", "symbol": s["symbol"]}
    cur = next(x for x in sessions(symbol, ts, c) if x["reopen"] > ts)
    state = "open" if ts < cur["no_entry"] else "no_entry" if ts < cur["flat"] else "flat"
    return dict(cur, enabled=True, state=state, symbol=s["symbol"], now=int(ts))


def entry_block(symbol: str, ts: float | None = None, c: dict | None = None) -> tuple[bool, str]:
    """(True, why) when no new trade may open on this symbol: the last `no_entry_minutes_before` before the close, the
    break/weekend until reopen."""
    try:
        st = status(symbol, ts, c)
    except Exception:
        return False, ""
    if not st.get("enabled") or st["state"] == "open":
        return False, ""
    ny = ZoneInfo(settings(symbol, c)["tz"])
    return True, (f"end of day: no new entries from {datetime.fromtimestamp(st['no_entry'], ny).strftime('%H:%M')} NY "
                  f"until the market reopens at {datetime.fromtimestamp(st['reopen'], ny).strftime('%a %H:%M')} NY")


def last_flat(symbol: str, ts: float | None = None, c: dict | None = None) -> int | None:
    """Latest flat-time (session end minus flat_minutes_before) that has already passed."""
    if not settings(symbol, c).get("enabled", True):
        return None
    ts = now() if ts is None else ts
    done = [x["flat"] for x in sessions(symbol, ts, c) if x["flat"] <= ts]
    return max(done) if done else None


def due(trades: list[dict], ts: float | None = None, since: float = 0, c: dict | None = None) -> list[dict]:
    """Open trades that must be closed now: opened before the latest flat-time that has passed (a flat-time older than
    `since`, the moment the feature went live, never closes older trades retroactively)."""
    out = []
    ts = now() if ts is None else ts
    for t in trades:
        try:
            f = last_flat(t["symbol"], ts, c)
        except Exception:
            continue
        if f is not None and f >= since and int(t["opened_ts"]) < f:
            out.append(t)
    return out


def fmt_times(ts: int, tz: str = "America/New_York") -> str:
    return datetime.fromtimestamp(ts, ZoneInfo(tz)).strftime("%a %d %b %H:%M")


def describe(symbol: str, ts: float | None = None, c: dict | None = None) -> dict:
    """Plain-data schedule for /status, the API and the desk: times in NY and Vilnius."""
    st = status(symbol, ts, c)
    if not st.get("enabled"):
        return {"symbol": st["symbol"], "enabled": False}
    ny = settings(symbol, c)["tz"]
    def both(k):
        return {"ts": st[k], "ny": datetime.fromtimestamp(st[k], ZoneInfo(ny)).strftime("%Y-%m-%d %H:%M"),
                "vilnius": datetime.fromtimestamp(st[k], VILNIUS).strftime("%Y-%m-%d %H:%M")}
    return {"symbol": st["symbol"], "name": instruments.display(st["symbol"]), "enabled": True, "state": st["state"],
            "no_entry": both("no_entry"), "flat": both("flat"), "close": both("close"), "reopen": both("reopen")}


def schedule(c: dict | None = None, ts: float | None = None) -> list[dict]:
    """describe() for every watchlist symbol."""
    out = []
    for w in (c or get_config()).get("watchlist", []):
        try:
            out.append(describe(w["symbol"], ts, c))
        except Exception:
            continue
    return out


def headline(c: dict | None = None, ts: float | None = None) -> str:
    """One line for /status: the standard (FX) flat / no-entry times, then any symbol that differs today."""
    if not cfg(c).get("enabled", True):
        return "End-of-day flat: off"
    rows = [r for r in schedule(c, ts) if r.get("enabled")]
    if not rows:
        return "End-of-day flat: off"
    ref = next((r for r in rows if r["symbol"] == "EURUSD=X"), rows[0])
    def hm(r, k, z):
        return r[k][z][11:]
    line = (f"End of day: no new entries from {hm(ref, 'no_entry', 'vilnius')} Vilnius ({hm(ref, 'no_entry', 'ny')} NY), "
            f"flat at {hm(ref, 'flat', 'vilnius')} ({hm(ref, 'flat', 'ny')} NY)")
    odd = [r for r in rows if r["flat"]["ts"] != ref["flat"]["ts"]]
    if odd:
        line += "; earlier today: " + ", ".join(f"{r['name']} {hm(r, 'flat', 'vilnius')}" for r in odd)
    return line
