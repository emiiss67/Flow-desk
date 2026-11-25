"""/signal + desk "Best strategy": per-symbol ranking from held-out stats, BUY/SELL/NO TRADE with the live bot's gates."""
import time

import pytest

from flowdesk import signalcall as SC
from flowdesk.broker import PaperBroker
from flowdesk.journal import Journal

SYM = "EURUSD=X"
CFG = {"watchlist": [{"symbol": "EURUSD=X", "tf": "15m"}, {"symbol": "NQ=F", "tf": "15m"}],
       "broker": {"starting_balance": 1000, "account_currency": "USD", "risk_pct": 1.0, "max_positions": 5,
                  "spread_bps": {"forex": 0.8}, "slippage_bps": 0.5},
       "quality": {"enabled": True, "max_cost_r": 0.20, "block_streams": [], "block_atr_regime": [], "min_rr_at_fill": 1.0, "closed_bars_only": True,
                   "max_entry_drift_r": None},
       "sizing": {"enabled": True}, "strategy": {"min_score": 55, "min_margin": 15}, "scanner": {}}


def rules(**kw):
    ho = {"core": {"n": 40, "win_rate": 52.0, "exp_r": 0.10}, "silver_bullet": {"n": 25, "win_rate": 58.0, "exp_r": 0.30},
          "orb": {"n": 5, "win_rate": 80.0, "exp_r": 0.90}}
    r = {"strategies": {"core": {"enabled": True, "params": {"min_score": 60}, "stats": {"val": {"n": 90, "win_rate": 50, "exp_r": 0.05},
                                                                                   "test": {"n": 40, "win_rate": 50, "exp_r": 0.04}}},
                        "silver_bullet": {"enabled": True, "params": {}}, "orb": {"enabled": True, "params": {}},
                        "vwap_revert": {"enabled": False, "params": {}}, "setup_hvn": {"enabled": True, "params": {}}},
         "symbols": {SYM: {"blocked": ["setup_hvn"], "heldout": ho}}}
    r.update(kw)
    return r


class FX:
    def mult(self, *a, **k):
        return 1.0


class Prov:
    def candles(self, *a, **k):
        return None


def fake_check(decision="NO TRADE", live=None, entry=1.1000, sl=1.1050):
    def f(symbol, tf, **k):
        assert k.get("closed_only") is True              # /signal must read finished candles only
        base = {"ok": True, "symbol": symbol, "tf": tf, "decision": decision, "price": entry, "live_price": live or entry,
                "last_bar": int(time.time()) - 300, "confluence": 70, "scores": {"long": 20, "short": 70}, "setup": None,
                "reasons": [{"text": "Sweep of the Asian high, then a bearish order block", "tag": "ICT", "points": 20}],
                "blackout": None, "source": "test"}
        if decision != "NO TRADE":
            base["levels"] = {"entry": entry, "sl": sl, "tp1": 1.0925, "tp2": 1.0880}
        return base
    return f


@pytest.fixture
def env(monkeypatch):
    import flowdesk.strategy as ST
    b = PaperBroker(Journal(":memory:"), CFG["broker"])
    monkeypatch.setattr(SC.S, "indicators", lambda d: d)
    monkeypatch.setattr(SC.S, "rows", lambda d: [{"hour": 9, "adx1h": 25}])
    monkeypatch.setattr(SC.S, "features", lambda R, i, side, sl_atr=None, score=None: {"atr_regime": "normal", "side": side})
    monkeypatch.setattr(SC.S, "signal", lambda *a, **k: None)
    monkeypatch.setattr(SC, "closed_bars", lambda df, *a, **k: df)
    monkeypatch.setattr("flowdesk.backtest.winrate", lambda *a, **k: {"status": "ok", "direction": "SHORT", "band": [60, 80], "n": 60, "win_rate": 55.0, "avg_r": 0.2,
                                                                         "setup_stats": None})
    SC._cache.clear()
    return ST, b, monkeypatch


def run(ST, b, mp, check, rl=None):
    mp.setattr(ST, "check", check)
    return SC.evaluate(SYM, b, b.j, FX(), CFG, Prov(), rl or rules())


def test_resolve_friendly_names():
    assert SC.resolve("EURUSD") == "EURUSD=X"
    assert SC.resolve("eur/usd") == "EURUSD=X"
    assert SC.resolve("NAS100") == "NQ=F"
    assert SC.resolve("gold") == "GC=F"
    assert SC.resolve("definitely-not-a-market") is None


def test_ranking_uses_per_symbol_heldout_and_filters_blocked():
    u = SC.universe(rules(), SYM)
    names = [z["strategy"] for z in u]
    assert names[0] == "silver_bullet"                    # best held-out expectancy among proper samples
    assert names[-1] == "orb" and u[-1]["low_sample"]     # n=5 ranks after every proper sample, flagged
    assert "setup_hvn" not in names and "vwap_revert" not in names     # blocked on the symbol / disabled
    assert u[0]["basis"].startswith("held-out on")
    paused = rules(regime={"computed": int(time.time()), "strategies": {"silver_bullet": {"state": "paused", "reason": "x", "name": "x"}}})
    assert "silver_bullet" not in [z["strategy"] for z in SC.universe(paused, SYM)]


def test_sell_call_has_levels_rr_size_and_reason(env):
    ST, b, mp = env
    d = run(ST, b, mp, fake_check("SHORT", live=1.0995))
    assert d["call"] == "SELL" and d["strategy"]["strategy"] == "core"
    p = d["plan"]
    assert p["entry"] == pytest.approx(1.0995)           # re-anchored to the live quote like the bot
    assert p["rr1"] == pytest.approx((1.0995 - 1.0925) / (1.1050 - 1.0995), abs=0.01)
    assert d["size"]["ok"] and d["size"]["risk_amount"] > 0 and d["size"]["size_text"].endswith("lots")
    assert d["risk_pct"] > 0 and "bearish order block" in d["reason"]
    assert d["best"]["strategy"] == "silver_bullet" and "ranks first" in d["note"]
    assert any(x["name"] for x in d["runner_ups"])
    text = SC.fmt_one(d, "USD")
    assert "SELL" in text and "Best strategy here" in text and "Stop" in text


def test_no_trade_says_what_it_waits_for(env):
    ST, b, mp = env
    d = run(ST, b, mp, fake_check("NO TRADE"))
    assert d["call"] == "NO TRADE" and "plan" not in d
    assert "waiting" in d and d["waiting"]
    assert "NO TRADE" in SC.fmt_one(d, "USD")


def test_price_ran_away_is_reported_not_traded(env):
    ST, b, mp = env
    d = run(ST, b, mp, fake_check("SHORT", live=1.0940))          # ~0.2R left to TP1
    assert d["call"] == "NO TRADE" and "left to TP1" in d["waiting"]


def test_blocked_strategy_and_cost_gate_match_bot(env):
    ST, b, mp = env
    rl = rules()
    rl["strategies"]["core"]["enabled"] = False
    d = run(ST, b, mp, fake_check("SHORT"), rl)
    assert d["call"] == "NO TRADE"                                 # core is not in the allowed universe
    d = run(ST, b, mp, fake_check("SHORT", entry=1.1000, sl=1.1002))   # 2-pip stop: costs eat the trade
    assert d["call"] == "NO TRADE"


def test_open_trade_limits_apply(env):
    ST, b, mp = env
    assert b.open(SYM, "SHORT", 1.1000, 1.1050, 1.0925, 1.0880, setup=None)
    d = run(ST, b, mp, fake_check("SHORT"))
    assert d["call"] == "NO TRADE"                                 # can_open refuses a second same-symbol trade with the same setup


def test_top_lists_actionable_first(env, monkeypatch):
    ST, b, mp = env
    mp.setattr(ST, "check", fake_check("SHORT"))
    monkeypatch.setattr(SC.learning, "load_rules", lambda: rules())
    t = SC.top(b, b.j, FX(), CFG, Prov())
    assert t["n_symbols"] == 2 and t["actionable"][0]["call"] == "SELL"
    assert "Top setups" in SC.fmt_top(t, "USD")


def test_telegram_command(env):
    ST, b, mp = env
    from flowdesk.commands import Commands
    mp.setattr(ST, "check", fake_check("SHORT"))
    mp.setattr(SC.learning, "load_rules", lambda: rules())
    mp.setattr(SC, "get_config", lambda: CFG)
    c = Commands(b.j, b, Prov(), None)
    c.fx = FX()
    assert "don't know the symbol" in c.handle("/signal blahblah")
    out = c.handle("/signal EURUSD")
    assert "SELL" in out and "Best strategy" in out
    assert "/signal" in c.handle("/help")


def test_symbol_without_heldout_data_ranks_after_proven_ones_and_is_not_called_best_edge():
    r = rules()
    r["symbols"][SYM]["heldout"] = {"core": {"n": 0, "win_rate": None, "exp_r": None}, "silver_bullet": {"n": 12, "win_rate": 40.0, "exp_r": -0.2}}
    r["strategies"]["orb"]["stats"] = {"val": {"n": 83, "win_rate": 54, "exp_r": 0.4}}
    u = SC.universe(r, SYM)
    assert u[0]["strategy"] == "silver_bullet" and not u[0]["edge"]       # has symbol data (tier 0), but negative: no "proven edge"
    assert [z["tier"] for z in u] == sorted(z["tier"] for z in u)
    assert next(z for z in u if z["strategy"] == "orb")["basis"] == "validation, all symbols"
    assert next(z for z in u if z["strategy"] == "orb")["tier"] == 2


def test_evidence_gate_says_no_trade_without_an_untouched_test_record(env):
    ST, b, mp = env
    rl = rules()
    rl["strategies"]["core"]["stats"].pop("test")
    d = run(ST, b, mp, fake_check("SHORT", live=1.0995), rl)
    assert d["call"] == "NO TRADE" and "gate:" in d["waiting"]
