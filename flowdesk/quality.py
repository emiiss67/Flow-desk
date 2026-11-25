"""Trade-quality gate shared by the live bot and every backtest/learning replay (so the stats match what trades).

Each rule was kept only after it raised the win rate AND did not lower expectancy on held-out data
(newest 50% of the replay, after spread + slippage) - see research/winrate_review.md.
  * max_cost_r       : skip when spread + slippage would eat more than this share of 1R (tight stops on wide spreads)
  * block_streams    : setups that lose after costs (HVN Absorption: 33% win, -0.29R train / -0.24R held-out)
  * block_atr_regime : quiet markets (ATR under 0.8x its median) - stops get hit before targets
Closed bars only + the fill-time R:R check live in the bot (see bot.scan / bot._enter)."""
from __future__ import annotations

from .config import get_config

DEFAULTS = {"enabled": True, "max_cost_r": 0.20, "block_streams": ["setup_hvn"], "block_atr_regime": ["low"],
            "min_rr_at_fill": 1.0, "max_same_direction_open": 2, "closed_bars_only": True}


def cfg(c: dict | None = None) -> dict:
    q = dict(DEFAULTS)
    q.update(((c or get_config()).get("quality") or {}))
    return q


def cost_r(symbol: str, entry: float, risk: float, c: dict | None = None) -> float:
    """Round-trip spread + slippage as a fraction of 1R (same formula as the learning loop)."""
    from . import instruments
    b = (c or get_config()).get("broker", {})
    cat = instruments.category_key(symbol)
    sp = b.get("spread_bps", {}) or {}
    bps = float(sp.get(cat, sp.get("other", 2.0))) + 2 * float(b.get("slippage_bps", 0.5))
    return entry * bps / 1e4 / risk if risk else 9.0


def check(stream: str, symbol: str, feats: dict | None, entry: float | None = None, sl: float | None = None,
          cost: float | None = None, c: dict | None = None) -> tuple[bool, str]:
    q = cfg(c)
    if not q.get("enabled", True):
        return True, ""
    if stream in (q.get("block_streams") or []):
        from .learning import NAMES
        return False, f"quality: {NAMES.get(stream, stream)} is switched off (loses after costs)"
    reg = (feats or {}).get("atr_regime")
    if reg and reg in (q.get("block_atr_regime") or []):
        return False, f"quality: {reg} volatility - stops tend to be hit before targets"
    if cost is None and entry is not None and sl is not None:
        cost = cost_r(symbol, float(entry), abs(float(entry) - float(sl)), c)
    mx = q.get("max_cost_r")
    if cost is not None and mx is not None and cost > float(mx):
        return False, f"quality: spread + slippage would cost {cost:.2f}R (max {float(mx):.2f}R) - stop too tight for the spread"
    return True, ""


def fill_check(r: dict, symbol: str, stream: str, feats: dict, c: dict | None = None) -> tuple[bool, str]:
    """The gate every live entry passes (bot and /signal share it): quality rules + re-anchor the fill to the live quote.
    The signal comes from the last CLOSED candle, so the trade must still offer at least min_rr_at_fill R to TP1 from where
    price is now. On success r["levels"]["entry"] becomes the live price."""
    q = cfg(c)
    lv = r["levels"]
    ok, why = check(stream, symbol, feats, lv["entry"], lv["sl"], c=c)
    if not ok:
        return ok, why
    px = r.get("live_price")
    if q.get("closed_bars_only", True) and px:
        sgn = 1 if r["decision"] == "LONG" else -1
        risk = (float(px) - lv["sl"]) * sgn
        if risk <= 0:
            return False, "price already through the stop since the candle closed"
        rr = (lv["tp1"] - float(px)) * sgn / risk
        mn = float(q.get("min_rr_at_fill", 1.0) or 0)
        if rr < mn:
            return False, f"price moved since the candle closed: only {rr:.2f}R left to TP1 (min {mn:g}R)"
        r["levels"] = dict(lv, entry=float(px))
    return True, ""
