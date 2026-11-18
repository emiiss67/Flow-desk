"""Win-rate based risk sizing: bigger risk when the replayed history of this symbol/setup/score band was better."""
from __future__ import annotations

DEFAULT = {
    "enabled": True,
    "low_sample_n": 20,          # n below this -> base risk
    "base_risk_pct": 35.0,        # low sample / win rate not computed yet
    "skip_expectancy_r": -0.25,  # skip the trade if expectancy <= this AND n >= skip_min_n
    "skip_min_n": 50,
    "negative_risk_pct": 20.0,    # expectancy < 0 (not bad enough to skip)
    "tiers": [                   # [min win %, risk %] - first match from the top
        [70, 80.0], [60, 65.0], [50, 50.0], [40, 35.0], [0, 20.0]],
}


def settings(cfg: dict | None) -> dict:
    s = dict(DEFAULT)
    s.update((cfg or {}).get("sizing", {}) or {})
    return s


def pick_stats(wr: dict | None, low_n: int = 20) -> tuple[dict | None, str]:
    """Prefer the named setup's own history when it has enough trades, else the score-band history."""
    if not wr or wr.get("status") != "ok":
        return None, ""
    ss = wr.get("setup_stats")
    if ss and (ss.get("n") or 0) >= low_n:
        return ss, f"{ss['setup']} history"
    return wr, f"{wr.get('direction', '').lower()} setups scoring {wr['band'][0]}-{wr['band'][1]}" if wr.get("band") else "history"


def choose(wr: dict | None, cfg: dict | None = None) -> dict:
    """Returns {"risk_pct": float, "reason": str, "skip": bool}."""
    s = settings(cfg)
    base = float(s["base_risk_pct"])
    if not s.get("enabled", True):
        fixed = float((cfg or {}).get("broker", {}).get("risk_pct", base))
        return {"risk_pct": fixed, "reason": f"fixed {fixed:g}% (win-rate sizing off)", "skip": False}
    if not wr or wr.get("status") != "ok":
        state = "still computing" if wr and wr.get("status") == "computing" else "unavailable"
        return {"risk_pct": base, "reason": f"base {base:g}% - win rate {state}", "skip": False}
    st, src = pick_stats(wr, int(s["low_sample_n"]))
    n = int(st.get("n") or 0)
    if n < int(s["low_sample_n"]) or st.get("win_rate") is None:
        return {"risk_pct": base, "reason": f"base {base:g}% - low sample (n={n} < {s['low_sample_n']})", "skip": False}
    win, exp = float(st["win_rate"]), float(st.get("avg_r") if st.get("avg_r") is not None else st.get("expectancy_r") or 0)
    tag = f"{src}: win {win:.0f}%, n={n}, exp {exp:+.2f}R"
    if exp <= float(s["skip_expectancy_r"]) and n >= int(s["skip_min_n"]):
        return {"risk_pct": 0.0, "reason": f"skip - strongly negative expectancy ({tag})", "skip": True}
    if exp < 0:
        r = float(s["negative_risk_pct"])
        return {"risk_pct": r, "reason": f"{r:g}% - negative expectancy ({tag})", "skip": False}
    for lo, r in s["tiers"]:
        if win >= float(lo):
            return {"risk_pct": float(r), "reason": f"{float(r):g}% - {tag}", "skip": False}
    return {"risk_pct": base, "reason": f"base {base:g}%", "skip": False}
