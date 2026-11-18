from flowdesk import instruments
from flowdesk.events import relevance, map_headline, why_it_matters


def test_display_names_have_no_raw_tickers():
    assert instruments.display("EURUSD=X") == "EUR/USD"
    assert instruments.display("NQ=F") == "Nasdaq 100 (NQ)"
    assert instruments.display("ES=F") == "S&P 500 (ES)"
    assert instruments.display("YM=F") == "Dow (YM)"
    assert instruments.display("GC=F") == "Gold" and instruments.display("BTC-USD") == "Bitcoin"
    for raw in ("USDTRY=X", "ZC=F", "^XYZ", "DOGE-USD"):
        d = instruments.display(raw)
        assert not any(x in d for x in ("=X", "=F", "^", "-USD")), d
    assert instruments.icon("EURUSD=X") == "🇪🇺🇺🇸"


def test_personal_finance_headlines_dropped():
    for t in ["My husband is happily retired at 64 and thinks I should keep working. Is he being fair?",
              "‘It’s downright dirty’: My brother took over our ailing mother’s life and finances. What can we do?",
              "It’s not too late to add U.S. energy companies to your 401(k)",
              "‘Nvidia’s turmoil has me spooked’: Has the time come to sell my stocks and buy real estate?"]:
        assert relevance(t) <= 0, t


def test_market_headlines_kept_and_tagged_specifically():
    t = "Silver Price Forecast: XAG/USD hovers at yearly lows amid Fed hiking bets"
    assert relevance(t) > 0 and map_headline(t) == ["SI=F"]
    t = "Dollar slips as Fed's Powell signals patience on rate cuts"
    assert relevance(t) > 0 and "EURUSD=X" in map_headline(t) and why_it_matters(t)
    assert map_headline("Stocks close higher as Dow gains 300 points") == ["ES=F", "YM=F"]
    assert not any(s.startswith("^") and s == "^DJI" for s in map_headline("Dow jumps"))
