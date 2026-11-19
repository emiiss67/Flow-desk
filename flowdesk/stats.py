"""Performance statistics from the journal."""
from __future__ import annotations
from collections import defaultdict
from datetime import datetime, timezone, timedelta

from .journal import Journal


def compute(trades: list[dict], start_balance: float) -> dict:
    closed = sorted([t for t in trades if t["status"] == "closed"], key=lambda t: t["closed_ts"] or 0)
    pnls = [t["pnl_usd"] or 0.0 for t in closed]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gross_w, gross_l = sum(wins), -sum(losses)
    net = sum(pnls)
    eq, peak, mdd = start_balance, start_balance, 0.0
    curve = []
    for t, p in zip(closed, pnls):
        eq += p
        peak = max(peak, eq)
        mdd = max(mdd, peak - eq)
        curve.append({"time": int(t["closed_ts"]), "value": round(eq, 2)})
    # streak of consecutive winners (current) and best
    cur = best = 0
    for p in pnls:
        cur = cur + 1 if p > 0 else 0
        best = max(best, cur)
    now = datetime.now(timezone.utc)
    daily = defaultdict(float)
    for t, p in zip(closed, pnls):
        d = datetime.fromtimestamp(t["closed_ts"], timezone.utc).date().isoformat()
        daily[d] += p
    days30 = [(now.date() - timedelta(days=i)).isoformat() for i in range(29, -1, -1)]
    heat = defaultdict(lambda: {"pnl": 0.0, "n": 0})
    for t, p in zip(closed, pnls):
        dt = datetime.fromtimestamp(t["opened_ts"], timezone.utc)
        k = f"{dt.weekday()}-{dt.hour}"
        heat[k]["pnl"] += p
        heat[k]["n"] += 1
    by_symbol = defaultdict(lambda: {"pnl": 0.0, "n": 0, "wins": 0})
    for t, p in zip(closed, pnls):
        b = by_symbol[t["symbol"]]
        b["pnl"] += p
        b["n"] += 1
        b["wins"] += p > 0
    rs = [t["r_multiple"] for t in closed if t["r_multiple"] is not None]
    return {
        "trades": len(closed), "wins": len(wins), "losses": len(losses),
        "net": round(net, 2), "win_rate": round(100 * len(wins) / len(closed), 1) if closed else 0.0,
        "profit_factor": round(gross_w / gross_l, 2) if gross_l > 0 else (None if not wins else float("inf")),
        "avg_win": round(gross_w / len(wins), 2) if wins else 0.0,
        "avg_loss": round(-gross_l / len(losses), 2) if losses else 0.0,
        "avg_r": round(sum(rs) / len(rs), 2) if rs else 0.0,
        "max_drawdown": round(mdd, 2), "max_drawdown_pct": round(100 * mdd / peak, 2) if peak else 0.0,
        "equity_curve": [{"time": int(closed[0]["opened_ts"]) - 1, "value": start_balance}] + curve if closed else [],
        "streak": cur, "best_streak": best,
        "last_trades": [{"id": t.get("id"), "symbol": t["symbol"], "side": t["side"], "pnl": round(p, 2), "time": t["closed_ts"],
                         "risk": round(t.get("risk_usd") or 0, 2), "risk_pct": t.get("risk_pct"),
                         "pnl_pct_of_risk": round(100 * p / t["risk_usd"], 1) if t.get("risk_usd") else None,
                         "notional": round(t["notional_eur"], 2) if t.get("notional_eur") is not None else None,
                         "leverage": round(t["leverage"], 1) if t.get("leverage") is not None else None}
                        for t, p in list(zip(closed, pnls))[-14:]],
        "daily_30": [{"date": d, "pnl": round(daily.get(d, 0.0), 2)} for d in days30],
        "heatmap": {k: {"pnl": round(v["pnl"], 2), "n": v["n"]} for k, v in heat.items()},
        "by_symbol": {k: {"pnl": round(v["pnl"], 2), "n": v["n"], "win_rate": round(100 * v["wins"] / v["n"], 1)}
                      for k, v in by_symbol.items()},
    }


def performance(j: Journal, start_balance: float) -> dict:
    trades = j.trades(limit=100000)
    out = compute(trades, start_balance)
    rs = j.get("equity_reset")
    if rs and rs.get("ts"):
        # fresh equity baseline: the curve, net, drawdown and return start at the reset;
        # win rate / profit factor / R / heatmap / per-symbol keep the whole history (learning + stats)
        ts0, base = int(rs["ts"]), float(rs["balance"])
        since = compute([t for t in trades if t["status"] == "closed" and (t["closed_ts"] or 0) >= ts0], base)
        out["all_time"] = {k: out[k] for k in ("net", "trades", "wins", "losses", "win_rate", "max_drawdown", "max_drawdown_pct")}
        for k in ("net", "max_drawdown", "max_drawdown_pct"):
            out[k] = since[k]
        out["since_reset"] = {k: since[k] for k in ("net", "trades", "wins", "losses", "win_rate")}
        out["equity_curve"] = [{"time": ts0, "value": base}] + since["equity_curve"][1:] if since["trades"] else []
        out["reset"] = {"ts": ts0, "balance": base, "from_balance": rs.get("from_balance")}
        out["start_balance"] = base
    if out.get("profit_factor") == float("inf"):
        out["profit_factor"] = None
        out["profit_factor_note"] = "no losing trades yet"
    return out
