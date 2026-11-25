# Win-rate review - 25 Nov 2026

## Where the money went (live paper trades)
Since the 19 Nov reset: 62 closed trades, 30.6% win, -0.47R/trade, -€46.38 (balance €50 -> €3.79 before the €50 top-up).
All history: 94 trades, 31.9% win, -0.40R, -€101.55.

* **Signals from a candle that had not closed yet (main cause).** The scanner read Yahoo's newest 15m bar while it was still forming
  (entries were spread over every minute of the bar); the backtest only ever sees closed bars. Re-checking every live trade on its
  closed bar: 36 of 59 signals did NOT exist once the candle closed -> 22.2% win, -0.68R, **-€46.46** (all of the post-reset loss).
  The 23 that held on the closed bar: 43.5% win, -0.15R, +€1.95.
* **Costs ignored in the stats.** Stop-outs average -1.12R live (-1.25R in the replay): spread + slippage were never charged to the
  core/setup replay, so win rates, learned rules and the risk tiers (10-12%) were built on numbers that were too good.
  The 10% tier: 20 trades, 20% win, -€43.18.
* **Clusters.** Several same-direction entries within minutes (20 Nov 14:00-14:16: 5 shorts, all stopped, -€16.27; 25 Nov 09:00-09:56: 8 shorts, 6 stopped).
* By slice (post reset): shorts 44 trades 25% win -0.61R (core longs are blocked by the learned rules); Asian session 14 trades 14% win -0.82R;
  core engine 35 trades 28.6% win -0.56R; HVN Absorption 19 trades 36.8% -0.26R; score 50s 9% win.

## Test set-up
Full walk-forward replay of the live engine on every closed 15m bar of the 19 symbols (about 45 days, Yahoo), each trade simulated with the
broker rules (50% at TP1 + breakeven, 1-ATR trail, TP2), **net of spread + slippage**, live learned blocks applied, no overlap per stream.
Per symbol by time: TRAIN = oldest 50%, HELD-OUT = newest 50% (validation + test). A change is kept only if it raises the win rate and
does not lower expectancy in BOTH train and held-out (stacked one at a time).

| Change | Train win / R | Held-out win / R | Kept |
|---|---|---|---|
| Baseline (live rules, with costs) | 37.3% / -0.263 | 42.3% / -0.071 | - |
| Skip if costs > 0.20R | 40.8% / -0.135 | 44.5% / +0.091 | yes |
| + HVN Absorption off | 45.1% / -0.038 | 47.4% / +0.139 | yes |
| + higher-timeframe structure agreement | 44.5% / -0.055 | 48.2% / +0.160 | no (train worse) |
| + no London killzone | 42.4% / -0.092 | 52.0% / +0.273 | no (train worse) |
| + TP1 <= 2R (min/max R:R) | 46.6% / -0.037 | 48.8% / +0.118 | no (held-out R lower) |
| + no low-volatility (ATR < 0.8x median) | 45.2% / -0.031 | 47.4% / +0.135 | yes (train better, held-out equal) |
| + no tight stops / no at-level / no late session | | | no (no gain) |
| + max 2 open same-direction trades overall | 47.5% / +0.012 | 49.4% / +0.202 | yes |
| TP1 at exactly 1R (+ breakeven) | 52.9% / -0.067 | 54.2% / +0.049 | **no** - wins more often but earns less |
| TP1 capped at 1.5R | 46.0% / -0.053 | 48.3% / +0.114 | no |

Plus (execution, cannot be backtested): signals only from **closed** candles (futures +11 min feed delay), the fill re-anchored to the live
quote and skipped if less than 1R is left to TP1. News blackout (30 min before / 15 after high-impact events) was already on.

Expected after the change (held-out replay): about 49% win, +0.20R/trade (was 42%, -0.07R with costs; live was 30.6%).
