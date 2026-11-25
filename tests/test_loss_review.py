"""Loss review 2026-11-25 (research/loss_review.md): intra-candle management fix, evidence gate, risk cuts."""
import time
from pathlib import Path

import pandas as pd
import pytest
import yaml

from flowdesk import guard, quality, sizing
from flowdesk.broker import PaperBroker, fresh_range
from flowdesk.journal import Journal

BCFG = {"starting_balance": 10000, "risk_pct": 1.0, "max_positions": 4, "daily_loss_limit_pct": 50.0,
        "tp1_close_pct": 50, "trail_atr": 1.0, "spread_bps": {"futures": 0, "forex": 0, "commodities": 0},
        "slippage_bps": 0}


# ---------- fresh_range ----------
def test_fresh_range_skips_bars_before_entry_and_counts_entry_bar_from_entry_price():
    assert fresh_range(0, 110, 90, 100, 900, 900, 100.0, None) is None             # candle ended at the entry time
    # entry at t=600 inside the 0-900 candle: the candle's low of 90 may be from BEFORE the entry - only entry->close counts
    assert fresh_range(0, 110, 90, 104, 900, 600, 101.0, None) == (104, 101.0)


def test_fresh_range_seen_candle_only_counts_new_extremes_and_close_path():
    st = {"ts": 900, "h": 110, "l": 90, "c": 105}
    assert fresh_range(900, 110, 90, 103, 900, 0, 100.0, st) == (105, 103)           # nothing new: prev close -> close
    assert fresh_range(900, 112, 90, 103, 900, 0, 100.0, st) == (112, 103)           # new high counts
    assert fresh_range(900, 110, 88, 103, 900, 0, 100.0, st) == (105, 88)            # new low counts
    assert fresh_range(0, 110, 90, 103, 900, 0, 100.0, st) is None                   # older candle: done
    assert fresh_range(1800, 120, 95, 99, 900, 0, 100.0, st) == (120, 95)            # new candle: full range


# ---------- the bug: re-reading a forming candle stopped winners at breakeven on pre-TP1 prices ----------
class _Prov:
    def __init__(self):
        self.df = None

    def candles(self, sym, tf):
        return self.df


class _Tg:
    enabled = False


def _bot(j, b, prov):
    from flowdesk.bot import Bot
    bot = object.__new__(Bot)
    bot.cfg, bot.j, bot.b, bot.p, bot.tg = {"telegram": {"auto_alerts": False}}, j, b, prov, _Tg()
    bot.fx = None                                    # refresh_fx fails -> logged and skipped
    return bot


def _frame(rows, start):
    idx = pd.to_datetime([start + 900 * k for k in range(len(rows))], unit="s", utc=True)
    return pd.DataFrame([{"open": r[0], "high": r[1], "low": r[2], "close": r[3], "volume": 0.0} for r in rows], index=idx)


def test_manage_does_not_stop_out_at_breakeven_on_the_same_candle_that_hit_tp1():
    j = Journal(":memory:")
    b = PaperBroker(j, BCFG)
    bar0 = (int(time.time()) // 900) * 900 - 1800
    t = b.open("GC=F", "LONG", 4000, 3990, 4010, 4030, tf="15m", atr=5, ts=bar0 + 100)
    prov = _Prov()
    bot = _bot(j, b, prov)
    # entry candle: dipped to 3995 (above the stop), next candle: spike to TP1 4012 after a dip to 3998 (before TP1)
    prov.df = _frame([(4000, 4003, 3995, 4001), (4001, 4012, 3998, 4011)], bar0)
    bot.manage()
    tr = b._get(t["id"])
    assert tr["tp1_hit"] == 1 and tr["status"] == "open"
    # the same forming candle is read again with the same high/low: the 3998 low happened BEFORE TP1 -> no breakeven exit
    bot.manage()
    tr = b._get(t["id"])
    assert tr["status"] == "open", "re-reading the forming candle closed the runner at breakeven (old bug)"
    # price really comes back below the entry afterwards -> breakeven / trail exit
    prov.df = _frame([(4000, 4003, 3995, 4001), (4001, 4012, 3998, 4011), (4011, 4011, 3999, 3999.5)], bar0)
    bot.manage()
    assert b._get(t["id"])["status"] == "closed"


def test_manage_entry_candle_low_before_entry_does_not_hit_stop():
    j = Journal(":memory:")
    b = PaperBroker(j, BCFG)
    bar0 = (int(time.time()) // 900) * 900 - 900
    t = b.open("GC=F", "LONG", 4000, 3990, 4010, 4030, tf="15m", atr=5, ts=bar0 + 800)
    prov = _Prov()
    prov.df = _frame([(3980, 4002, 3985, 4001)], bar0)                     # low 3985 was before the 800 s entry
    _bot(j, b, prov).manage()
    assert b._get(t["id"])["status"] == "open"


# ---------- evidence gate ----------
def _rules(val=(94, 0.18), test=(58, 0.03), held=(16, 0.42)):
    s = lambda n, e: {"n": n, "win_rate": 50.0, "exp_r": e, "total_r": n * e, "t": 1.0}
    return {"strategies": {"core": {"enabled": True, "stats": {"val": s(*val), "test": s(*test)}}},
            "symbols": {"NQ=F": {"heldout": {"core": {"n": held[0], "exp_r": held[1], "win_rate": 50}}}}, "regime": {}}


class _J:
    def __init__(self, rows):
        self.rows = rows

    def q(self, sql, a=()):
        return self.rows


def test_gate_needs_positive_validation_and_test_with_real_samples():
    c = {"gate": dict(guard.DEFAULTS)}
    assert guard.strategy_ok(_rules(), "core", None, c)[0]
    assert not guard.strategy_ok(_rules(val=(3, 1.6)), "core", None, c)[0]           # Key Level Absorption: 3 trades
    assert not guard.strategy_ok(_rules(test=(58, -0.1)), "core", None, c)[0]        # negative untouched test
    assert not guard.strategy_ok(_rules(test=(5, 0.5)), "core", None, c)[0]          # test too small


def test_gate_symbol_needs_held_out_edge_and_cuts_paper_losers():
    c = {"gate": dict(guard.DEFAULTS)}
    assert guard.symbol_ok(_rules(), "core", "NQ=F", None, c)[0]
    assert not guard.symbol_ok(_rules(held=(5, 0.4)), "core", "NQ=F", None, c)[0]   # too few held-out trades
    assert not guard.symbol_ok(_rules(held=(19, 0.09)), "core", "NQ=F", None, c)[0]  # edge too thin
    assert not guard.symbol_ok(_rules(), "core", "EURUSD=X", None, c)[0]             # no record at all
    guard._live_cache.update(at=0, key=None, val=None)
    losing = _J([{"id": i, "symbol": "NQ=F", "strategy": "core", "setup": None, "r_multiple": -1.1, "opened_ts": 0} for i in range(3)])
    ok, why = guard.check(_rules(), "core", "NQ=F", losing, c)
    assert not ok and "losing live" in why
    guard._live_cache.update(at=0, key=None, val=None)


def test_gate_strategy_wide_kill_counts_only_trades_after_the_fixes():
    c = {"gate": dict(guard.DEFAULTS, clean_since=1000)}
    old = [{"id": i, "symbol": "ES=F", "strategy": "core", "setup": None, "r_multiple": -1.0, "opened_ts": 10} for i in range(20)]
    guard._live_cache.update(at=0, key=None, val=None)
    assert guard.strategy_ok(_rules(), "core", guard.live_stats(_J(old), 1000), c)[0]
    new = [dict(t, opened_ts=2000) for t in old]
    guard._live_cache.update(at=0, key=None, val=None)
    assert not guard.strategy_ok(_rules(), "core", guard.live_stats(_J(new), 1000), c)[0]
    guard._live_cache.update(at=0, key=None, val=None)


# ---------- risk ----------
def test_sizing_skips_negative_expectancy_and_risk_is_small():
    cfg = yaml.safe_load((Path(__file__).resolve().parent.parent / "config.yaml").read_text())
    wr = lambda win, exp, n=40: {"status": "ok", "direction": "SHORT", "band": [55, 75], "n": n, "win_rate": win, "avg_r": exp}
    assert sizing.choose(wr(39, -0.33, 33), cfg)["skip"]                              # USD/CHF short traded at 5% before
    assert sizing.choose(wr(24, -0.52, 29), cfg)["skip"]
    for w in (80, 65, 55, 45, 10):
        s = sizing.choose(wr(w, 0.2), cfg)
        assert not s["skip"] and s["risk_pct"] <= 3.0
    assert sizing.choose({"status": "computing"}, cfg)["risk_pct"] <= 2.0
    br = cfg["broker"]
    assert br["max_risk_per_trade_pct"] <= 5 and br["max_open_risk_pct"] <= 10 and br["daily_loss_limit_pct"] <= 10
    assert br["max_same_direction_risk_pct"] <= br["max_open_risk_pct"] and br["max_positions"] <= 5


def test_broker_hard_caps_risk_per_trade():
    b = PaperBroker(Journal(":memory:"), dict(BCFG, max_risk_per_trade_pct=3.0))
    t = b.open("NQ=F", "LONG", 20000, 19900, 20150, 20300, tf="15m", risk_pct=15.0)
    assert t["risk_usd"] == pytest.approx(300) and "capped at 3% per trade" in t["risk_reason"]


def test_fill_check_rejects_chasing_past_the_signal_close():
    c = {"broker": {"spread_bps": {"forex": 0.8}, "slippage_bps": 0.5},
         "quality": {"enabled": True, "max_cost_r": 0.5, "block_streams": [], "block_atr_regime": [],
                     "min_rr_at_fill": 0.5, "closed_bars_only": True, "max_entry_drift_r": 0.15}}
    mk = lambda px: {"decision": "SHORT", "live_price": px, "levels": {"entry": 1.1000, "sl": 1.1050, "tp1": 1.0900, "tp2": 1.0850}}
    assert quality.fill_check(mk(1.0995), "EURUSD=X", "core", {}, c)[0]            # 0.10R worse: ok
    ok, why = quality.fill_check(mk(1.0990), "EURUSD=X", "core", {}, c)            # 0.20R worse: skip
    assert not ok and "past the signal close" in why
    assert quality.fill_check(mk(1.1010), "EURUSD=X", "core", {}, c)[0]            # better fill: fine
