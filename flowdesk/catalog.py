"""Instrument catalog and ticker resolution.

The JSON file is the single source of truth so the desk and the bot agree.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from flowdesk.models import Instrument

_TICKER = re.compile(r"^[A-Za-z0-9\^=\.\-]{1,24}$")
_CATEGORIES = ("forex", "indices", "futures", "commodities", "crypto", "custom")


def catalog_path() -> Path:
    return Path(__file__).with_name("catalog.json")


@lru_cache(maxsize=1)
def load_catalog(path: str | None = None) -> tuple[Instrument, ...]:
    raw_path = Path(path) if path else catalog_path()
    data = json.loads(raw_path.read_text(encoding="utf-8"))
    items: list[Instrument] = []
    for row in data:
        items.append(
            Instrument(
                id=row["id"],
                name=row["name"],
                category=row["category"],
                yahoo=row["yahoo"],
                oanda=row.get("oanda"),
                pip=float(row["pip"]),
                digits=int(row["digits"]),
                currencies=tuple(row.get("currencies") or ()),
                psych_step=float(row.get("psych_step") or 0),
                spread=float(row.get("spread") or 0),
                slippage=float(row.get("slippage") or 0),
                aliases=tuple(row.get("aliases") or ()),
            )
        )
    return tuple(items)


def categories() -> tuple[str, ...]:
    return _CATEGORIES


def _keys(inst: Instrument) -> list[str]:
    return [inst.id, inst.yahoo, *(() if not inst.oanda else (inst.oanda,)), *inst.aliases]


def search(query: str = "", category: str | None = None, catalog: tuple[Instrument, ...] | None = None) -> list[Instrument]:
    items = list(catalog or load_catalog())
    if category and category not in ("", "all"):
        items = [i for i in items if i.category == category]
    q = (query or "").strip().lower()
    if not q:
        return items
    ranked: list[tuple[int, str, Instrument]] = []
    for inst in items:
        hay = [k.lower() for k in _keys(inst)]
        name = inst.name.lower()
        if q in hay or q in name or any(q in k for k in hay):
            if inst.id.lower() == q or q in hay and any(k == q for k in hay):
                rank = 0
            elif inst.id.lower().startswith(q) or name.startswith(q):
                rank = 1
            else:
                rank = 2
            ranked.append((rank, inst.id, inst))
    ranked.sort(key=lambda row: (row[0], row[1]))
    return [row[2] for row in ranked]


def resolve(query: str, catalog: tuple[Instrument, ...] | None = None) -> tuple[Instrument | None, list[Instrument]]:
    """Return (instrument, candidates).

    An exact id, alias, Yahoo symbol, or OANDA name wins.
    A single substring hit wins. Several hits are returned as candidates.
    A raw Yahoo-looking ticker with no catalog hit becomes an ad-hoc instrument.
    """
    book = catalog or load_catalog()
    q = (query or "").strip()
    if not q:
        return None, []
    ql = q.lower()
    exact = [inst for inst in book if any(k.lower() == ql for k in _keys(inst))]
    # Prefer id matches over yahoo/alias collisions (there should be none).
    id_hits = [inst for inst in exact if inst.id.lower() == ql]
    if len(id_hits) == 1:
        return id_hits[0], []
    if len(exact) == 1:
        return exact[0], []
    if len(exact) > 1:
        return None, exact
    partial = search(q, catalog=book)
    if len(partial) == 1:
        return partial[0], []
    if len(partial) > 1:
        return None, partial
    if _TICKER.match(q):
        return adhoc_instrument(q), []
    return None, []


def adhoc_instrument(ticker: str) -> Instrument:
    symbol = ticker.strip()
    return Instrument(
        id=symbol.upper(),
        name=f"Yahoo ticker {symbol}",
        category="custom",
        yahoo=symbol,
        oanda=None,
        pip=0.01,
        digits=2,
        currencies=tuple(),
        psych_step=0.0,
        spread=0.0,
        slippage=0.0,
        aliases=tuple(),
    )


def derive_psych_step(price: float) -> float:
    magnitude = abs(price)
    if magnitude >= 10000:
        return 500
    if magnitude >= 1000:
        return 50
    if magnitude >= 100:
        return 5
    if magnitude >= 10:
        return 0.5
    if magnitude >= 1:
        return 0.005
    return 0.0005


def digits_for_price(instrument: Instrument, price: float) -> int:
    if instrument.category != "custom":
        return instrument.digits
    if price >= 100:
        return 2
    if price >= 2:
        return 4
    return 5
