"""End-of-day flat, entry block and the daily mistakes review (owner request 2026-11-26)."""
import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from flowdesk import eod, guard, review
from flowdesk.config import get_config
from flowdesk.journal import Journal

CFG = dict(get_config(), gate=dict(get_config()["gate"], clean_since=0))      # test data predates the real clean_since
NY, VIL = ZoneInfo("America/New_York"), ZoneInfo("Europe/Vilnius")


def ts(y, m, d, hh, mm, tz=NY):
    return datetime(y, m, d, hh, mm, tzinfo=tz).timestamp()


def hm(t, tz):
    return datetime.fromtimestamp(t, tz).strftime("%Y-%m-%d %H:%M")


# ---------------- end-of-day schedule ----------------
def test_flat_times_ny_and_vilnius_with_dst():
    for day, vil in (((2026, 11, 18), "23:45"), ((2026, 7, 15), "23:45"), ((2026, 10, 28), "22:45"), ((2026, 3, 10), "22:45")):
        s = eod.status("EURUSD=X", ts(*day, 9, 0))
        assert hm(s["flat"], NY).endswith("16:45") and hm(s["close"], NY).endswith("17:00")
        assert hm(s["no_entry"], NY).endswith("16:15")
        assert hm(s["flat"], VIL).endswith(vil), (day, hm(s["flat"], VIL))


def test_today_nov26_2026_schedule():
    now = ts(2026, 11, 26, 7, 38, VIL)                    # the day it went live (Thanksgiving)
    d = {r["symbol"]: r for r in eod.schedule(get_config(), now)}
    fx = d["EURUSD=X"]
    assert fx["flat"]["vilnius"] == "2026-11-26 23:45" and fx["flat"]["ny"] == "2026-11-26 16:45"
    assert fx["no_entry"]["vilnius"] == "2026-11-26 23:15"
    assert d["BTC-USD"]["flat"]["vilnius"] == "2026-11-26 23:45" and d["BTC-USD"]["reopen"]["ny"].endswith("17:00")
    nq = d["NQ=F"]                                         # CME Thanksgiving halt 12:00 CT = 13:00 ET
    assert nq["close"]["ny"] == "2026-11-26 13:00" and nq["flat"]["ny"] == "2026-11-26 12:45" and nq["flat"]["vilnius"] == "2026-11-26 19:45"
    assert d["GC=F"]["close"]["ny"] == "2026-11-26 14:30"


def test_entry_block_windows():
    assert eod.entry_block("EURUSD=X", ts(2026, 11, 18, 16, 14))[0] is False
    b, why = eod.entry_block("EURUSD=X", ts(2026, 11, 18, 16, 16))
    assert b and "end of day" in why
    assert eod.entry_block("EURUSD=X", ts(2026, 11, 18, 17, 30))[0] is True        # break until 18:00
    assert eod.entry_block("EURUSD=X", ts(2026, 11, 18, 18, 1))[0] is False         # reopened
    assert eod.entry_block("EURUSD=X", ts(2026, 11, 28, 12, 0))[0] is True          # Saturday
    assert eod.entry_block("EURUSD=X", ts(2026, 11, 29, 17, 59))[0] is True         # Sunday before the reopen
    assert eod.entry_block("EURUSD=X", ts(2026, 11, 29, 18, 1))[0] is False
    assert eod.entry_block("BTC-USD", ts(2026, 11, 28, 12, 0))[0] is False          # crypto trades weekends
    assert eod.entry_block("BTC-USD", ts(2026, 11, 28, 16, 30))[0] is True
    assert eod.entry_block("BTC-USD", ts(2026, 11, 28, 17, 0))[0] is False
    assert eod.entry_block("NQ=F", ts(2026, 11, 26, 12, 20))[0] is True             # Thanksgiving early halt
    assert eod.entry_block("NQ=F", ts(2026, 11, 26, 18, 30))[0] is False


def test_disabled_and_override():
    c = {"eod": {"enabled": False}}
    assert eod.entry_block("EURUSD=X", ts(2026, 11, 18, 16, 30), c) == (False, "")
    assert eod.due([{"symbol": "EURUSD=X", "opened_ts": 1}], ts(2026, 11, 18, 17, 0), 0, c) == []
    c = {"eod": {"overrides": {"BTC-USD": {"enabled": False}}}}
    assert eod.entry_block("BTC-USD", ts(2026, 11, 18, 16, 30), c)[0] is False
    assert eod.entry_block("EURUSD=X", ts(2026, 11, 18, 16, 30), c)[0] is True
    c = {"eod": {"close_time": "16:00", "flat_minutes_before": 30}}
    assert hm(eod.status("EURUSD=X", ts(2026, 11, 18, 9, 0), c)["flat"], NY).endswith("15:30")


def test_due_trades():
    t_old = {"symbol": "EURUSD=X", "opened_ts": ts(2026, 11, 18, 10, 0)}
    t_new = {"symbol": "EURUSD=X", "opened_ts": ts(2026, 11, 18, 18, 30)}
    assert eod.due([t_old, t_new], ts(2026, 11, 18, 16, 44)) == []
    assert eod.due([t_old, t_new], ts(2026, 11, 18, 16, 46)) == [t_old]
    assert eod.due([t_old, t_new], ts(2026, 11, 19, 9, 0)) == [t_old]               # missed the flat (bot was down): still flat it
    assert eod.due([t_old], ts(2026, 11, 18, 16, 46), since=ts(2026, 11, 18, 17, 0)) == []   # older session end: never retroactive
    thu = {"symbol": "EURUSD=X", "opened_ts": ts(2026, 11, 17, 12, 0)}
    assert eod.due([thu], ts(2026, 11, 18, 16, 50)) == [thu]
    sun = {"symbol": "EURUSD=X", "opened_ts": ts(2026, 11, 22, 19, 0)}            # opened after the Sunday reopen
    assert eod.due([sun], ts(2026, 11, 23, 10, 0)) == []
    assert eod.due([sun], ts(2026, 11, 23, 16, 50)) == [sun]


def _bot():
    from flowdesk.bot import Bot

    class TG:
        token, chat_id, enabled = "x", "1", True
        sent = []

        def send(self, *a, **k):
            self.sent.append(a); return True

    class Prov:
        name = "fake"

        def candles(self, sym, tf):
            idx = pd.date_range("2026-11-18 20:00", periods=3, freq="15min", tz="UTC")
            return pd.DataFrame({"open": 1.1, "high": 1.1, "low": 1.1, "close": [1.1, 1.1, 1.1020], "volume": 0.0}, index=idx)

    tg = TG()
    b = Bot(journal=Journal(":memory:"), tg=tg)
    b.p = Prov()
    return b, tg


def test_eod_close_at_market_with_costs_and_no_telegram(monkeypatch):
    b, tg = _bot()
    t = b.b.open("EURUSD=X", "LONG", 1.1000, 1.0950, 1.1050, 1.1100, tf="15m", usd_mult=1.0, ts=int(ts(2026, 11, 18, 10, 0)),
                 risk_pct=2, setup=None, strategy="core")
    assert t
    b.j.set("eod_since", 0)
    monkeypatch.setattr(eod, "_clock", lambda: ts(2026, 11, 18, 16, 44))
    import time as _t
    monkeypatch.setattr(_t, "time", lambda: ts(2026, 11, 18, 16, 44))
    b.eod_step()
    assert len(b.b.open_trades()) == 1                                              # 16:44 NY: not yet
    monkeypatch.setattr(_t, "time", lambda: ts(2026, 11, 18, 16, 46))
    b.eod_step()
    assert b.b.open_trades() == []
    tr = b.j.q("SELECT * FROM trades WHERE id=?", (t["id"],))[0]
    assert tr["exit_reason"] == "EOD close" and tr["status"] == "closed"
    assert tr["exit_price"] < 1.1020                                                # sold below the quote: half spread + slippage
    assert tr["closed_ts"] == int(ts(2026, 11, 18, 16, 46))
    assert [f["kind"] for f in b.j.q("SELECT kind FROM fills WHERE trade_id=?", (t["id"],))] == ["entry", "EOD close"]
    assert tg.sent == []                                                            # no unsolicited Telegram messages


def test_eod_not_retroactive_on_first_run(monkeypatch):
    b, _ = _bot()
    b.b.open("EURUSD=X", "LONG", 1.1, 1.095, 1.105, 1.11, tf="15m", usd_mult=1.0, ts=int(ts(2026, 11, 17, 10, 0)), risk_pct=2, strategy="core")
    import time as _t
    monkeypatch.setattr(_t, "time", lambda: ts(2026, 11, 18, 3, 0))                # long after the last flat, feature just deployed
    b.eod_step()
    assert len(b.b.open_trades()) == 1 and b.j.get("eod_since") is not None


def test_bot_enter_blocked_near_close(monkeypatch):
    from flowdesk.bot import Bot
    b, _ = _bot()
    monkeypatch.setattr(eod, "_clock", lambda: ts(2026, 11, 18, 16, 30))
    blk, why = eod.entry_block("EURUSD=X", c=b.cfg)
    assert blk


# ---------------- daily review ----------------
NOW = int(ts(2026, 11, 18, 16, 50))


def add_trade(j, sym="EURUSD=X", strat="core", side="LONG", r=-1.0, feats=None, opened=None, closed=NOW - 3600,
              reason="stop loss", tp1_hit=0, entry=1.1000, sl=1.0950, signal_price=None, sid=None):
    opened = closed - 3600 if opened is None else opened
    sgn = 1 if side == "LONG" else -1
    tp1 = entry + sgn * 0.0050
    f = {"htf_align": "with", "session": "newyork", "killzone": "none", "atr_regime": "normal", "sl_atr": "normal", "score": "70s"}
    f.update(feats or {})
    if signal_price is not None:
        sid = j.x("INSERT INTO signals(ts,symbol,tf,decision,price) VALUES(?,?,?,?,?)", (opened, sym, "15m", side, signal_price))
    return j.x("INSERT INTO trades(signal_id,symbol,tf,side,qty,qty_open,entry,sl,sl_initial,tp1,tp2,risk_usd,point_value,usd_mult,opened_ts,"
               "closed_ts,exit_price,pnl_usd,r_multiple,status,tp1_hit,exit_reason,reasons,tags,strategy,features) "
               "VALUES(?,?,?,?,1,0,?,?,?,?,?,1,1,1,?,?,?,?,?,'closed',?,?,'[]','[]',?,?)",
               (sid, sym, "15m", side, entry, sl, sl, tp1, tp1 + sgn * 0.005, opened, closed, entry, r, r, tp1_hit, reason, strat, json.dumps(f)))


def jr():
    j = Journal(":memory:")
    return j


def fake_bars(after_high=None):
    def f(sym, tf):
        idx = pd.date_range(pd.Timestamp(NOW - 3600, unit="s", tz="UTC"), periods=10, freq="15min")
        hi = [1.1 if after_high is None else after_high] * 10
        return pd.DataFrame({"open": 1.0955, "high": hi, "low": 1.094, "close": 1.0955, "volume": 0.0}, index=idx)
    return f


class Prov:
    def __init__(self, bars):
        self.candles = bars


def run_review(j, **kw):
    kw.setdefault("write_file", False)
    return review.run(j, None, kw.pop("provider", None), now=NOW, events=kw.pop("events", []), c=CFG, **kw)


def test_classify_each_mistake():
    j = jr()
    ids = {
        "counter": add_trade(j, feats={"htf_align": "against"}),
        "chase": add_trade(j, signal_price=1.0970),                                  # filled 0.003 = 0.6R past the signal
        "score": add_trade(j, feats={"score": "50s"}),
        "tight": add_trade(j, feats={"sl_atr": "tight"}),
        "quiet": add_trade(j, feats={"atr_regime": "low"}),
        "gave": add_trade(j, tp1_hit=1, r=-0.2, reason="breakeven"),
        "clean": add_trade(j, feats={"session": "london"}),
        "eod": add_trade(j, r=-0.3, reason="EOD close", closed=NOW - 100),
        "win": add_trade(j, r=1.5, reason="tp2"),
        "news": add_trade(j, sym="GBPUSD=X"),
        "instant": add_trade(j, opened=NOW - 600, closed=NOW - 300),
    }
    ev = [{"ccy": "GBP", "impact": "High", "title": "BoE rate", "ts": NOW - 5400}]
    s = run_review(j, events=ev, learn_too=False)
    by = {x["id"]: x for x in s["trades"]}
    assert by[ids["counter"]]["primary"] == "counter_trend"
    assert by[ids["chase"]]["primary"] == "chased_entry"
    assert by[ids["score"]]["primary"] == "low_quality_score"
    assert "tight_stop" in by[ids["tight"]]["tags"] and "quiet_market" in by[ids["quiet"]]["tags"]
    assert "gave_back_winner" in by[ids["gave"]]["tags"]
    assert "eod_forced" in by[ids["eod"]]["tags"]
    assert by[ids["news"]]["primary"] == "news_spike" and "BoE" in by[ids["news"]]["notes"]["event"]
    assert "instant_adverse" in by[ids["instant"]]["tags"]
    assert by[ids["win"]]["tags"] == [] and by[ids["win"]]["primary"] is None
    assert by[ids["clean"]]["primary"] == "clean_stop"
    assert s["n"] == 11 and s["wins"] == 1 and s["losses"] == 10


def test_stopped_then_reversed_needs_data():
    j = jr()
    i = add_trade(j)
    s = run_review(j, provider=Prov(fake_bars(after_high=1.1060)), learn_too=False)           # price then ran through TP1
    assert "stopped_then_reversed" in s["trades"][0]["tags"]
    j2 = jr(); add_trade(j2)
    s2 = run_review(j2, provider=Prov(fake_bars()), learn_too=False)
    assert "stopped_then_reversed" not in s2["trades"][0]["tags"]
    s3 = run_review(jr(), provider=Prov(lambda *a: (_ for _ in ()).throw(RuntimeError("no data"))), learn_too=False)   # no data -> no claim
    assert s3["n"] == 0


def test_cost_too_high_uses_real_costs():
    from flowdesk.broker import PaperBroker
    j = jr(); b = PaperBroker(j, get_config()["broker"])
    add_trade(j, entry=1.1000, sl=1.0999)                                              # 1 pip stop: costs dwarf the risk
    s = review.run(j, b, None, now=NOW, events=[], c=CFG, write_file=False, learn_too=False)
    assert "cost_too_high" in s["trades"][0]["tags"]
    j = jr(); add_trade(j)
    s = review.run(j, b, None, now=NOW, events=[], c=CFG, write_file=False, learn_too=False)
    assert "cost_too_high" not in s["trades"][0]["tags"]


def test_small_sample_changes_nothing():
    j = jr()
    add_trade(j, feats={"htf_align": "against"})
    s = run_review(j)
    assert s["actions"] == [] and review.active_rules(j, NOW) == {"pauses": [], "blocks": [], "min_score": {}}
    assert guard.check({}, "core", "EURUSD=X", j, {"gate": {"enabled": False}}, feats={"htf_align": "against"}) == (True, "")


def test_repeated_mistake_pauses_combo_and_guard_blocks_it(monkeypatch):
    j = jr()
    add_trade(j, feats={"htf_align": "against"}, closed=NOW - 7000)
    add_trade(j, feats={"htf_align": "against"}, closed=NOW - 3000)
    s = run_review(j)
    assert any(a["kind"] == "pause" and a["symbol"] == "EURUSD=X" for a in s["actions"])
    ok, why = review.blocked(j, "core", "EURUSD=X", {}, None, NOW + 60)
    assert ok and "paused" in why and "against the 1h trend" in why
    assert review.blocked(j, "core", "GBPUSD=X", {}, None, NOW + 60) == (False, "")           # other pair untouched
    assert review.blocked(j, "setup_klar", "EURUSD=X", {}, None, NOW + 60) == (False, "")     # other strategy untouched
    assert review.blocked(j, "core", "EURUSD=X", {}, None, NOW + 4 * 86400) == (False, "")    # pause expires after 3 days
    monkeypatch.setattr(review.time, "time", lambda: NOW + 60)
    ok, why = guard.check({}, "core", "EURUSD=X", j, {"gate": {"enabled": False}})
    assert not ok and why.startswith("daily review")


def test_old_losses_do_not_retrigger_and_pause_never_shortens():
    j = jr()
    add_trade(j, feats={"htf_align": "against"}, closed=NOW - 7000)
    add_trade(j, feats={"htf_align": "against"}, closed=NOW - 3000)
    run_review(j)
    st1 = review.load_state(j)["pauses"][0]["until"]
    # next day, no new trades: the same two losses are still in the window but add no new evidence
    s2 = review.run(j, None, None, now=NOW + 86400, events=[], c=CFG, write_file=False)
    assert s2["n"] == 0 and s2["actions"] == []
    assert review.load_state(j)["pauses"][0]["until"] == st1


def test_loss_streak_and_live_combo_and_strategy_pause():
    j = jr()
    for k in range(3):
        add_trade(j, sym="USDJPY=X", strat="setup_klar", closed=NOW - 9000 + k * 1000, r=-1.0)
    s = run_review(j)
    kinds = {a["text"] for a in s["actions"]}
    assert any("3 losses in a row" in t for t in kinds)
    j = jr()
    for k in range(8):
        add_trade(j, sym=["EURUSD=X", "GBPUSD=X", "USDJPY=X", "AUDUSD=X"][k % 4], strat="momo", closed=NOW - 9000 + k * 100, r=-0.6 if k % 2 else 0.1)
    s = run_review(j)
    assert any(a["symbol"] == "*" and a["strategy"] == "momo" for a in s["actions"])
    ok, why = review.blocked(j, "momo", "NQ=F", {}, None, NOW + 10)
    assert ok and "everywhere" in why


def test_feature_block_after_repeated_counter_trend():
    j = jr()
    for k, sym in enumerate(("EURUSD=X", "GBPUSD=X", "USDJPY=X")):
        add_trade(j, sym=sym, feats={"htf_align": "against"}, closed=NOW - 6000 + k * 500)
    s = run_review(j)
    assert any(a["kind"] == "block" and a["feature"] == "htf_align" for a in s["actions"])
    assert review.blocked(j, "core", "AUDUSD=X", {"htf_align": "against"}, None, NOW + 10)[0] is True
    assert review.blocked(j, "core", "AUDUSD=X", {"htf_align": "with"}, None, NOW + 10)[0] is False


def test_min_score_raised_for_core_only_stricter():
    j = jr()
    add_trade(j, sym="EURUSD=X", feats={"score": "50s"}, closed=NOW - 6000)
    add_trade(j, sym="GBPUSD=X", feats={"score": "50s"}, closed=NOW - 5000)
    s = run_review(j)
    ms = review.load_state(j)["min_score"]["core"]
    assert ms["min"] > 55 and any(a["kind"] == "min_score" for a in s["actions"])
    assert review.blocked(j, "core", "NQ=F", {}, ms["min"] - 1, NOW + 10)[0] is True
    assert review.blocked(j, "core", "NQ=F", {}, ms["min"] + 1, NOW + 10)[0] is False
    # a later review with fewer low-score losses must not lower it while it is active
    j.set("review_last_end", NOW)
    review.run(j, None, None, now=NOW + 86400, events=[], c=CFG, write_file=False)
    assert review.load_state(j)["min_score"]["core"]["min"] >= ms["min"]


def test_review_logged_to_db_file_and_telegram(tmp_path, monkeypatch):
    monkeypatch.setattr(review, "ROOT", tmp_path)
    j = jr()
    add_trade(j, feats={"htf_align": "against"}); add_trade(j, r=1.0, reason="tp2")
    s = review.run(j, None, None, now=NOW, events=[], c=CFG)
    row = j.q("SELECT * FROM daily_reviews")[0]
    assert row["day"] == "2026-11-18" and row["n_trades"] == 2 and row["wins"] == 1 and row["losses"] == 1
    md = (tmp_path / "research" / "daily_reviews" / "2026-11-18.md").read_text()
    assert "against the 1h trend" in md and "EUR/USD" in md
    assert review.latest(j)["n"] == 2
    from flowdesk.commands import Commands
    c = Commands(j, None, None, None)
    out = c.cmd_review([])
    assert "Daily review 2026-11-18" in out and "against the 1h trend" in out
    assert "No daily review yet" in Commands(jr(), None, None, None).cmd_review([])


def test_review_window_reviews_each_trade_once():
    j = jr()
    add_trade(j, closed=NOW - 3000)
    s1 = run_review(j)
    s2 = review.run(j, None, None, now=NOW + 600, events=[], c=CFG, write_file=False)
    assert s1["n"] == 1 and s2["n"] == 0


def test_bot_runs_review_after_flat_once(monkeypatch):
    b, tg = _bot()
    b.cfg = CFG
    add_trade(b.j, closed=int(ts(2026, 11, 18, 12, 0)), opened=int(ts(2026, 11, 18, 9, 0)), feats={"htf_align": "against"})
    import time as _t
    monkeypatch.setattr(review, "ROOT", __import__("pathlib").Path("/tmp/fd-review-test"))
    monkeypatch.setattr(_t, "time", lambda: ts(2026, 11, 18, 10, 0))
    b.eod_step()                                                                      # first run: baseline only
    assert b.j.get("review_done_day") == "2026-11-17"
    monkeypatch.setattr(_t, "time", lambda: ts(2026, 11, 18, 16, 46))
    b.eod_step()
    assert b.j.get("review_done_day") == "2026-11-17"                                # review waits delay_minutes (3) after the flat
    monkeypatch.setattr(_t, "time", lambda: ts(2026, 11, 18, 16, 49))
    b.eod_step()
    assert b.j.get("review_done_day") == "2026-11-18" and review.latest(b.j)["n"] == 1
    n = b.j.q("SELECT COUNT(*) c FROM daily_reviews")[0]["c"]
    b.eod_step()
    assert b.j.q("SELECT COUNT(*) c FROM daily_reviews")[0]["c"] == n and tg.sent == []


def test_status_line_and_api():
    assert "End of day" in eod.headline(get_config(), ts(2026, 11, 18, 9, 0))
    assert "flat at 23:45 (16:45 NY)" in eod.headline(get_config(), ts(2026, 11, 18, 9, 0))
