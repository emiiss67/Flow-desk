"""Instrument catalog. Any Yahoo ticker is also accepted as free text."""
from __future__ import annotations
import re

# point_value: USD P&L per 1.0 price move per 1 unit (futures = per contract; FX = per unit of base)
# ccy: currencies whose economic events move the instrument
# kw: headline keywords mapping news to the instrument
CATALOG: list[dict] = []


def _add(symbol, name, category, point_value=1.0, ccy=("USD",), kw=(), tick=None):
    CATALOG.append({"symbol": symbol, "name": name, "category": category,
                    "point_value": point_value, "ccy": list(ccy), "kw": list(kw), "tick": tick})


FX = [("EURUSD", "Euro / US Dollar"), ("GBPUSD", "British Pound / US Dollar"), ("USDJPY", "US Dollar / Japanese Yen"),
      ("AUDUSD", "Australian Dollar / US Dollar"), ("USDCAD", "US Dollar / Canadian Dollar"), ("USDCHF", "US Dollar / Swiss Franc"),
      ("NZDUSD", "New Zealand Dollar / US Dollar"), ("EURGBP", "Euro / British Pound"), ("EURJPY", "Euro / Japanese Yen"),
      ("GBPJPY", "British Pound / Japanese Yen"), ("AUDJPY", "Australian Dollar / Japanese Yen"), ("EURCHF", "Euro / Swiss Franc"),
      ("EURAUD", "Euro / Australian Dollar"), ("GBPCHF", "British Pound / Swiss Franc"), ("CADJPY", "Canadian Dollar / Japanese Yen")]
CCY_KW = {"USD": ["fed", "fomc", "powell", "treasury", "dollar", "nfp", "payrolls", "cpi", "us inflation", "jobless"],
          "EUR": ["ecb", "lagarde", "euro", "eurozone", "germany", "german"],
          "GBP": ["boe", "bank of england", "bailey", "sterling", "pound", "uk "],
          "JPY": ["boj", "bank of japan", "ueda", "yen", "japan"],
          "AUD": ["rba", "aussie", "australia"], "CAD": ["boc", "bank of canada", "loonie", "canada"],
          "CHF": ["snb", "swiss franc", "switzerland"], "NZD": ["rbnz", "kiwi", "new zealand"]}
for s, n in FX:
    b, q = s[:3], s[3:]
    _add(f"{s}=X", n, "Forex", 1.0, (b, q), CCY_KW.get(b, []) + CCY_KW.get(q, []) + [s.lower(), f"{b}/{q}".lower()])

_add("ES=F", "E-mini S&P 500", "Futures", 50, ("USD",), ["s&p", "stocks", "wall street", "equities", "fed"], 0.25)
_add("NQ=F", "E-mini Nasdaq-100", "Futures", 20, ("USD",), ["nasdaq", "tech", "nvidia", "apple", "stocks", "fed"], 0.25)
_add("YM=F", "E-mini Dow", "Futures", 5, ("USD",), ["dow", "stocks", "wall street"], 1)
_add("RTY=F", "E-mini Russell 2000", "Futures", 50, ("USD",), ["russell", "small caps", "stocks"], 0.1)
_add("ZN=F", "10-Year T-Note", "Futures", 1000, ("USD",), ["treasury", "yields", "bonds", "fed"], 0.015625)
_add("ZB=F", "30-Year T-Bond", "Futures", 1000, ("USD",), ["treasury", "yields", "bonds"], 0.03125)
_add("6E=F", "Euro FX Futures", "Futures", 125000, ("EUR", "USD"), CCY_KW["EUR"] + CCY_KW["USD"], 0.00005)

_add("^GSPC", "S&P 500 Index", "Indices", 1, ("USD",), ["s&p", "stocks", "wall street"])
_add("^NDX", "Nasdaq-100 Index", "Indices", 1, ("USD",), ["nasdaq", "tech"])
_add("^DJI", "Dow Jones Industrial", "Indices", 1, ("USD",), ["dow"])
_add("^GDAXI", "DAX 40", "Indices", 1, ("EUR",), ["dax", "german", "germany", "ecb"])
_add("^FTSE", "FTSE 100", "Indices", 1, ("GBP",), ["ftse", "uk ", "boe"])
_add("^N225", "Nikkei 225", "Indices", 1, ("JPY",), ["nikkei", "japan", "boj"])
_add("^STOXX50E", "Euro Stoxx 50", "Indices", 1, ("EUR",), ["stoxx", "europe", "ecb"])
_add("^HSI", "Hang Seng", "Indices", 1, ("CNY", "HKD"), ["hang seng", "china", "hong kong"])
_add("^VIX", "CBOE Volatility Index", "Indices", 1, ("USD",), ["vix", "volatility"])

_add("GC=F", "Gold Futures", "Commodities", 100, ("USD",), ["gold", "bullion", "fed", "safe haven"], 0.1)
_add("SI=F", "Silver Futures", "Commodities", 5000, ("USD",), ["silver"], 0.005)
_add("CL=F", "Crude Oil WTI", "Commodities", 1000, ("USD",), ["oil", "crude", "opec", "wti", "brent", "eia"], 0.01)
_add("BZ=F", "Brent Crude", "Commodities", 1000, ("USD",), ["oil", "crude", "opec", "brent"], 0.01)
_add("NG=F", "Natural Gas", "Commodities", 10000, ("USD",), ["natural gas", "lng"], 0.001)
_add("HG=F", "Copper", "Commodities", 25000, ("USD",), ["copper", "china"], 0.0005)
_add("PL=F", "Platinum", "Commodities", 50, ("USD",), ["platinum"], 0.1)

_add("BTC-USD", "Bitcoin", "Crypto", 1, ("USD",), ["bitcoin", "btc", "crypto"])
_add("ETH-USD", "Ethereum", "Crypto", 1, ("USD",), ["ethereum", "ether", "crypto"])
_add("SOL-USD", "Solana", "Crypto", 1, ("USD",), ["solana", "crypto"])

BY_SYMBOL = {i["symbol"]: i for i in CATALOG}
CATEGORY_KEY = {"Forex": "forex", "Futures": "futures", "Indices": "indices", "Commodities": "commodities",
                "Crypto": "crypto"}
_TICKER_RE = re.compile(r"^[\^A-Za-z0-9=._\-]{1,20}$")


def normalize(symbol: str) -> str:
    s = (symbol or "").strip()
    if not s or not _TICKER_RE.match(s):
        raise ValueError("invalid symbol")
    up = s.upper()
    if up in BY_SYMBOL:
        return up
    if re.fullmatch(r"[A-Z]{6}", up) and up[:3] in CCY_KW and up[3:] in CCY_KW:
        return up + "=X"          # EURUSD -> EURUSD=X
    if re.fullmatch(r"(ES|NQ|YM|RTY|GC|SI|CL|NG|HG|ZN|ZB|BZ|PL|6E)", up):
        return up + "=F"
    aliases = {"XAUUSD": "GC=F", "GOLD": "GC=F", "XAGUSD": "SI=F", "OIL": "CL=F", "WTI": "CL=F", "SPX": "^GSPC",
               "NAS100": "NQ=F", "US100": "NQ=F", "US500": "ES=F", "US30": "YM=F", "DAX": "^GDAXI", "GER40": "^GDAXI",
               "UK100": "^FTSE", "JP225": "^N225", "BTC": "BTC-USD", "BTCUSD": "BTC-USD", "ETH": "ETH-USD", "ETHUSD": "ETH-USD"}
    return aliases.get(up, s if s.startswith("^") else up)


def info(symbol: str) -> dict:
    sym = normalize(symbol)
    if sym in BY_SYMBOL:
        return dict(BY_SYMBOL[sym])
    cat = "Forex" if sym.endswith("=X") else "Futures" if sym.endswith("=F") else \
        "Indices" if sym.startswith("^") else "Crypto" if sym.endswith("-USD") else "Other"
    ccy = ["USD"]
    if cat == "Forex" and len(sym) >= 8:
        ccy = [sym[:3], sym[3:6]]
    return {"symbol": sym, "name": sym, "category": cat, "point_value": 1.0, "ccy": ccy, "kw": [], "tick": None,
            "custom": True}


def category_key(symbol: str) -> str:
    i = info(symbol)
    if i["symbol"] in ("ZN=F", "ZB=F"):
        return "rates"
    return CATEGORY_KEY.get(i["category"], "other")


def search(q: str = "", category: str | None = None) -> list[dict]:
    q = (q or "").lower().strip()
    out = []
    for i in CATALOG:
        if category and i["category"].lower() != category.lower():
            continue
        if q and q not in i["symbol"].lower() and q not in i["name"].lower():
            continue
        out.append({k: i[k] for k in ("symbol", "name", "category")})
    return out


def usd_per_quote(symbol: str, price: float, quote_rates: dict | None = None) -> float:
    """Multiplier converting P&L in the instrument's quote currency into USD."""
    i = info(symbol)
    if i["category"] != "Forex":
        return 1.0
    sym = i["symbol"].replace("=X", "")
    q = sym[3:6]
    if q == "USD":
        return 1.0
    if sym[:3] == "USD":
        return 1.0 / price if price else 1.0
    if quote_rates and q in quote_rates:
        return quote_rates[q]
    return 1.0
