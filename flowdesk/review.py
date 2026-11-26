"""Daily mistakes review (owner request 2026-11-26): right after the end-of-day flat, look at every trade that closed
since the last review, name what went wrong, and make the bot STRICTER where the same thing keeps happening.

Per losing trade (R < 0) the review assigns mistake tags from what the journal actually recorded - never a guess:
  news_spike           a high-impact event for the pair's currencies fell inside the trade's life
  counter_trend        entered against the 1h EMA trend (entry feature htf_align = against)
  chased_entry         filled more than `chase_r` R beyond the signal price (net of the half-spread)
  cost_too_high        round-trip spread + slippage was >= `cost_r` of the risk
  low_quality_score    confluence score band below `low_score`
  bad_session          the entry session / killzone has lost live (>= `session_min_n` trades averaging <= `session_exp` R)
  stopped_then_reversed stopped out, then price reached TP1 within `reversal_bars` bars
  tight_stop / quiet_market   entry features: stop < 0.8 ATR / ATR regime low
  gave_back_winner     TP1 was hit but the trade finished at <= 0R
  instant_adverse      stopped within 2 bars of entry
  eod_forced           closed by the end-of-day flat while losing (informational: time, not a mistake in the setup)
  clean_stop           none of the above: the plan was fine and price simply went against it
Winners are summarised too. Then the learning step (`learn`), always stricter, never looser, and all of it expires:
  * a strategy x symbol pause when the same mistake type cost >= `pause_repeat_n` losses in `window_days` (3 days, 7 if it
    was paused before in the window), or `streak_n` losses in a row, or the pair is losing live (n >= `combo_n`, avg <=
    `combo_exp` R, win rate <= `combo_wr`%);
  * a whole-strategy pause when it is losing live (n >= `strat_n`, avg <= `strat_exp` R);
  * a feature block (e.g. counter-trend entries, a session, quiet markets) for a strategy after `bucket_n` losses of that
    kind in the window while that bucket averages below 0R;
  * a higher minimum confluence score for the core strategy when low-score trades keep failing (+2 per loss, max +10).
The state lives in kv `review_state`; guard.check() reads it for every entry (the base gates are never relaxed)."""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from . import instruments
from .config import ROOT, get_config

log = logging.getLogger("flowdesk.review")
VILNIUS = ZoneInfo("Europe/Vilnius")

DEFAULTS = {"enabled": True, "delay_minutes": 3, "window_days": 14, "chase_r": 0.10, "cost_r": 0.12, "low_score": 60,
            "session_min_n": 4, "session_exp": -0.25, "reversal_bars": 8, "pause_repeat_n": 2, "pause_days": 3,
            "pause_days_repeat": 7, "streak_n": 3, "streak_days": 2, "combo_n": 4, "combo_exp": -0.25, "combo_wr": 25,
            "combo_days": 5, "strat_n": 8, "strat_exp": -0.25, "strat_days": 3, "bucket_n": 3, "bucket_days": 7,
            "score_bump_per_loss": 2, "score_bump_max": 10, "score_bump_days": 7}
PRIORITY = ["news_spike", "counter_trend", "chased_entry", "cost_too_high", "low_quality_score", "bad_session",
            "stopped_then_reversed", "tight_stop", "quiet_market", "gave_back_winner", "instant_adverse", "eod_forced"]
LABEL = {"news_spike": "news spike", "counter_trend": "against the 1h trend", "chased_entry": "chased the entry",
         "cost_too_high": "costs too high for the stop", "low_quality_score": "low confluence score",
         "bad_session": "bad session for this strategy", "stopped_then_reversed": "stopped out, then price reversed to target",
         "tight_stop": "stop too tight", "quiet_market": "quiet market", "gave_back_winner": "gave back a winner after TP1",
         "instant_adverse": "stopped almost immediately", "eod_forced": "closed by the end-of-day flat while losing",
         "clean_stop": "clean stop-out (plan was fine, price went against it)"}
# mistake -> the entry-feature bucket to block when it keeps repeating (bad_session fills in the actual session)
FEATURE_OF = {"counter_trend": ("htf_align", "against"), "quiet_market": ("atr_regime", "low"), "tight_stop": ("sl_atr", "tight")}
STATE_KEY = "review_state"


def cfg(c: dict | None = None) -> dict:
    g = dict(DEFAULTS)
    g.update((((c or get_config()).get("eod") or {}).get("review")) or {})
    return g


def _clean_since(c=None) -> int:
    from . import guard
    return int(guard.cfg(c).get("clean_since") or 0)


# ---------------- state (read by guard.check) ----------------
def empty_state() -> dict:
    return {"updated": 0, "pauses": [], "blocks": [], "min_score": {}, "pause_log": []}


def load_state(journal) -> dict:
    s = journal.get(STATE_KEY) if journal is not None else None
    return {**empty_state(), **(s or {})}


def blocked(journal, strategy: str, symbol: str, feats: dict | None = None, score: float | None = None,
            ts: float | None = None) -> tuple[bool, str]:
    """(True, why) if the daily review has paused / blocked this entry. Expired entries are ignored."""
    if journal is None:
        return False, ""
    st = load_state(journal)
    ts = time.time() if ts is None else ts
    from .learning import NAMES
    label, disp = NAMES.get(strategy, strategy), instruments.display(symbol)
    for p in st["pauses"]:
        if p["until"] > ts and p["strategy"] == strategy and p["symbol"] in ("*", symbol):
            where = "everywhere" if p["symbol"] == "*" else f"on {disp}"
            return True, f"daily review: {label} is paused {where} until {_vil(p['until'])} ({p['why']})"
    f = feats or {}
    for b in st["blocks"]:
        if b["until"] > ts and b["strategy"] == strategy and str(f.get(b["feature"])) == str(b["bucket"]):
            return True, f"daily review: {label} blocked for {b['label']} until {_vil(b['until'])} ({b['why']})"
    ms = (st["min_score"] or {}).get(strategy)
    if ms and ms["until"] > ts and score is not None and score < ms["min"]:
        return True, f"daily review: confluence {score:.0f} is below the raised minimum {ms['min']:g} ({ms['why']})"
    return False, ""


def _vil(ts: int) -> str:
    return datetime.fromtimestamp(ts, VILNIUS).strftime("%d %b %H:%M")


# ---------------- classification ----------------
def _rows(journal, start: int, end: int) -> list[dict]:
    out = journal.q("SELECT * FROM trades WHERE status='closed' AND closed_ts>? AND closed_ts<=? ORDER BY closed_ts", (start, end))
    for t in out:
        try:
            t["f"] = json.loads(t["features"]) if t.get("features") else {}
        except ValueError:
            t["f"] = {}
    return out


def _stream(t: dict) -> str:
    from . import guard
    return guard.stream_of(t)


def _score_band(f: dict) -> int | None:
    s = str((f or {}).get("score") or "")
    return int(s[:-1]) if s.endswith("s") and s[:-1].isdigit() else None


def classify(t: dict, rc: dict, ctx: dict) -> dict:
    """Tags + primary mistake of one closed trade. ctx: {events, bars(symbol, tf) -> DataFrame|None, cost_bps(symbol),
    session_stats: {bucket: [r...]}, signal_price}."""
    f = t.get("f") or {}
    sgn = 1 if t["side"] == "LONG" else -1
    r = float(t.get("r_multiple") or 0)
    tf_sec = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400}.get(t.get("tf") or "15m", 900)
    unit = abs(float(t["entry"]) - float(t.get("sl_initial") or t["sl"])) or 1e-12
    tags: list[str] = []
    notes: dict = {}
    reason = t.get("exit_reason") or ""
    loss = r < 0 or float(t.get("pnl_usd") or 0) < 0
    if reason == "EOD close" and loss:
        tags.append("eod_forced")
    if loss:
        ccys = set(instruments.info(t["symbol"])["ccy"])
        for e in ctx.get("events") or []:
            if e.get("impact") == "High" and e.get("ccy") in ccys and t["opened_ts"] - 600 <= e["ts"] <= (t["closed_ts"] or 0) + 300:
                tags.append("news_spike"); notes["event"] = f"{e.get('ccy')} {e.get('title')}"; break
        if f.get("htf_align") == "against":
            tags.append("counter_trend")
        sp = ctx.get("signal_price", {}).get(t["id"])
        cb = ctx["cost_bps"](t["symbol"]) if ctx.get("cost_bps") else 0.0
        if sp:
            drift = (float(t["entry"]) - sp) * sgn / unit - float(t["entry"]) * cb / 1e4 / unit
            notes["entry_drift_r"] = round(drift, 3)
            if drift > rc["chase_r"]:
                tags.append("chased_entry")
        cost_r = 2 * cb / 1e4 * float(t["entry"]) / unit
        notes["cost_r"] = round(cost_r, 3)
        if cost_r >= rc["cost_r"]:
            tags.append("cost_too_high")
        band = _score_band(f)
        if band is not None and band < rc["low_score"]:
            tags.append("low_quality_score")
        for key in ("session", "killzone"):
            v = f.get(key)
            rs = (ctx.get("session_stats") or {}).get((_stream(t), key, v)) or []
            if v not in (None, "none") and len(rs) >= rc["session_min_n"] and sum(rs) / len(rs) <= rc["session_exp"]:
                tags.append("bad_session"); notes["session"] = f"{key}={v} ({sum(rs) / len(rs):+.2f}R over {len(rs)})"; break
        if reason == "stop loss" and not t.get("tp1_hit"):
            try:
                df = ctx["bars"](t["symbol"], t.get("tf") or "15m") if ctx.get("bars") else None
                if df is not None and len(df):
                    after = df[df.index.map(lambda x: x.timestamp()) >= (t["closed_ts"] or 0)].iloc[: int(rc["reversal_bars"])]
                    if len(after) and ((after["high"].max() >= t["tp1"]) if sgn > 0 else (after["low"].min() <= t["tp1"])):
                        tags.append("stopped_then_reversed")
            except Exception as e:                                       # no data -> no claim
                log.debug("reversal check %s: %s", t["id"], e)
        if f.get("sl_atr") == "tight":
            tags.append("tight_stop")
        if f.get("atr_regime") == "low":
            tags.append("quiet_market")
        if t.get("tp1_hit") and r <= 0.0:
            tags.append("gave_back_winner")
        if reason == "stop loss" and (t["closed_ts"] or 0) - t["opened_ts"] <= 2 * tf_sec:
            tags.append("instant_adverse")
        if not tags:
            tags.append("clean_stop")
    tags = sorted(set(tags), key=lambda x: PRIORITY.index(x) if x in PRIORITY else 99)
    return {"id": t["id"], "symbol": t["symbol"], "name": instruments.display(t["symbol"]), "strategy": _stream(t),
            "side": t["side"], "r": round(r, 2), "pnl": round(float(t.get("pnl_usd") or 0), 2), "exit": reason,
            "opened": t["opened_ts"], "closed": t["closed_ts"], "loss": loss, "tags": tags,
            "primary": tags[0] if loss and tags else None, "notes": notes}


def _session_stats(journal, since: int) -> dict:
    """{(strategy, 'session'|'killzone', value): [r...]} over closed live trades since the fixes."""
    out: dict = {}
    for t in journal.q("SELECT * FROM trades WHERE status='closed' AND opened_ts>=?", (since,)):
        try:
            f = json.loads(t["features"]) if t.get("features") else {}
        except ValueError:
            f = {}
        for k in ("session", "killzone"):
            if f.get(k) is not None:
                out.setdefault((_stream(t), k, f[k]), []).append(float(t.get("r_multiple") or 0))
    return out


# ---------------- learning (stricter only) ----------------
def learn(journal, results: list[dict], rc: dict, now: int, c: dict | None = None) -> list[dict]:
    """Update review_state from the rolling window. Returns the list of actions taken (for the report)."""
    st = load_state(journal)
    since = max(_clean_since(c), now - int(rc["window_days"]) * 86400)
    st["pauses"] = [p for p in st["pauses"] if p["until"] > now]
    st["blocks"] = [b for b in st["blocks"] if b["until"] > now]
    st["min_score"] = {k: v for k, v in (st["min_score"] or {}).items() if v["until"] > now}
    st["pause_log"] = [x for x in st["pause_log"] if x["ts"] > now - 30 * 86400][-60:]
    clean = _clean_since(c)
    hist = [t for t in _rows(journal, since, now) if int(t["opened_ts"] or 0) >= clean]
    byid = {r["id"]: r for r in results}
    fresh = set(byid)                       # a rule only fires when today's trades add evidence (old losses never re-trigger it)
    cls: dict[int, dict] = dict(byid)
    actions: list[dict] = []

    def add_pause(strategy, symbol, days, why, kind):
        until = now + int(days * 86400)
        cur = next((p for p in st["pauses"] if p["strategy"] == strategy and p["symbol"] == symbol), None)
        if cur:
            if cur["until"] >= until:
                return
            cur.update(until=until, why=why)
        else:
            st["pauses"].append({"strategy": strategy, "symbol": symbol, "until": until, "why": why, "kind": kind, "set": now})
        st["pause_log"].append({"key": f"{strategy}|{symbol}", "ts": now})
        from .learning import NAMES
        where = "everywhere" if symbol == "*" else f"on {instruments.display(symbol)}"
        actions.append({"kind": "pause", "strategy": strategy, "symbol": symbol, "until": until,
                        "text": f"Paused {NAMES.get(strategy, strategy)} {where} for {days:g} days: {why}"})

    # live rolling stats per (strategy, symbol) and per strategy (clean trades only)
    combos: dict = {}
    strats: dict = {}
    for t in hist:
        s, r = _stream(t), float(t.get("r_multiple") or 0)
        combos.setdefault((s, t["symbol"]), []).append((t, r))
        strats.setdefault(s, []).append(r)
    for (s, sym), rows in combos.items():
        rs = [r for _, r in rows]
        # a) same mistake type repeating
        kinds: dict = {}
        for t, r in rows:
            c_ = cls.get(t["id"]) or (classify(t, rc, {}) if r < 0 else None)
            if c_ and c_.get("primary") and c_["primary"] not in ("clean_stop", "eod_forced"):
                kinds.setdefault(c_["primary"], []).append(t["id"])
        for k, ids in kinds.items():
            if len(ids) >= rc["pause_repeat_n"] and fresh & set(ids):
                again = any(x["key"] == f"{s}|{sym}" and x["ts"] > now - int(rc["window_days"]) * 86400 for x in st["pause_log"])
                add_pause(s, sym, rc["pause_days_repeat"] if again else rc["pause_days"],
                          f"{len(ids)} losses from the same mistake ({LABEL[k]}) in {rc['window_days']} days", "repeat_mistake")
                break
        # b) loss streak
        last = [r for r in rs[-int(rc["streak_n"]):]]
        if len(last) >= rc["streak_n"] and all(r < 0 for r in last) and fresh & {t["id"] for t, _ in rows[-int(rc["streak_n"]):]}:
            add_pause(s, sym, rc["streak_days"], f"{len(last)} losses in a row", "streak")
        # c) losing live on this pair
        wr = 100 * sum(1 for r in rs if r > 0) / len(rs)
        if len(rs) >= rc["combo_n"] and sum(rs) / len(rs) <= rc["combo_exp"] and wr <= rc["combo_wr"] and fresh & {t["id"] for t, _ in rows}:
            add_pause(s, sym, rc["combo_days"], f"losing live: {sum(rs) / len(rs):+.2f}R per trade, {wr:.0f}% wins over {len(rs)} trades", "combo_live")
    for s, rs in strats.items():
        if len(rs) >= rc["strat_n"] and sum(rs) / len(rs) <= rc["strat_exp"] and any(_stream(t) == s for t in hist if t["id"] in fresh):
            add_pause(s, "*", rc["strat_days"], f"losing live: {sum(rs) / len(rs):+.2f}R per trade over {len(rs)} trades", "strategy_live")

    # feature blocks: repeated mistake of one kind inside a strategy while that bucket is negative
    by_strat: dict = {}
    for t in hist:
        r = float(t.get("r_multiple") or 0)
        c_ = cls.get(t["id"]) or (classify(t, rc, {}) if r < 0 else None)
        by_strat.setdefault(_stream(t), []).append((t, r, c_))
    for s, rows in by_strat.items():
        for k, (feat, bucket) in {**FEATURE_OF, "bad_session": ("session", None)}.items():
            cand = [(t, r) for t, r, c_ in rows if c_ and k in (c_.get("tags") or []) and r < 0]
            if not any(t["id"] in fresh for t, _ in cand):
                continue
            if k == "bad_session":
                vals = {}
                for t, r in cand:
                    vals.setdefault((t["f"] or {}).get("session"), []).append(r)
                groups = [("session", v, rs) for v, rs in vals.items() if v]
            else:
                groups = [(feat, bucket, [r for _, r in cand])]
            for feat_, bucket_, rs in groups:
                if len(rs) < rc["bucket_n"]:
                    continue
                allb = [r for t, r, _ in rows if str((t["f"] or {}).get(feat_)) == str(bucket_)]
                if allb and sum(allb) / len(allb) < 0 and not any(b["strategy"] == s and b["feature"] == feat_ and str(b["bucket"]) == str(bucket_) for b in st["blocks"]):
                    from .learning import NAMES
                    lab = f"{feat_} = {bucket_}"
                    why = f"{len(rs)} losses of this kind in {rc['window_days']} days, bucket {sum(allb) / len(allb):+.2f}R over {len(allb)}"
                    st["blocks"].append({"strategy": s, "feature": feat_, "bucket": bucket_, "label": lab, "why": why,
                                         "until": now + int(rc["bucket_days"] * 86400), "set": now})
                    actions.append({"kind": "block", "strategy": s, "feature": feat_, "bucket": bucket_,
                                    "text": f"Blocked {NAMES.get(s, s)} for {lab} for {rc['bucket_days']:g} days: {why}"})

    # raise the minimum confluence score (core) when low-score trades keep losing
    low = [r for t, r, c_ in by_strat.get("core", []) if c_ and "low_quality_score" in (c_.get("tags") or []) and r < 0]
    if len(low) >= 2 and any(t["id"] in fresh and r < 0 and "low_quality_score" in ((c_ or {}).get("tags") or []) for t, r, c_ in by_strat.get("core", [])):
        from . import learning
        base = float((learning.load_rules().get("strategies", {}).get("core", {}).get("params") or {}).get("min_score", 55))
        bump = min(float(rc["score_bump_max"]), rc["score_bump_per_loss"] * len(low))
        cur = (st["min_score"] or {}).get("core")
        new_min = base + bump
        if not cur or new_min > cur["min"]:
            st["min_score"]["core"] = {"min": new_min, "until": now + int(rc["score_bump_days"] * 86400),
                                       "why": f"{len(low)} losing trades with a score under {rc['low_score']} in {rc['window_days']} days"}
            actions.append({"kind": "min_score", "strategy": "core", "text": f"Raised the minimum confluence score for the main engine to {new_min:g} "
                            f"for {rc['score_bump_days']:g} days: {len(low)} losing low-score trades"})
    st["updated"] = now
    journal.set(STATE_KEY, st)
    return actions


# ---------------- the daily run ----------------
def _ny_day(ts: int) -> str:
    return datetime.fromtimestamp(ts, ZoneInfo("America/New_York")).strftime("%Y-%m-%d")


def run(journal, broker=None, provider=None, now: int | None = None, events: list | None = None,
        c: dict | None = None, write_file: bool = True, learn_too: bool = True) -> dict:
    c = c or get_config()
    rc = cfg(c)
    now = int(now or time.time())
    from . import guard
    last_end = journal.get("review_last_end")
    start = int(last_end) if last_end else max(_clean_since(c), now - 36 * 3600)
    trades = _rows(journal, start, now)
    if events is None:
        try:
            from . import events as E
            events = E.calendar().get("events", [])
        except Exception:
            events = []
    sig = {}
    for t in trades:
        if t.get("signal_id"):
            r = journal.q("SELECT price FROM signals WHERE id=?", (t["signal_id"],))
            if r and r[0]["price"]:
                sig[t["id"]] = float(r[0]["price"])
    ctx = {"events": events, "signal_price": sig,
           "cost_bps": (broker.cost_bps if broker is not None else None),
           "bars": (provider.candles if provider is not None else None),
           "session_stats": _session_stats(journal, _clean_since(c))}
    results = [classify(t, rc, ctx) for t in trades]
    losers = [x for x in results if x["loss"]]
    mist: dict = {}
    for x in losers:
        for k in x["tags"]:
            m = mist.setdefault(k, {"n": 0, "r": 0.0, "ids": []})
            m["n"] += 1; m["r"] = round(m["r"] + x["r"], 2); m["ids"].append(x["id"])
    prim: dict = {}
    for x in losers:
        p = prim.setdefault(x["primary"], {"n": 0, "r": 0.0})
        p["n"] += 1; p["r"] = round(p["r"] + x["r"], 2)
    actions = learn(journal, results, rc, now, c) if learn_too and rc.get("enabled", True) else []
    day = _ny_day(now)
    wins = sum(1 for x in results if x["pnl"] > 0)
    summary = {"day": day, "generated": now, "window": [start, now], "n": len(results), "wins": wins, "losses": len(losers),
               "pnl": round(sum(x["pnl"] for x in results), 2), "total_r": round(sum(x["r"] for x in results), 2),
               "eod_closed": sum(1 for x in results if x["exit"] == "EOD close"), "trades": results,
               "mistakes": mist, "primary": prim, "actions": actions, "lessons": lessons(results, mist, prim)}
    journal.x("INSERT INTO daily_reviews(day,ts,window_start,window_end,n_trades,wins,losses,pnl,total_r,summary) "
              "VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(day) DO UPDATE SET ts=excluded.ts, window_start=MIN(window_start, excluded.window_start),"
              "window_end=excluded.window_end, n_trades=n_trades+excluded.n_trades, wins=wins+excluded.wins, losses=losses+excluded.losses,"
              "pnl=pnl+excluded.pnl, total_r=total_r+excluded.total_r, summary=excluded.summary",
              (day, now, start, now, len(results), wins, len(losers), summary["pnl"], summary["total_r"], json.dumps(summary)))
    journal.set("review_last_end", now)
    if write_file:
        try:
            summary["file"] = write_markdown(summary)
        except Exception as e:
            log.warning("review file not written: %s", type(e).__name__)
    return summary


def lessons(results: list[dict], mist: dict, prim: dict) -> list[str]:
    out = []
    if not results:
        return ["No trades closed in this window - nothing to review."]
    n_loss = sum(1 for x in results if x["loss"])
    out.append(f"{len(results)} trades closed: {len(results) - n_loss} winners/flat, {n_loss} losers.")
    for k, m in sorted(prim.items(), key=lambda kv: kv[1]["r"]):
        out.append(f"{LABEL.get(k, k)}: {m['n']} loss{'es' if m['n'] != 1 else ''} ({m['r']:+.2f}R) as the main cause.")
    return out


def md_name(day: str) -> Path:
    return ROOT / "research" / "daily_reviews" / f"{day}.md"


def write_markdown(s: dict) -> str:
    p = md_name(s["day"])
    p.parent.mkdir(parents=True, exist_ok=True)
    L = [f"# FlowDesk daily review {s['day']} (NY trading day)", "",
         f"Window {_vil(s['window'][0])} to {_vil(s['window'][1])} Vilnius. {s['n']} closed trades "
         f"({s['wins']} winners, {s['losses']} losers), P&L {s['pnl']:+.2f}, total {s['total_r']:+.2f}R, "
         f"{s['eod_closed']} closed by the end-of-day flat.", "", "## Trades", "",
         "| # | Pair | Strategy | Side | R | P&L | Exit | Mistakes |", "|---|---|---|---|---|---|---|---|"]
    for x in s["trades"]:
        tg = ", ".join(LABEL.get(k, k) for k in x["tags"]) if x["loss"] else "-"
        L.append(f"| {x['id']} | {x['name']} | {x['strategy']} | {x['side']} | {x['r']:+.2f} | {x['pnl']:+.2f} | {x['exit']} | {tg} |")
    L += ["", "## What went wrong", ""] + [f"- {t}" for t in s["lessons"]]
    L += ["", "## What the bot changed (stricter only, all expire)", ""] + ([f"- {a['text']}" for a in s["actions"]] or ["- Nothing new."])
    p.write_text("\n".join(L) + "\n")
    return str(p)


def latest(journal) -> dict | None:
    r = journal.q("SELECT summary FROM daily_reviews ORDER BY day DESC LIMIT 1")
    return json.loads(r[0]["summary"]) if r else None


def history(journal, n: int = 14) -> list[dict]:
    return journal.q("SELECT day, ts, n_trades, wins, losses, pnl, total_r FROM daily_reviews ORDER BY day DESC LIMIT ?", (n,))


def active_rules(journal, ts: float | None = None) -> dict:
    st = load_state(journal)
    ts = time.time() if ts is None else ts
    return {"pauses": [p for p in st["pauses"] if p["until"] > ts], "blocks": [b for b in st["blocks"] if b["until"] > ts],
            "min_score": {k: v for k, v in (st["min_score"] or {}).items() if v["until"] > ts}}


def fmt(s: dict | None) -> str:
    """Telegram (HTML) text for /review."""
    from .telegram import esc
    if not s:
        return "No daily review yet. The first one runs right after the end-of-day flat (23:45 Vilnius in winter)."
    out = [f"<b>Daily review {esc(s['day'])}</b> (paper)",
           f"{s['n']} trades closed · {s['wins']} won · {s['losses']} lost · P&amp;L {s['pnl']:+.2f} ({s['total_r']:+.2f}R)"
           + (f" · {s['eod_closed']} closed at end of day" if s.get("eod_closed") else "")]
    if s["primary"]:
        out.append("<b>Main causes of losses</b>")
        out += [f"• {esc(LABEL.get(k, k))}: {m['n']} ({m['r']:+.2f}R)" for k, m in sorted(s["primary"].items(), key=lambda kv: kv[1]["r"])]
    out.append("<b>Bot changes</b>")
    out += [f"• {esc(a['text'])}" for a in s["actions"][:8]] or ["• nothing new"]
    return "\n".join(out)
