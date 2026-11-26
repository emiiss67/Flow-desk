"""Evidence gate (loss review 2026-11-25, research/loss_review.md): a strategy may only open a trade on a symbol when
there is POSITIVE OUT-OF-SAMPLE evidence for it and it is not losing in live paper trading.

  1. strategy level : validation (>= min_val_n trades) AND the untouched test segment (>= min_test_n) both positive,
                      after costs. A strategy the regime check switched on (positive pick AND check days) also passes.
  2. symbol level   : held-out (validation + test) record of that strategy on THAT symbol: >= sym_min_n trades and
                      expectancy >= sym_min_exp R.
  3. live kill      : the strategy on that symbol in live paper trading: >= live_min_n closed trades with an average of
                      live_kill_exp R or worse -> off there (losing live AND not proven in the backtest = cut).
  4. strategy live  : closed trades since `clean_since` (after the closed-candle / management fixes) - >= strat_live_min_n
                      with an average at or below strat_live_kill_exp R -> the whole strategy is off.

  5. daily review    : the end-of-day mistakes review (review.py) can pause a strategy x symbol, block a feature bucket or raise
                      the core minimum score for a few days - restrictions only, they expire and never relax 1-4.

Shared by the bot (bot._enter) and /signal (signalcall) so what /signal says is what the bot does."""
from __future__ import annotations

import time

from .config import get_config

DEFAULTS = {"enabled": True, "min_val_n": 30, "min_val_exp": 0.02, "min_test_n": 10, "min_test_exp": 0.0,
            "sym_min_n": 8, "sym_min_exp": 0.10, "live_min_n": 3, "live_kill_exp": -0.5,
            "clean_since": 1795632000, "strat_live_min_n": 15, "strat_live_kill_exp": -0.25}

_live_cache: dict = {"at": 0.0, "key": None, "val": None}


def cfg(c: dict | None = None) -> dict:
    g = dict(DEFAULTS)
    g.update(((c or get_config()).get("gate") or {}))
    return g


def stream_of(t: dict) -> str:
    from .learning import CORE, NAMES, SETUP_KEYS
    if t.get("strategy"):
        return t["strategy"]
    if t.get("setup"):
        return SETUP_KEYS.get(t["setup"]) or next((k for k, v in NAMES.items() if v == t["setup"]), CORE)
    return CORE


def live_stats(journal, since_clean: int = 0, ttl: float = 60.0) -> dict:
    """{"sym": {(strategy, symbol): [r, ...]}, "clean": {strategy: [r, ...]}} from closed paper trades (cached ttl s)."""
    key = (id(journal), since_clean)
    now = time.time()
    if _live_cache["key"] == key and now - _live_cache["at"] < ttl and _live_cache["val"] is not None:
        return _live_cache["val"]
    out: dict = {"sym": {}, "clean": {}}
    if journal is not None:
        for t in journal.q("SELECT id, symbol, strategy, setup, r_multiple, opened_ts FROM trades WHERE status='closed'"):
            s = stream_of(t)
            r = float(t.get("r_multiple") or 0)
            out["sym"].setdefault((s, t["symbol"]), []).append(r)
            if int(t.get("opened_ts") or 0) >= since_clean:
                out["clean"].setdefault(s, []).append(r)
    _live_cache.update(at=now, key=key, val=out)
    return out


def _avg(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def strategy_ok(rules: dict, name: str, live: dict | None = None, c: dict | None = None) -> tuple[bool, str]:
    from . import learning, regime
    g = cfg(c)
    if not g.get("enabled", True):
        return True, ""
    label = learning.NAMES.get(name, name)
    st = (rules.get("strategies") or {}).get(name) or {}
    stats = st.get("stats") or {}
    v, te = stats.get("val") or {}, stats.get("test") or {}
    proven = ((v.get("n") or 0) >= g["min_val_n"] and (v.get("exp_r") or 0) > g["min_val_exp"]
              and (te.get("n") or 0) >= g["min_test_n"] and (te.get("exp_r") or 0) > g["min_test_exp"])
    if not proven and not regime.switched_on(rules, name):
        def seg(d, lab):
            return f"{lab} {d['exp_r']:+.2f}R over {d['n']}" if d.get("n") else f"no {lab} trades"
        return False, (f"gate: {label} has no proven out-of-sample edge ({seg(v, 'validation')}, {seg(te, 'test')}; "
                       f"needs both positive with >= {g['min_val_n']} / {g['min_test_n']} trades)")
    cl = (live or {}).get("clean", {}).get(name) or []
    if len(cl) >= g["strat_live_min_n"] and _avg(cl) <= g["strat_live_kill_exp"]:
        return False, f"gate: {label} is losing live ({_avg(cl):+.2f}R over {len(cl)} trades since the fixes)"
    return True, ""


def symbol_ok(rules: dict, name: str, symbol: str, live: dict | None = None, c: dict | None = None) -> tuple[bool, str]:
    from . import instruments, learning
    g = cfg(c)
    if not g.get("enabled", True):
        return True, ""
    label, disp = learning.NAMES.get(name, name), instruments.display(symbol)
    ho = ((((rules.get("symbols") or {}).get(symbol) or {}).get("heldout") or {}).get(name)) or {}
    n, e = int(ho.get("n") or 0), ho.get("exp_r")
    if n < g["sym_min_n"] or e is None or e < g["sym_min_exp"]:
        rec = f"{e:+.2f}R over {n}" if n and e is not None else "no trades"
        return False, (f"gate: {label} not proven on {disp} (held-out {rec}; needs >= {g['sym_min_n']} trades "
                       f"and >= {g['sym_min_exp']:+.2f}R)")
    lv = (live or {}).get("sym", {}).get((name, symbol)) or []
    if len(lv) >= g["live_min_n"] and _avg(lv) <= g["live_kill_exp"]:
        return False, f"gate: {label} is losing live on {disp} ({_avg(lv):+.2f}R over {len(lv)} paper trades)"
    return True, ""


def check(rules: dict, name: str, symbol: str, journal=None, c: dict | None = None, feats: dict | None = None,
          score: float | None = None) -> tuple[bool, str]:
    g = cfg(c)
    if g.get("enabled", True):
        live = live_stats(journal, int(g.get("clean_since") or 0)) if journal is not None else None
        ok, why = strategy_ok(rules, name, live, c)
        if not ok:
            return ok, why
        ok, why = symbol_ok(rules, name, symbol, live, c)
        if not ok:
            return ok, why
    if journal is not None:                      # daily mistakes review (review.py): only ever adds restrictions
        from . import review
        if review.cfg(c).get("enabled", True):
            blk, why = review.blocked(journal, name, symbol, feats, score)
            return (not blk), why
    return True, ""
