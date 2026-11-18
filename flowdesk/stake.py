"""How much went into a trade, in the account currency: amount at risk (and % of the balance at entry), position
size in the instrument's own unit (forex lots, futures contracts, units), notional value and the leverage that
notional represents. Stored on the trade at entry; trades from before this existed are computed from their stored
qty / point value / FX multiplier (for still-open old trades that FX multiplier is the latest, so it is approximate)."""
from __future__ import annotations

from . import instruments
from .currency import fmt_money

LOT = 100_000           # 1 standard forex lot = 100,000 units of the base currency


def size_unit(symbol: str, qty: float) -> tuple[float, str]:
    cat = instruments.info(symbol).get("category")
    if cat == "Forex":
        return qty / LOT, "lots"
    if cat in ("Futures", "Commodities"):
        return qty, "contracts"
    return qty, "units"


def fmt_size(v: float, unit: str) -> str:
    """'0.0234 lots', '1.5 lots', '1 contract', '0.37 contracts' (3 significant digits below 1)."""
    a = abs(v)
    if a == 0:
        return f"0 {unit}"
    txt = f"{v:,.2f}".rstrip("0").rstrip(".") if a >= 1 else f"{v:.3g}"
    if unit == "contracts" and txt in ("1", "-1"):
        unit = "contract"
    return f"{txt} {unit}"


def entry_values(symbol: str, qty: float, entry: float, point_value: float, mult: float, equity: float) -> dict:
    notional = abs(qty * entry * point_value * mult)
    return {"notional_eur": round(notional, 2), "equity_at_entry": round(equity, 2),
            "leverage": round(notional / equity, 2) if equity else None}


def of_trade(t: dict, ccy: str = "EUR") -> dict:
    qty = float(t.get("qty") or 0)
    risk = float(t.get("risk_usd") or 0)
    rp = t.get("risk_pct")
    eq = t.get("equity_at_entry") or (risk * 100 / rp if rp else None)
    notional = t.get("notional_eur")
    if notional is None:
        notional = abs(qty * float(t.get("entry") or 0) * float(t.get("point_value") or 1) * float(t.get("usd_mult") or 1))
    lev = t.get("leverage") or (notional / eq if eq else None)
    sv, unit = size_unit(t["symbol"], qty)
    pnl = float(t.get("pnl_usd") or 0) + float(t.get("unrealized") or 0)
    out = {"risk_eur": round(risk, 2), "risk_pct": round(float(rp), 1) if rp is not None else None, "qty": qty,
           "size": round(sv, 6), "size_unit": unit, "size_text": fmt_size(sv, unit), "notional_eur": round(notional, 2),
           "equity_at_entry": round(eq, 2) if eq else None, "leverage": round(lev, 1) if lev else None,
           "pnl_pct_of_risk": round(100 * pnl / risk, 1) if risk else None}
    lev_t = f" · {out['leverage']:,.0f}x" if out["leverage"] and out["leverage"] >= 1 else (f" · {out['leverage']:.2f}x" if out["leverage"] else "")
    out["text"] = (f"Risk {fmt_money(risk, ccy, False)}" + (f" ({out['risk_pct']:g}%)" if rp is not None else "") +
                   f" · Size {out['size_text']} · Notional {fmt_money(notional, ccy, False, None)}{lev_t}")
    return out
