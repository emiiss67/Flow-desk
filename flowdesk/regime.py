"""Regime check: which strategies work in the CURRENT market, judged on the most recent trading days only.

Walk-forward on the newest data (15m, the timeframe the bot trades):
  * window A ("pick")  = trading days -10 .. -5   -> choose what to test (whole strategy or one session / trend state / instrument)
  * window B ("check") = the newest 4 trading days -> out-of-sample: the choice must ALSO make money here
Every trade is after costs (spread + slippage; the replayed core/setup trades get the same cost estimate with a
1-ATR stop). Trend vs range per bar = 1-hour ADX(14) from completed hours only (>=25 trend, <20 range).

Switched-off strategies are turned ON for a scope only with a positive expectancy in BOTH windows and a minimum
sample in each; live strategies (core / HVN / KLAR) are PAUSED when both recent windows lose with enough trades.
The result lives in rules["regime"] (recomputed by the nightly learning loop), and is ignored once it is older
than MAX_AGE so a stale verdict can never keep a strategy on."""
from __future__ import annotations
import time
from datetime import datetime, timezone

from . import learning as L, strategies as S

CFG = {"days_pick": 6, "days_check": 4, "min_pick_n": 10, "min_check_n": 10, "min_pick_exp": 0.05,
       "min_check_exp": 0.05, "pause_min_n": 10, "max_scopes": 2}
MAX_AGE = 3 * 86400
LIVE = (L.CORE, "setup_hvn", "setup_klar")
SCOPE_KEYS = ("session", "trend", "symbol")
SCOPE_WORDS = {"session": {"asia": "Asian session (00-07 UTC)", "london": "London session (07-12 UTC)",
                           "newyork": "New York session (12-17 UTC)", "late": "late session (17-24 UTC)"},
               "trend": {"trend": "trending markets (ADX 25+)", "range": "ranging markets (ADX under 20)", "mixed": "markets between trend and range (ADX 20-25)"}}


def scope_text(sc: dict | None) -> str:
    if not sc:
        return "everywhere"
    if sc["feature"] == "symbol":
        return "on " + _disp(sc["bucket"])
    return "in " + SCOPE_WORDS.get(sc["feature"], {}).get(sc["bucket"], sc["bucket"])


def _disp(sym: str) -> str:
    from . import instruments
    return instruments.display(sym)


def _days(data: list[dict]) -> list[str]:
    ds = set()
    for x in data:
        for t in x["ts"][-1600:]:
            d = datetime.fromtimestamp(t, timezone.utc)
            if d.weekday() < 5:
                ds.add(d.date().isoformat())
    return sorted(ds)


def recent_trades(data: list[dict], rules: dict) -> dict[str, list[dict]]:
    """All strategies' trades in the data, after costs, tagged with their UTC trading day."""
    sc = L._cfg().get("strategy", {})
    mm = float(sc.get("min_margin", 15))
    out = {n: [] for n in rules.get("strategies", {})}
    for x in data:
        R = x["R"]
        ms = float(rules.get("strategies", {}).get(L.CORE, {}).get("params", {}).get("min_score", sc.get("min_score", 55)))
        for t in L.core_trades(x["sym"], x, ms, mm):
            k = x["idx"].get(t["t"])
            if k is None or t["strategy"] not in out:
                continue
            atr = float(R[k]["atr"] or 0)
            t["r"] = t["r"] - (L._cost_r(x["sym"], float(R[k]["close"]), atr) if atr > 0 else 0)
            t["win"] = t["r"] > 0
            out[t["strategy"]].append(t)
        for name in S.STRATEGIES:
            if name in out:
                out[name] += L.simulate_strategy(x["sym"], name, x, (rules["strategies"][name].get("params") or {}))
    for name, ts in out.items():
        live = name in LIVE
        keep = []
        for t in ts:
            f = t["f"]
            if live:   # what the live bot would actually have taken (learned blocks + per-symbol blocks)
                rr = {"strategies": {name: {"enabled": True, "params": {"min_score": 0}}}, "blocks": rules.get("blocks", []),
                      "symbols": rules.get("symbols", {})}
                if not L.allow(rr, name, f["symbol"], {k: v for k, v in f.items() if k != "symbol"})[0]:
                    continue
            t["day"] = datetime.fromtimestamp(t["t"], timezone.utc).date().isoformat()
            keep.append(t)
        out[name] = keep
    return out


def _match(t: dict, sc: dict | None) -> bool:
    return sc is None or str(t["f"].get(sc["feature"])) == str(sc["bucket"])


def evaluate(data: list[dict], rules: dict, now: float | None = None) -> dict:
    c = CFG
    days = _days(data)
    pick_days = set(days[-(c["days_pick"] + c["days_check"]):-c["days_check"]])
    check_days = set(days[-c["days_check"]:])
    trades = recent_trades(data, rules)
    res = {}
    for name, ts in trades.items():
        A = [t for t in ts if t["day"] in pick_days]
        B = [t for t in ts if t["day"] in check_days]
        sa, sb = L.summarize(A), L.summarize(B)
        long_on = bool(rules["strategies"][name].get("enabled"))
        breakdown = {}
        for fk in SCOPE_KEYS:
            for bk in sorted({str(t["f"].get(fk)) for t in A + B if t["f"].get(fk) is not None}):
                sc = {"feature": fk, "bucket": bk}
                breakdown[f"{fk}:{bk}"] = {"pick": L.summarize([t for t in A if _match(t, sc)]),
                                           "check": L.summarize([t for t in B if _match(t, sc)])}
        entry = {"name": L.NAMES.get(name, name), "long_term_on": long_on, "pick": sa, "check": sb, "scopes": [],
                 "breakdown": breakdown}
        if name in LIVE:
            if sb["n"] >= c["pause_min_n"] and (sb["exp_r"] or 0) < 0 and sa["n"] >= c["pause_min_n"] and (sa["exp_r"] or 0) < 0:
                entry["state"] = "paused"
                entry["reason"] = (f"Paused for now: lost in both recent windows ({sa['exp_r']:+.2f}R over {sa['n']} trades, then "
                                   f"{sb['exp_r']:+.2f}R over {sb['n']}) - turns back on when the recent results recover")
            else:
                entry["state"] = "on" if long_on else "off"
                entry["reason"] = (f"Recent check {_fmt(sb)} (before that {_fmt(sa)}) - no reason to pause" if long_on else
                                   "Off by the long-term learning")
            res[name] = entry
            continue
        # switched-off strategies: candidates chosen on window A only, then verified once on B
        cands = []
        if sa["n"] >= c["min_pick_n"] and (sa["exp_r"] or -9) > c["min_pick_exp"]:
            cands.append((sa["exp_r"], None))
        for k, v in breakdown.items():
            p = v["pick"]
            if p["n"] >= c["min_pick_n"] and (p["exp_r"] or -9) > c["min_pick_exp"]:
                fk, bk = k.split(":", 1)
                cands.append((p["exp_r"], {"feature": fk, "bucket": bk}))
        cands.sort(key=lambda z: -z[0])
        tested = []
        for _, sc in cands[:c["max_scopes"] + (1 if cands and cands[0][1] is None else 0)]:
            pa = L.summarize([t for t in A if _match(t, sc)])
            pb = L.summarize([t for t in B if _match(t, sc)])
            ok = pb["n"] >= c["min_check_n"] and (pb["exp_r"] or -9) > c["min_check_exp"]
            tested.append({"scope": sc, "pick": pa, "check": pb, "ok": ok})
            if ok:
                entry["scopes"].append({"scope": sc, "pick": pa, "check": pb, "text": scope_text(sc)})
            if ok and sc is None:
                break                                  # on everywhere: narrower scopes add nothing
        entry["tested"] = tested
        if entry["scopes"]:
            entry["state"] = "on"
            s0 = entry["scopes"][0]
            entry["reason"] = ("Trading " + " and ".join(s["text"] for s in entry["scopes"]) +
                               f": made money in the last {c['days_check']} trading days ({_fmt(s0['check'])}) after also making money "
                               f"the {c['days_pick']} days before ({_fmt(s0['pick'])}) - small sample, re-checked every night")
        else:
            entry["state"] = "off"
            if tested:
                t0 = tested[0]
                entry["reason"] = (f"Off: looked good {scope_text(t0['scope'])} before ({_fmt(t0['pick'])}) but not in the last "
                                   f"{c['days_check']} trading days ({_fmt(t0['check'])})" if t0["check"]["n"] >= c["min_check_n"] else
                                   f"Off: looked good {scope_text(t0['scope'])} ({_fmt(t0['pick'])}) but too few recent trades to confirm "
                                   f"({t0['check']['n']}, needs {c['min_check_n']})")
            else:
                entry["reason"] = f"Off: no money-making pattern in the recent window ({_fmt(sa)}, latest days {_fmt(sb)})"
        res[name] = entry
    return {"computed": int(now or time.time()), "pick_days": sorted(pick_days), "check_days": sorted(check_days),
            "timeframe": "15m", "costs": "after spread + slippage", "trend": "1h ADX(14): 25+ trend, under 20 range",
            "limits": dict(c), "strategies": res}


def _fmt(s: dict) -> str:
    if not s or not s.get("n"):
        return "no trades"
    return f"{s['win_rate']:.0f}% win, {s['exp_r']:+.2f}R/trade, n={s['n']}"


# ---------------- used by the live filter ----------------
def current(rules: dict, now: float | None = None) -> dict:
    rg = rules.get("regime") or {}
    if not rg or (now or time.time()) - int(rg.get("computed", 0)) > MAX_AGE:
        return {}
    return rg.get("strategies", {}) or {}


def switched_on(rules: dict, name: str) -> bool:
    return (current(rules).get(name) or {}).get("state") == "on" and not (rules.get("strategies", {}).get(name) or {}).get("enabled")


def check(rules: dict, name: str, feats: dict) -> tuple[bool, str]:
    """(allowed, why) from the regime verdict, for a candidate with entry features incl. symbol."""
    e = current(rules).get(name)
    if not e:
        return True, ""
    if e.get("state") == "paused":
        return False, "regime: " + e["reason"]
    if e.get("state") == "on" and e.get("scopes") and not (rules.get("strategies", {}).get(name) or {}).get("enabled"):
        if any(_match({"f": feats}, s["scope"]) for s in e["scopes"]):
            return True, ""
        return False, f"regime: {e['name']} is only on " + " / ".join(s["text"] for s in e["scopes"]) + " right now"
    return True, ""


def apply(new: dict, old: dict, data: list[dict], changes: list[dict] | None = None) -> dict:
    """Compute the regime verdict into `new` and log state flips as plain-English changes."""
    rg = evaluate(data, new)
    before = (old.get("regime") or {}).get("strategies", {}) or {}
    for name, e in rg["strategies"].items():
        was = (before.get(name) or {}).get("state")
        default = "on" if e.get("long_term_on") else "off"
        if changes is not None and e["state"] != (was or default):
            changes.append({"kind": "regime", "strategy": name, "state": e["state"], "text": f"{e['name']}: {e['reason']}"})
    # keep the stored file small: only buckets with trades in the check window
    for e in rg["strategies"].values():
        e["breakdown"] = {k: v for k, v in e.get("breakdown", {}).items() if v["check"]["n"] >= 3}
    new["regime"] = rg
    return rg


def refresh(journal=None) -> dict:
    """Recompute only the regime verdict on the newest data and save it as a new rules version."""
    import copy
    from . import instruments
    cfg = L.get_config()
    L._CFG["c"] = cfg
    old = L.load_rules()
    new = copy.deepcopy(old)
    data = [x for x in (L.load_symbol(instruments.normalize(w["symbol"]), w.get("tf", "15m")) for w in cfg.get("watchlist", [])) if x]
    if not data:
        raise RuntimeError("no market data")
    changes: list[dict] = []
    apply(new, old, data, changes)
    new["changes"] = changes or [{"kind": "regime", "text": "Regime re-checked: no strategy changed state."}]
    new["note"] = f"regime check: {len(changes)} change(s)"
    return L.save_rules(new)
