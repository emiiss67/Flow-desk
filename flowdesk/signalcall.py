"""/signal and the desk's "Best strategy" panel: for one symbol (or every watchlist symbol) rank the strategies that are
allowed to trade, and say whether the bot would BUY, SELL or stand aside right now - with the SAME rules as live trading:
finished candles only (data.closed_bars), the learned blocks / regime (learning.allow), the quality gate and the
fill re-anchor (quality.fill_check), the broker's own limits (can_open) and the win-rate risk sizing.
Every number comes from the learned rules file (held-out, after costs) or from the live engine - nothing is invented."""
from __future__ import annotations

import re
import time

from . import instruments, learning, quality, regime, sizing, strategies as S
from .config import get_config
from .data import closed_bars, get_provider

MIN_RANK_N = 10            # a held-out sample below this is ranked after every proper sample and flagged "low sample"
_TTL = 60
_cache: dict = {}


def resolve(q: str) -> str | None:
    """'EURUSD', 'eur/usd', 'NAS100', 'Gold', 'nasdaq' -> ticker; None if nothing matches."""
    s = (q or "").strip()
    if not s:
        return None
    flat = re.sub(r"[\s/_-]+", "", s)
    for cand in (s, flat):
        try:
            t = instruments.normalize(cand)
        except ValueError:
            continue
        if t in instruments.BY_SYMBOL or t in watch_symbols():
            return t
    hits = instruments.search(s)
    if hits:
        return hits[0]["symbol"]
    return None


def watch_symbols(cfg: dict | None = None) -> list[str]:
    return [instruments.normalize(w["symbol"]) for w in (cfg or get_config()).get("watchlist", [])]


def _tf_of(sym: str, cfg: dict) -> str:
    for w in cfg.get("watchlist", []):
        if instruments.normalize(w["symbol"]) == sym:
            return w.get("tf", "15m")
    return "15m"


def universe(rules: dict, sym: str) -> list[dict]:
    """Enabled (or regime-switched-on), not paused, not blocked on this symbol - ranked by held-out expectancy on THIS symbol."""
    blocked = set(((rules.get("symbols") or {}).get(sym) or {}).get("blocked", []))
    reg = regime.current(rules)
    out = []
    for name, st in (rules.get("strategies") or {}).items():
        if name in blocked:
            continue
        if reg.get(name, {}).get("state") == "paused":
            continue
        on = bool(st.get("enabled")) or regime.switched_on(rules, name)
        if not on:
            continue
        ho = (((rules.get("symbols") or {}).get(sym) or {}).get("heldout") or {}).get(name)
        basis = f"held-out on {instruments.display(sym)}"
        if not ho or not ho.get("n"):
            v = ((st.get("stats") or {}).get("val")) or {}
            ho = {"n": v.get("n") or 0, "win_rate": v.get("win_rate"), "exp_r": v.get("exp_r")} if v.get("n") else {"n": 0, "win_rate": None, "exp_r": None}
            basis = "validation, all symbols" if ho["n"] else "no history"
        n = int(ho.get("n") or 0)
        tier = 2 if basis != f"held-out on {instruments.display(sym)}" else (1 if n < MIN_RANK_N else 0)
        out.append({"tier": tier, "edge": tier == 0 and (ho.get("exp_r") or 0) > 0, "strategy": name, "name": learning.NAMES.get(name, name), "n": n, "win_rate": ho.get("win_rate"),
                    "exp_r": ho.get("exp_r"), "low_sample": n < MIN_RANK_N, "basis": basis,
                    "regime": reg.get(name, {}).get("state") if name in reg else None})
    # tier 0: >= MIN_RANK_N held-out trades on THIS symbol; tier 1: fewer (anecdotal); tier 2: no held-out trade on this symbol,
    # only the strategy's all-symbol validation record. Within a tier: held-out expectancy (R per trade, after costs), then sample size.
    out.sort(key=lambda z: (-z["tier"], z["exp_r"] if z["exp_r"] is not None else -9, z["n"]), reverse=True)
    for i, z in enumerate(out):
        z["rank"] = i + 1
    return out


def _live_regime(R: list[dict]) -> dict:
    r = R[-1]
    tr = S.trend_of(r.get("adx1h"))
    return {"trend": tr, "session": S.session(r["hour"]), "volatility": S.features(R, len(R) - 1, "LONG")["atr_regime"]}


def size_preview(broker, fx, sym: str, side: str, entry: float, sl: float, risk_pct: float) -> dict:
    """What the broker would do at the current balance (same caps and sizing as PaperBroker.open)."""
    eq = broker.equity()
    rp, notes = float(risk_pct), []
    if broker.max_open_risk_pct:
        room = eq * broker.max_open_risk_pct / 100 - broker.open_risk_usd()
        if room < eq * 0.005:
            return {"ok": False, "why": f"open-risk cap ({broker.max_open_risk_pct:g}% of equity) reached"}
        if eq * rp / 100 > room:
            rp = 100 * room / eq
            notes.append(f"cut to {rp:.1f}% by the open-risk cap")
    if broker.max_side_risk_pct:
        room = eq * broker.max_side_risk_pct / 100 - broker.side_risk_usd(side)
        if room < eq * 0.005:
            return {"ok": False, "why": f"{'buy' if side == 'LONG' else 'sell'} trades already risk {broker.max_side_risk_pct:g}% of the balance"}
        if eq * rp / 100 > room:
            rp = 100 * room / eq
            notes.append(f"cut to {rp:.1f}% by the same-direction cap")
    meta = instruments.info(sym)
    pv = float(meta["point_value"])
    m = fx.mult(sym, entry, broker.ccy)
    if not m:
        return {"ok": False, "why": f"no FX rate to convert {sym} into {broker.ccy}"}
    entry = broker.fill_price(sym, side, entry, opening=True)      # what the paper broker would actually fill (spread + slippage)
    if (side == "LONG" and sl >= entry) or (side == "SHORT" and sl <= entry):
        return {"ok": False, "why": "stop is on the wrong side of the expected fill"}
    q = broker.position_size(eq, rp, entry, sl, pv, m, broker.max_leverage, broker.qty_step, broker.min_qty)
    if q <= 0:
        return {"ok": False, "why": "size rounds to zero"}
    from . import stake
    risk_amt = abs(entry - sl) * q * pv * m
    ev = stake.entry_values(sym, q, entry, pv, m, eq)
    sv, unit = stake.size_unit(sym, q)
    return {"ok": True, "risk_pct": round(100 * risk_amt / eq, 2) if eq else rp, "risk_amount": round(risk_amt, 2), "qty": q,
            "size_text": stake.fmt_size(sv, unit), "notional": ev["notional_eur"], "leverage": ev["leverage"],
            "equity": round(eq, 2), "ccy": broker.ccy, "notes": notes}


def _plan(res: dict, sym: str, broker, fx) -> dict:
    lv = res["levels"]
    side = res["decision"]
    sgn = 1 if side == "LONG" else -1
    risk = abs(lv["entry"] - lv["sl"])
    return {"side": side, "action": "BUY" if side == "LONG" else "SELL", "entry": lv["entry"], "sl": lv["sl"], "tp1": lv["tp1"],
            "tp2": lv["tp2"], "rr1": round((lv["tp1"] - lv["entry"]) * sgn / risk, 2) if risk else None,
            "rr2": round((lv["tp2"] - lv["entry"]) * sgn / risk, 2) if risk else None}


def _reason(c: dict) -> str:
    r = c["res"]
    txt = [x["text"] for x in (r.get("reasons") or []) if x.get("text")][:2]
    if c["stream"] in (learning.CORE,) or c["stream"] in learning.SETUP_KEYS.values():
        base = "; ".join(txt)
        if r.get("setup"):
            base = f"{r['setup']} setup" + (f": {base}" if base else "")
        return base or "confluence of structure, liquidity and order flow lines up"
    return S.STRATEGIES[c["stream"]]["desc"]


def evaluate(sym: str, broker, journal, fx, cfg: dict | None = None, provider=None, rules: dict | None = None, tf: str | None = None) -> dict:
    cfg = cfg or get_config()
    provider = provider or get_provider()
    rules = rules or learning.load_rules()
    tf = tf or _tf_of(sym, cfg)
    from .strategy import check
    meta = instruments.info(sym)
    out = {"symbol": sym, "name": instruments.display(sym), "category": meta.get("category"), "tf": tf, "paper": True,
           "generated": int(time.time()), "watchlist": sym in watch_symbols(cfg)}
    r = check(sym, tf, with_chart=False, winrate="off", closed_only=True)
    if not r.get("ok"):
        out.update(ok=False, call="NO TRADE", waiting="price data is unavailable right now", strategies=[])
        return out
    try:
        R = S.rows(S.indicators(closed_bars(provider.candles(sym, tf), sym, tf)))
    except Exception:
        R = None
    uni = universe(rules, sym)
    names = {u["strategy"] for u in uni}
    out.update(ok=True, price=r.get("live_price") or r["price"], last_closed=r["last_bar"], source=r.get("source"),
               regime=_live_regime(R) if R else None, strategies=uni, blackout=r.get("blackout"),
               scores=r.get("scores"), confluence=r.get("confluence"))
    cands: list[dict] = []
    if r["decision"] in ("LONG", "SHORT"):
        setup = r.get("setup")
        stream = learning.SETUP_KEYS.get(setup) if setup else learning.CORE
        feats = S.features(R, len(R) - 1, r["decision"], None, r["confluence"]) if R else {}
        cands.append({"stream": stream, "setup": setup, "feats": feats, "score": r["confluence"], "res": dict(r)})
    if R and not r.get("blackout"):
        for name in S.STRATEGIES:
            if name not in names:
                continue
            st = (rules.get("strategies") or {}).get(name) or {}
            sg = S.signal(name, R, len(R) - 1, st.get("params"))
            if not sg:
                continue
            from .strategy import decimals
            dp = decimals(sg["entry"])
            lv = {k: round(sg[k], dp) for k in ("entry", "sl", "tp1", "tp2")}
            lv["rr2"] = round(sg["rr"], 2)
            label = learning.NAMES[name]
            res = {"symbol": sym, "tf": tf, "decision": sg["side"], "confluence": None, "price": r["price"], "levels": lv,
                   "live_price": r.get("live_price"), "atr": sg["atr"], "setup": label,
                   "reasons": [{"text": S.STRATEGIES[name]["desc"], "tag": label}]}
            cands.append({"stream": name, "setup": label, "feats": S.features(R, len(R) - 1, sg["side"], sg["sl_atr"]), "score": None, "res": res})
    by = {u["strategy"]: u for u in uni}
    live = {}
    for c in cands:
        st = c["stream"]
        res = c["res"]
        res["levels"] = dict(res["levels"])
        item = {"strategy": st, "side": res["decision"], "reason": _reason(c)}
        if st not in by:
            item.update(state="blocked", why=f"{learning.NAMES.get(st, st)} is not allowed on {out['name']} right now")
        else:
            ok, why = learning.allow(rules, st, sym, dict(c["feats"]), res.get("confluence"))
            if ok:
                ok, why = quality.fill_check(res, sym, st, c["feats"], cfg)
            if ok:
                ok, why = broker.can_open(sym, c["setup"], res["decision"])
            wr = None
            if ok and (cfg.get("scanner", {}) or {}).get("require_killzone"):
                from .ict import killzone
                if not killzone():
                    ok, why = False, "outside killzone"
            if ok:
                try:
                    if st == learning.CORE or st in learning.SETUP_KEYS.values():
                        from . import backtest
                        wr = backtest.winrate(sym, tf, res["decision"], res["confluence"], mode="cached", setup=c["setup"])
                    else:
                        wr = learning.stats_for(rules, st, sym)
                except Exception:
                    wr = None
                sz = sizing.choose(wr, cfg)
                if sz["skip"]:
                    ok, why = False, sz["reason"]
            if ok:
                prev = size_preview(broker, fx, sym, res["decision"], res["levels"]["entry"], res["levels"]["sl"], sz["risk_pct"])
                if not prev["ok"]:
                    ok, why = False, prev["why"]
            if ok:
                item.update(state="ready", plan=_plan(res, sym, broker, fx), risk_pct=sz["risk_pct"], risk_reason=sz["reason"], size=prev)
            else:
                item.update(state="blocked", why=why)
        live[st] = item
    ready = [live[u["strategy"]] for u in uni if live.get(u["strategy"], {}).get("state") == "ready"]
    for u in uni:
        it = live.get(u["strategy"])
        u["state"] = it["state"] if it else "waiting"
        if it and it["state"] == "blocked":
            u["why"] = it["why"]
        if not it:
            u["waiting"] = _waiting(u["strategy"], r, rules, cfg)
    out["best"] = uni[0] if uni else None
    if ready:
        pick = ready[0]
        u = by[pick["strategy"]]
        out.update(call="BUY" if pick["side"] == "LONG" else "SELL", strategy=u, **{k: pick[k] for k in ("plan", "risk_pct", "risk_reason", "size", "reason")})
        out["runner_ups"] = [_ru(z, live) for z in uni if z["strategy"] != pick["strategy"]][:4]
        if uni and uni[0]["strategy"] != pick["strategy"]:
            out["note"] = f"{uni[0]['name']} ranks first here but has no signal; {u['name']} has one."
    else:
        out["call"] = "NO TRADE"
        blockedd = [(live[z["strategy"]], z) for z in uni if live.get(z["strategy"], {}).get("state") == "blocked"]
        if blockedd:
            it, z = blockedd[0]
            out["waiting"] = f"{z['name']} signalled {'a buy' if it['side'] == 'LONG' else 'a sell'} but the bot skips it: {it['why']}"
        elif r.get("blackout"):
            b = r["blackout"]
            out["waiting"] = f"a high-impact {b['ccy']} event ('{b['title']}') is too close - waiting until it has passed"
        elif uni:
            out["waiting"] = f"{uni[0]['name']} is " + (uni[0].get("waiting") or "waiting for a signal on a finished candle")
        else:
            out["waiting"] = "no strategy is allowed to trade this symbol right now"
        out["runner_ups"] = [_ru(z, live) for z in uni[1:5]]
    return out


def _ru(z: dict, live: dict) -> dict:
    it = live.get(z["strategy"])
    return {"strategy": z["strategy"], "name": z["name"], "state": z.get("state"), "exp_r": z["exp_r"], "win_rate": z["win_rate"], "n": z["n"],
            "low_sample": z["low_sample"], "basis": z["basis"], "edge": z["edge"],
            "action": ("BUY" if it["side"] == "LONG" else "SELL") if it else None, "note": z.get("why") or z.get("waiting")}


def _waiting(name: str, r: dict, rules: dict, cfg: dict) -> str:
    if name == learning.CORE:
        ms = float(((rules.get("strategies") or {}).get(name) or {}).get("params", {}).get("min_score", cfg.get("strategy", {}).get("min_score", 55)))
        mm = float(cfg.get("strategy", {}).get("min_margin", 15))
        sc = r.get("scores") or {}
        return (f"waiting for confluence of at least {ms:g} with a {mm:g}-point lead over the other side (now buy {sc.get('long', '?')} / sell {sc.get('short', '?')})")
    if name in learning.SETUP_KEYS.values():
        return f"waiting for a {learning.NAMES[name]} pattern on a finished candle (none now)"
    if name in S.STRATEGIES:
        return "waiting for its entry pattern on a finished candle - " + S.STRATEGIES[name]["desc"]
    return "waiting for a valid signal on a finished candle"


def get(sym: str, broker, journal, fx, cfg=None, provider=None, force: bool = False) -> dict:
    k = sym
    hit = _cache.get(k)
    if hit and not force and time.time() - hit[0] < _TTL:
        return hit[1]
    d = evaluate(sym, broker, journal, fx, cfg, provider)
    _cache[k] = (time.time(), d)
    return d


def top(broker, journal, fx, cfg=None, provider=None, limit: int = 5) -> dict:
    """Every watchlist symbol, best actionable setups first."""
    cfg = cfg or get_config()
    provider = provider or get_provider()
    syms = watch_symbols(cfg)
    from concurrent.futures import ThreadPoolExecutor

    def warm(s):
        try:
            provider.candles(s, _tf_of(s, cfg))
        except Exception:
            pass
    with ThreadPoolExecutor(max_workers=6) as ex:
        list(ex.map(warm, syms))
    res = []
    for s in syms:
        try:
            res.append(get(s, broker, journal, fx, cfg, provider))
        except Exception as e:
            res.append({"symbol": s, "name": instruments.display(s), "ok": False, "call": "NO TRADE", "waiting": f"error: {type(e).__name__}", "strategies": []})

    def key(d):
        st = d.get("strategy") or {}
        return (d.get("call") in ("BUY", "SELL"), st.get("exp_r") if st.get("exp_r") is not None else -9, st.get("n", 0))
    res.sort(key=key, reverse=True)
    act = [d for d in res if d.get("call") in ("BUY", "SELL")]
    near = [d for d in res if d.get("call") == "NO TRADE" and d.get("waiting", "").find("skips it") >= 0]
    return {"ok": True, "generated": int(time.time()), "actionable": act[:limit], "n_actionable": len(act), "near": near[:3],
            "n_symbols": len(res), "all": [{"symbol": d["symbol"], "name": d.get("name"), "call": d.get("call"),
                                             "strategy": (d.get("strategy") or {}).get("name") if d.get("strategy") else None} for d in res]}


# ---------------- Telegram text ----------------
def _stat(z: dict | None) -> str:
    if not z or not z.get("n"):
        return "no history yet"
    s = f"{z['win_rate']:.0f}% win · {z['exp_r']:+.2f}R/trade · n={z['n']}"
    return s + (" (low sample)" if z.get("low_sample") else "")


def fmt_one(d: dict, ccy: str = "EUR") -> str:
    from .currency import fmt_money
    from .strategy import fmt
    from .telegram import esc
    if not d.get("ok"):
        return f"<b>{esc(d['name'])}</b>: {esc(d.get('waiting', 'no data'))}"
    L = [f"📡 <b>{esc(d['name'])}</b> · {esc(d['tf'])} · paper"]
    rg = d.get("regime")
    if rg:
        L[0] += f" · {rg['trend']}, {rg['session']}, {rg['volatility']} volatility"
    L.append(f"Price {fmt(d['price'])} (last finished candle {time.strftime('%H:%M', time.localtime(d['last_closed']))})")
    best = d.get("best")
    if best:
        L.append(f"🏆 {'Best strategy here' if best.get('edge') else 'Best available here (no proven edge on this symbol)'}: <b>{esc(best['name'])}</b> - {best['basis']}: {_stat(best)}")
    else:
        L.append("No strategy is allowed to trade this symbol right now.")
    if d["call"] in ("BUY", "SELL"):
        p, st, sz = d["plan"], d["strategy"], d["size"]
        icon = "🟢" if d["call"] == "BUY" else "🔴"
        L.append("")
        L.append(f"{icon} <b>{d['call']}</b> via {esc(st['name'])} ({_stat(st)})")
        L.append(f"Entry {fmt(p['entry'])} · Stop {fmt(p['sl'])} · Target 1 {fmt(p['tp1'])} ({p['rr1']:g}R) · Target 2 {fmt(p['tp2'])} ({p['rr2']:g}R)")
        L.append(f"Risk {sz['risk_pct']:g}% = {fmt_money(sz['risk_amount'], ccy, False)} of {fmt_money(sz['equity'], ccy, False)} → size {esc(sz['size_text'])}"
                 + (f" ({esc('; '.join(sz['notes']))})" if sz["notes"] else ""))
        L.append(f"Why: {esc(d['reason'][:220])}")
        if d.get("note"):
            L.append("ℹ️ " + esc(d["note"]))
    else:
        L.append("")
        L.append("⚪ <b>NO TRADE</b> - " + esc(d.get("waiting", "")))
    ru = d.get("runner_ups") or []
    if ru:
        L.append("")
        L.append("Runner-ups:")
        for z in ru[:3]:
            tail = (z["action"] + " signal, skipped" if z.get("action") else "no signal now")
            L.append(f"• {esc(z['name'])} - {_stat(z)}{' (all-symbol validation)' if z.get('basis') == 'validation, all symbols' else ''} · {esc(tail)}")
    if d.get("blackout"):
        L.append("⚠️ High-impact news window")
    L.append("<i>Same rules as the live bot (finished candles, costs included). Paper trading only.</i>")
    return "\n".join(L)


def fmt_top(t: dict, ccy: str = "EUR") -> str:
    from .strategy import fmt
    from .telegram import esc
    L = ["📡 <b>Top setups now</b> (finished candles · paper)"]
    if not t["actionable"]:
        L.append("None of the " + str(t["n_symbols"]) + " watched symbols has a tradeable setup right now.")
    for d in t["actionable"]:
        p, st = d["plan"], d["strategy"]
        icon = "🟢" if d["call"] == "BUY" else "🔴"
        L.append(f"{icon} <b>{esc(d['name'])} {d['call']}</b> · {esc(st['name'])} ({_stat(st)})\n"
                 f"   Entry {fmt(p['entry'])} · SL {fmt(p['sl'])} · TP1 {fmt(p['tp1'])} · {p['rr1']:g}R · risk {d['risk_pct']:g}%")
    if t.get("near"):
        L.append("\nSignalled but skipped by the bot:")
        for d in t["near"]:
            L.append(f"• {esc(d['name'])}: {esc(d['waiting'][:140])}")
    L.append("\nUse /signal SYMBOL (e.g. /signal EURUSD) for the full plan on one symbol.")
    return "\n".join(L)
