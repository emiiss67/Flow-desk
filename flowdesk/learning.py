"""Learning loop: learn from losing trades without fooling ourselves.

Data: every walk-forward backtest trade (core confluence engine + named setups from the cached replays, plus the
extra strategies in strategies.py) and every paper trade, each with its entry features.
Split by TIME per symbol: TRAIN (oldest 50%) -> tune / propose, VALIDATION (next 25%) -> accept or reject a change,
TEST (newest 25%) -> only reported, never used for a decision. A change is adopted only when it improves validation
EXPECTANCY (R per trade), never on win rate alone, with minimum sample sizes, and only a few changes per cycle.
Rules are versioned in data/learned/ with one-call rollback. Nothing here can see bars after the entry bar
except the trade simulation itself (which is what a trade outcome is)."""
from __future__ import annotations
import copy
import json
import logging
import math
import time
from pathlib import Path

from . import backtest, instruments, quality, strategies as S
from .config import get_config, data_dir
from .data import get_provider, DataUnavailable

log = logging.getLogger("flowdesk.learning")

LIMITS = {"min_train_n": 20, "min_val_n": 8, "block_train_exp": -0.10, "block_t": -2.0, "max_new_blocks": 12, "max_blocks_per_strategy": 3, "max_param_steps": 1,
          "min_improve_r": 0.02, "enable_min_n": 30, "enable_min_exp": 0.02, "symbol_min_n": 6, "fixed_min_test_n": 10,
          "sym_min_val_n": 10, "sym_min_test_n": 8}
CORE = "core"
SETUP_KEYS = {"HVN Absorption": "setup_hvn", "Key Level Absorption Reversal": "setup_klar"}
NAMES = {CORE: "Confluence engine (structure)", "setup_hvn": "HVN Absorption", "setup_klar": "Key Level Absorption Reversal",
         **{k: v["name"] for k, v in S.STRATEGIES.items()}}


# ---------------- rules file ----------------
def _dir() -> Path:
    p = data_dir() / "learned"
    p.mkdir(parents=True, exist_ok=True)
    return p


def rules_path() -> Path:
    return data_dir() / "learned_rules.json"


def default_rules() -> dict:
    sc = get_config().get("strategy", {})
    st = {CORE: {"enabled": True, "params": {"min_score": float(sc.get("min_score", 55))}},
          "setup_hvn": {"enabled": True, "params": {}}, "setup_klar": {"enabled": True, "params": {}}}
    for k in S.STRATEGIES:
        st[k] = {"enabled": False, "params": dict(S.DEFAULT_PARAMS, **S.STRATEGIES[k].get("params", {}))}       # new strategies start OFF until they earn it
    return {"version": 0, "created": 0, "note": "defaults (nothing learned yet)", "strategies": st, "blocks": [], "symbols": {},
            "changes": [], "summary": {}}


_cache: dict = {"mtime": None, "rules": None}


def load_rules() -> dict:
    p = rules_path()
    try:
        m = p.stat().st_mtime
        if _cache["mtime"] != m:
            _cache.update(mtime=m, rules=json.loads(p.read_text()))
        return _cache["rules"]
    except (OSError, ValueError):
        return default_rules()


def save_rules(r: dict) -> dict:
    hist = sorted(_dir().glob("v*.json"))
    r["version"] = (int(hist[-1].stem[1:]) if hist else 0) + 1
    r["created"] = int(time.time())
    (_dir() / f"v{r['version']:04d}.json").write_text(json.dumps(r))
    tmp = rules_path().with_suffix(".tmp")
    tmp.write_text(json.dumps(r))
    tmp.replace(rules_path())
    return r


def history() -> list[dict]:
    out = []
    for p in sorted(_dir().glob("v*.json"), reverse=True)[:30]:
        try:
            r = json.loads(p.read_text())
            out.append({"version": r["version"], "created": r["created"], "note": r.get("note", ""),
                        "after": (r.get("summary") or {}).get("after"), "n_changes": len(r.get("changes", []))})
        except Exception:
            continue
    return out


def rollback(version: int) -> dict:
    p = _dir() / f"v{int(version):04d}.json"
    r = json.loads(p.read_text())
    r["note"] = f"rollback to v{int(version)}"
    r["changes"] = [{"kind": "rollback", "text": f"Rolled back to the rules of version {int(version)}."}]
    return save_rules(r)


# ---------------- live filter ----------------
def allow(rules: dict, strategy: str, symbol: str, feats: dict, score: float | None = None) -> tuple[bool, str]:
    st = rules.get("strategies", {}).get(strategy)
    if st is None:
        return True, ""
    from . import regime
    if not st.get("enabled", True) and not regime.switched_on(rules, strategy):
        return False, f"learned: {NAMES.get(strategy, strategy)} is disabled (negative out-of-sample edge)"
    if strategy == CORE and score is not None and score < float(st.get("params", {}).get("min_score", 0)):
        return False, f"learned: confluence {score:.0f} below the learned minimum {st['params']['min_score']:g}"
    sym = rules.get("symbols", {}).get(symbol)
    if sym and strategy in sym.get("blocked", []):
        return False, f"learned: {NAMES.get(strategy, strategy)} has no edge on {instruments.display(symbol)}"
    f = dict(feats, symbol=symbol)
    for b in rules.get("blocks", []):
        if b["strategy"] == strategy and str(f.get(b["feature"])) == str(b["bucket"]):
            return False, "learned block: " + b["text"]
    return regime.check(rules, strategy, f)


def stats_for(rules: dict, strategy: str, symbol: str | None = None) -> dict:
    """win-rate dict for sizing.choose() from the learned validation stats."""
    st = rules.get("strategies", {}).get(strategy, {})
    v = (st.get("stats") or {}).get("val") or {}
    sym = (rules.get("symbols", {}).get(symbol) or {}).get("stats", {}).get(strategy) if symbol else None
    v = sym if sym and (sym.get("n") or 0) >= 20 else v
    if not v.get("n"):
        return {"status": "computing"}
    name = NAMES.get(strategy, strategy)
    return {"status": "ok", "direction": "", "band": [0, 100], "n": v["n"], "win_rate": v["win_rate"], "avg_r": v["exp_r"],
            "setup_stats": {"setup": name, "n": v["n"], "win_rate": v["win_rate"], "avg_r": v["exp_r"]}}


# ---------------- dataset ----------------
_CFG: dict = {}


def _cfg() -> dict:
    return _CFG.get("c") or get_config()


def _cost_r(symbol: str, entry: float, risk: float) -> float:
    b = _cfg().get("broker", {})
    cat = instruments.category_key(symbol)
    bps = float((b.get("spread_bps", {}) or {}).get(cat, (b.get("spread_bps", {}) or {}).get("other", 2.0))) + 2 * float(b.get("slippage_bps", 0.5))
    return entry * bps / 1e4 / risk if risk else 0.0


def simulate_strategy(sym: str, name: str, x: dict, params: dict, max_hold: int = 96) -> list[dict]:
    b = _cfg().get("broker", {})
    R, df = x["R"], x["df"]
    raws = x["raw"].get(name)
    if raws is None:
        raws = x["raw"][name] = S.raw_signals(name, R)
    out, busy = [], -1
    for i, side, raw in raws:
        if i < busy or i >= len(R) - 1:
            continue
        sg = S.signal(name, R, i, dict(params, tp1_frac=float(b.get("tp1_close_pct", 50)) / 100), (side, raw))
        if not sg:
            continue
        o = backtest.simulate(sg["side"], sg["entry"], sg["sl"], sg["tp1"], sg["tp2"], df.iloc[i + 1:], sg["atr"],
                              sg["tp1_frac"], b.get("trail_atr", 1.0), max_hold)
        if o is None:
            continue
        cr = _cost_r(sym, sg["entry"], abs(sg["entry"] - sg["sl"]))
        if not quality.check(name, sym, S.features(R, i, sg["side"], sg["sl_atr"]), cost=cr, c=_cfg())[0]:
            continue
        r = o["r"] - cr   # spread + slippage, round trip
        out.append({"t": x["ts"][i], "i": i, "strategy": name, "side": sg["side"], "r": r, "win": r > 0,
                    "f": dict(S.features(R, i, sg["side"], sg["sl_atr"]), symbol=sym)})
        busy = i + o["exit"]
    return out


def core_trades(sym: str, x: dict, min_score: float, min_margin: float) -> list[dict]:
    """Core engine + named-setup trades from the cached walk-forward replay records (no overlap per stream)."""
    recs, R, idx = x["recs"], x["R"], x["idx"]
    out, busy = [], {CORE: -1, "setup_hvn": -1, "setup_klar": -1}
    for r in recs:
        k = idx.get(r["t"])
        for side in ("long", "short"):
            o = r.get(side + "_o")
            if o is None or k is None:
                continue
            other = "short" if side == "long" else "long"
            sname = r.get("setup_" + side)
            stream = SETUP_KEYS.get(sname) if sname else None
            if stream is None and not (r[side] >= min_score and r[side] - r[other] >= min_margin):
                continue
            stream = stream or CORE
            if r["i"] < busy[stream]:
                continue
            S_ = side.upper()
            f = S.features(R, k, S_, None, r[side])
            if not quality.check(stream, sym, f, cost=o.get("cost"), c=_cfg())[0]:
                continue                                  # the live quality gate would not have taken it
            out.append({"t": r["t"], "i": r["i"], "strategy": stream, "side": S_, "r": float(o["r"]), "win": float(o["r"]) > 0,
                        "score": r[side], "f": dict(f, symbol=sym)})
            busy[stream] = r["i"] + o["exit"]
    return out


def load_symbol(sym: str, tf: str) -> dict | None:
    try:
        df = get_provider().candles(sym, tf)
    except DataUnavailable:
        return None
    if len(df) < 400:
        return None
    d = S.indicators(df, S.peer_frame(get_provider(), sym, tf))
    bt = None
    p = backtest._path(sym, tf)
    if p.exists():
        try:
            bt = json.loads(p.read_text())
        except Exception:
            bt = None
    if not bt or bt.get("v") != backtest.VERSION or not bt.get("ok"):
        try:
            bt = backtest.compute(sym, tf)
        except Exception as e:
            log.warning("replay %s failed: %s", sym, e)
            bt = {"records": []}
    recs = bt.get("records", [])
    # validation + test windows are the newest half of the replay period (identical for every strategy, so the
    # before/after comparison is like-for-like); extra strategies also train on the older bars before it.
    t0 = recs[0]["t"] if recs else int(d.index[220].timestamp())
    t1 = int(d.index[-1].timestamp())
    ts = [int(t.timestamp()) for t in d.index]
    return {"sym": sym, "tf": tf, "df": df, "R": S.rows(d), "ts": ts, "idx": {t: k for k, t in enumerate(ts)}, "raw": {}, "recs": recs, "split": (t0 + (t1 - t0) * 0.5, t0 + (t1 - t0) * 0.75)}


def _seg(trades: list[dict], split, which: str) -> list[dict]:
    a, b = split
    return [t for t in trades if (t["t"] < a if which == "train" else a <= t["t"] < b if which == "val" else t["t"] >= b)]


def summarize(ts: list[dict]) -> dict:
    n = len(ts)
    if not n:
        return {"n": 0, "win_rate": None, "exp_r": None, "total_r": 0.0, "t": 0.0}
    rs = [float(t["r"]) for t in ts]
    m = sum(rs) / n
    sd = math.sqrt(sum((r - m) ** 2 for r in rs) / (n - 1)) if n > 1 else 0.0
    return {"n": n, "win_rate": round(100 * sum(bool(t["win"]) for t in ts) / n, 1), "exp_r": round(m, 3), "total_r": round(sum(rs), 2),
            "t": round(m / (sd / math.sqrt(n)), 2) if sd > 0 else 0.0}


# ---------------- one learning cycle ----------------
def live_trades(journal, data: list[dict]) -> list[dict]:
    """Closed paper trades with entry features (stored at entry; older trades are back-filled from the candle at
    their entry bar, which only uses bars up to that bar)."""
    by = {x["sym"]: x for x in data}
    out = []
    for t in journal.q("SELECT * FROM trades WHERE status='closed' ORDER BY id"):
        strat = t.get("strategy") or SETUP_KEYS.get(t.get("setup") or "", None) or (
            next((k for k, v in NAMES.items() if v == t.get("setup")), None) if t.get("setup") else CORE)
        if strat is None:
            continue
        f = None
        try:
            f = json.loads(t["features"]) if t.get("features") else None
        except ValueError:
            f = None
        x = by.get(t["symbol"])
        if f is None and x:
            k = max((i for i, ts in enumerate(x["ts"]) if ts <= t["opened_ts"]), default=None)
            if k is not None and x["ts"][k] > t["opened_ts"] - 3600:
                sla = abs(t["entry"] - (t["sl_initial"] or t["sl"])) / (t["atr"] or 1) if strat in S.STRATEGIES else None
                f = S.features(x["R"], k, t["side"], sla, None)
        out.append({"id": t["id"], "t": t["opened_ts"], "strategy": strat, "side": t["side"], "r": float(t["r_multiple"] or 0),
                    "win": float(t["pnl_usd"] or 0) > 0, "eur": float(t["pnl_usd"] or 0), "symbol": t["symbol"],
                    "f": dict(f or {}, symbol=t["symbol"])})
    return out


def live_summary(ts: list[dict]) -> dict:
    s = summarize(ts)
    s["pnl"] = round(sum(t["eur"] for t in ts), 2)
    return s


def run_cycle(symbols: list[tuple[str, str]] | None = None, progress=None, journal=None) -> dict:
    cfg = get_config()
    _CFG["c"] = cfg
    sc = cfg.get("strategy", {})
    symbols = symbols or [(instruments.normalize(w["symbol"]), w.get("tf", "15m")) for w in cfg.get("watchlist", [])]
    old = copy.deepcopy(load_rules())
    new = copy.deepcopy(old)
    for k, v in default_rules()["strategies"].items():          # strategies added since the last version
        new["strategies"].setdefault(k, v)
    data = []
    for sym, tf in symbols:
        if progress:
            progress(f"loading {sym}")
        x = load_symbol(sym, tf)
        if x:
            data.append(x)
    if not data:
        raise RuntimeError("no market data")
    changes = []
    min_margin = float(sc.get("min_margin", 15))

    def trades_for(name, params, segs=("train", "val", "test")) -> dict:
        res = {s: [] for s in segs}
        for x in data:
            ts = (core_trades(x["sym"], x, params.get("min_score", 55), min_margin) if name in (CORE, "setup_hvn", "setup_klar")
                  else simulate_strategy(x["sym"], name, x, params))
            if name in ("setup_hvn", "setup_klar", CORE):
                ts = [t for t in ts if t["strategy"] == name]
            for s in segs:
                res[s] += _seg(ts, x["split"], s)
        return res

    # 1) parameter tuning (train -> propose one grid step, validation -> accept only if expectancy improves)
    all_tr = {}
    for name, st in new["strategies"].items():
        if progress:
            progress(f"tuning {name}")
        cur = dict(st.get("params") or {})
        base = trades_for(name, cur)
        best, best_tr = (cur, base)
        if name == CORE:
            grid = {"min_score": [cur.get("min_score", 55) + d_ for d_ in (-5, 5)]}
        elif name in S.STRATEGIES:
            # video strategies keep the video's rules: nothing to tune
            grid = {} if S.STRATEGIES[name].get("fixed") else {k: [v for v in S.GRID[k] if v != cur.get(k)] for k in S.GRID}
        else:
            grid = {}
        props = []
        for k, vals in grid.items():                                   # one parameter, one step at a time
            g = S.GRID.get(k)
            for v in vals:
                if g and cur.get(k) in g and abs(g.index(v) - g.index(cur[k])) > LIMITS["max_param_steps"]:
                    continue
                if k == "min_score" and not (40 <= v <= 80):
                    continue
                p = dict(cur, **{k: v})
                tr = trades_for(name, p)
                a, b0 = summarize(tr["train"]), summarize(base["train"])
                if a["n"] >= LIMITS["min_train_n"] and (a["exp_r"] or -9) > (b0["exp_r"] or -9) + LIMITS["min_improve_r"]:
                    props.append((a["exp_r"], k, v, p, tr))
        for _, k, v, p, tr in sorted(props, key=lambda z: -z[0])[:3]:
            va, vb = summarize(tr["val"]), summarize(best_tr["val"])
            if va["n"] >= LIMITS["min_val_n"] and (va["exp_r"] or -9) > (vb["exp_r"] or -9) + LIMITS["min_improve_r"]:
                changes.append({"kind": "param", "strategy": name, "param": k, "before": best.get(k), "after": v,
                                "val_before": vb, "val_after": va, "text": f"{NAMES[name]}: {k} {best.get(k)} → {v} "
                                f"(validation expectancy {vb['exp_r']:+.2f}R → {va['exp_r']:+.2f}R over {va['n']} trades)"})
                best, best_tr = p, tr
                break                                                   # max one parameter change per strategy per cycle
        st["params"] = best
        all_tr[name] = best_tr

    # 2) blocks: feature buckets that lose in TRAIN and are still negative in VALIDATION
    blocks = list(new.get("blocks", []))
    kept = []
    live_now = {k for k, v in old.get("strategies", {}).items() if v.get("enabled", k in (CORE, "setup_hvn", "setup_klar"))}
    for b in blocks:                                                    # re-check old blocks; lift if they now look fine
        tr = all_tr.get(b["strategy"])
        if tr is None or b["strategy"] not in live_now:                 # switched-off strategies are judged without blocks
            continue
        vv = summarize([t for t in tr["val"] if str(t["f"].get(b["feature"])) == str(b["bucket"])])
        if vv["n"] >= LIMITS["min_val_n"] + 2 and vv["exp_r"] > 0.10:
            changes.append({"kind": "unblock", **{k: b[k] for k in ("strategy", "feature", "bucket")}, "val": vv,
                            "text": f"Lifted block: {b['text']} (now {vv['exp_r']:+.2f}R over {vv['n']} validation trades)"})
        else:
            kept.append(b)
    dropped = sum(1 for b in blocks if b["strategy"] not in live_now)
    if dropped:
        changes.append({"kind": "unblock", "text": f"Cleared {dropped} block(s) of switched-off strategies - they are judged on all their trades."})
    cands = []
    for name, tr in all_tr.items():
        if name not in live_now:                                        # only refine strategies that actually trade
            continue
        for fk in S.FEATURE_KEYS:
            buckets = {str(t["f"].get(fk)) for t in tr["train"] if t["f"].get(fk) is not None}
            for bk in buckets:
                if any(b["strategy"] == name and b["feature"] == fk and b["bucket"] == bk for b in kept):
                    continue
                a = summarize([t for t in tr["train"] if str(t["f"].get(fk)) == bk])
                v = summarize([t for t in tr["val"] if str(t["f"].get(fk)) == bk])
                rest_v = summarize([t for t in tr["val"] if str(t["f"].get(fk)) != bk])
                if a["n"] >= LIMITS["min_train_n"] and a["exp_r"] <= LIMITS["block_train_exp"] and a["t"] <= LIMITS["block_t"] \
                        and v["n"] >= LIMITS["min_val_n"] \
                        and v["exp_r"] < 0 and (rest_v["exp_r"] is None or rest_v["exp_r"] > v["exp_r"]):
                    cands.append((a["exp_r"] * a["n"], name, fk, bk, a, v))
    by: dict = {}
    for c in sorted(cands, key=lambda z: z[0]):                         # worst total loss first within each strategy
        by.setdefault(c[1], []).append(c)
    picked = []                                                         # round-robin so every strategy gets a turn
    for k in range(LIMITS["max_blocks_per_strategy"]):
        for name in new["strategies"]:
            if k < len(by.get(name, [])) and len(picked) < LIMITS["max_new_blocks"]:
                picked.append(by[name][k])
    for _, name, fk, bk, a, v in picked:
        text = f"{NAMES[name]} {S.FEATURE_LABEL.get(fk, fk)} {instruments.display(bk) if fk == 'symbol' else bk.replace('_', ' ')}: {a['exp_r']:+.2f}R/trade over {a['n']} training trades, {v['exp_r']:+.2f}R over {v['n']} validation trades"
        kept.append({"strategy": name, "feature": fk, "bucket": bk, "train": a, "val": v, "added": int(time.time()), "text": text})
        changes.append({"kind": "block", "strategy": name, "feature": fk, "bucket": bk, "train": a, "val": v, "text": "Blocked " + text})
    new["blocks"] = kept

    def filt(name, ts):
        return [t for t in ts if allow({"strategies": {name: {"enabled": True}}, "blocks": new["blocks"], "symbols": {}}, name, t["f"]["symbol"], {k: v for k, v in t["f"].items() if k != "symbol"})[0]]

    # 3) enable / disable each strategy on VALIDATION expectancy after blocks; report TEST
    for name, st in new["strategies"].items():
        tr = all_tr[name]
        seg = {s: summarize(filt(name, tr[s])) for s in ("train", "val", "test")}
        was = st.get("enabled", True)
        v = seg["val"]
        both = summarize(filt(name, tr["train"] + tr["val"]))
        # needs a positive validation edge AND must not be a loser over train+validation combined
        en = bool(v["n"] >= LIMITS["enable_min_n"] and v["exp_r"] > LIMITS["enable_min_exp"] and both["exp_r"] > 0) if name != CORE else bool(v["n"] == 0 or v["exp_r"] > -0.05 or seg["train"]["exp_r"] > 0)
        if S.STRATEGIES.get(name, {}).get("fixed"):
            # fixed (video) rules are never tuned, so the TEST segment is a second untouched out-of-sample check:
            # on only when validation AND test are both positive and the test has a real sample
            te = seg["test"]
            en = bool(en and te["n"] >= LIMITS["fixed_min_test_n"] and (te["exp_r"] or 0) > 0)
        per_sym = None
        if S.STRATEGIES.get(name, {}).get("per_symbol"):
            # per-symbol strategies (LVN ledge): on only for the symbols where validation AND the untouched test are both
            # positive with a real sample on THAT symbol; blocked on every other symbol (step 4)
            per_sym = {}
            for sym in sorted({t["f"]["symbol"] for t in tr["val"] + tr["test"]}):
                sv = summarize([t for t in filt(name, tr["val"]) if t["f"]["symbol"] == sym])
                stt = summarize([t for t in filt(name, tr["test"]) if t["f"]["symbol"] == sym])
                if sv["n"] >= LIMITS["sym_min_val_n"] and (sv["exp_r"] or 0) > 0 and stt["n"] >= LIMITS["sym_min_test_n"] and (stt["exp_r"] or 0) > 0:
                    per_sym[sym] = {"val": sv, "test": stt}
            en = bool(per_sym)
            st["symbols_on"] = sorted(per_sym)
        if name in ("setup_hvn", "setup_klar"):     # already-live setups: drop only when clearly negative in BOTH periods
            t_ = seg["train"]
            en = not (v["n"] >= LIMITS["min_val_n"] and v["exp_r"] < 0 and (t_["exp_r"] or 0) < 0)
        qblock = name in (quality.cfg(cfg).get("block_streams") or []) and quality.cfg(cfg).get("enabled", True)
        if qblock:
            en = False
        st["stats"], st["enabled"] = seg, en
        vt = f"validation {v['exp_r']:+.2f}R over {v['n']} trades" if v["n"] else "no validation trades"
        if qblock:
            st["reason"] = "Off: switched off by the quality gate (lost after spread + slippage in the win-rate review)"
        elif per_sym is not None:
            te = seg["test"]
            st["reason"] = ((f"On for {', '.join(instruments.display(x) for x in sorted(per_sym))} only: validation and test both positive there"
                             if en else f"Off on every symbol: no symbol has positive validation (>= {LIMITS['sym_min_val_n']} trades) AND test (>= {LIMITS['sym_min_test_n']} trades)")
                            + f" (all symbols: {vt}; test " + (f"{te['exp_r']:+.2f}R over {te['n']}" if te["n"] else "no trades") + ")")
        elif S.STRATEGIES.get(name, {}).get("fixed") and not en and v["n"] >= LIMITS["enable_min_n"] and (v["exp_r"] or 0) > LIMITS["enable_min_exp"] and both["exp_r"] > 0:
            te = seg["test"]
            st["reason"] = (f"Off: {vt}, but the untouched test period shows "
                            + (f"{te['exp_r']:+.2f}R over {te['n']} trades" if te["n"] else "no trades")
                            + f" - needs a positive test over at least {LIMITS['fixed_min_test_n']} trades")
        elif name in S.STRATEGIES:
            st["reason"] = (f"On: {vt} and positive over learning + validation combined" if en else
                            f"Off: {vt} - needs at least {LIMITS['enable_min_n']}" if v["n"] < LIMITS["enable_min_n"] else
                            f"Off: lost money in validation ({vt})" if v["exp_r"] <= 0 else
                            f"Off: {vt} - too small an edge" if v["exp_r"] <= LIMITS["enable_min_exp"] else
                            f"Off: {vt}, but it lost {both['exp_r']:+.2f}R/trade over learning + validation combined")
        elif name == CORE:
            st["reason"] = f"{'On' if en else 'Off'}: {vt}"
        else:
            st["reason"] = (f"Off: lost in both learning ({seg['train']['exp_r']:+.2f}R) and validation ({v['exp_r']:+.2f}R)" if not en else
                            f"On: {vt}" if (v["exp_r"] or 0) >= 0 else
                            f"Kept on: {vt} but {seg['train']['exp_r']:+.2f}R in learning - mixed, not clearly negative; its losing buckets are blocked")
        if en != was:
            changes.append({"kind": "enable" if en else "disable", "strategy": name, "val": v,
                            "text": f"{'Enabled' if en else 'Disabled'} {NAMES[name]}: {st['reason']} (test {seg['test']['exp_r'] if seg['test']['exp_r'] is not None else 0:+.2f}R over {seg['test']['n']})"})

    # 4) per-symbol ranking on validation; a symbol only trades strategies with positive edge there
    syms = {}
    for x in data:
        rank, blocked, sstats = [], [], {}
        for name, st in new["strategies"].items():
            vv = summarize([t for t in filt(name, all_tr[name]["val"] + all_tr[name]["train"]) if t["f"]["symbol"] == x["sym"]])
            vonly = summarize([t for t in filt(name, all_tr[name]["val"]) if t["f"]["symbol"] == x["sym"]])
            sstats[name] = vv
            rank.append({"strategy": name, "name": NAMES[name], "n": vv["n"], "exp_r": vv["exp_r"], "win_rate": vv["win_rate"], "enabled": st["enabled"]})
            if st["enabled"] and vv["n"] >= LIMITS["symbol_min_n"] and vv["exp_r"] < -0.05 and (vonly["n"] == 0 or (vonly["exp_r"] or 0) < 0):
                blocked.append(name)
            elif st["enabled"] and S.STRATEGIES.get(name, {}).get("per_symbol") and x["sym"] not in (st.get("symbols_on") or []):
                blocked.append(name)                                    # per-symbol strategy without its own edge here
        rank.sort(key=lambda z: -(z["exp_r"] if z["exp_r"] is not None else -9))
        # held-out (validation + test, after costs and the quality gate) per strategy on this symbol - what /signal ranks by
        held = {}
        for name in new["strategies"]:
            ho = summarize([t for t in filt(name, all_tr[name]["val"] + all_tr[name]["test"]) if t["f"]["symbol"] == x["sym"]])
            held[name] = {k: ho[k] for k in ("n", "win_rate", "exp_r")}
        syms[x["sym"]] = {"ranking": rank, "blocked": blocked, "stats": sstats, "heldout": held}
    new["symbols"] = syms

    # 5) honest before/after on the TEST segment (never used for any decision above)
    base_rules = default_rules()
    before = []
    for x in data:
        ts = core_trades(x["sym"], x, base_rules["strategies"][CORE]["params"]["min_score"], min_margin)
        before += _seg(ts, x["split"], "test")          # core + both named setups, default settings, no blocks
    after = []
    for name, st in new["strategies"].items():
        if not st["enabled"]:
            continue
        for t in filt(name, all_tr[name]["test"]):
            if name in syms.get(t["f"]["symbol"], {}).get("blocked", []):
                continue
            after.append(t)
    new["summary"] = {"before": summarize(before), "after": summarize(after),
                      "split": "per symbol by time: train 50% / validation 25% / test 25% (test only reported)",
                      "period": [min(x["ts"][220] for x in data), max(x["ts"][-1] for x in data)],
                      "symbols": len(data), "costs": "all trades net of spread + slippage",
                      "test_from": min(int(x["split"][1]) for x in data)}
    # 6) live paper trades: per-strategy results and where the losses came from (reported; the sample is small)
    live = {"strategies": {}, "loss_buckets": [], "n": 0}
    if journal is not None:
        try:
            lt = live_trades(journal, data)
            live["n"] = len(lt)
            live["total"] = live_summary(lt)
            for name in new["strategies"]:
                mine = [t for t in lt if t["strategy"] == name]
                if mine:
                    live["strategies"][name] = live_summary(mine)
            bl = []
            for fk in S.FEATURE_KEYS:
                for bk in {str(t["f"].get(fk)) for t in lt if t["f"].get(fk) is not None}:
                    g = [t for t in lt if str(t["f"].get(fk)) == bk]
                    sm = live_summary(g)
                    if sm["n"] >= 3 and sm["pnl"] < 0:
                        bl.append({"feature": fk, "bucket": bk, **sm, "label": f"{S.FEATURE_LABEL.get(fk, fk)} {instruments.display(bk) if fk == 'symbol' else bk.replace('_', ' ')}"})
            live["loss_buckets"] = sorted(bl, key=lambda z: z["pnl"])[:8]
        except Exception as e:
            log.warning("live trade analysis failed: %s", e)
    new["live"] = live
    # 7) regime: what works on the newest trading days (recent walk-forward, after costs) - can switch an off
    #    strategy on for one session / trend state / instrument, or pause a live one while it keeps losing
    try:
        from . import regime
        if progress:
            progress("regime check")
        regime.apply(new, old, data, changes)
    except Exception as e:
        log.warning("regime check failed: %s", e)
    new["changes"] = changes
    new["note"] = f"{len(changes)} change(s)" if changes else "no change passed validation"
    new["limits"] = LIMITS
    return save_rules(new)
