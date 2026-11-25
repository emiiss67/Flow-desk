# Loss review - 25 Nov 2026

Data: live journal (102 closed paper trades, 19 Nov - 25 Nov 19:15 Vilnius) + learned rules v22.

## Where the money went
| | trades | win % | avg R | P&L (EUR) |
|---|---|---|---|---|
| all closed | 102 | 33.3 | -0.37 | -100.29 |
| since 25 Nov 00:00 | 18 | 33.3 | -0.42 | -1.65 |
| since the win-rate review deploy (11:05) | 5 | 40 | -0.20 | -1.13 |

* Payoff: 68 stop-outs averaged -1.11R; winners averaged only about +1.1R (trailing +1.13R, TP2 +1.51R, breakeven +0.44R),
  although TP2 sat at 2-3R. At about 33% wins that is -0.37R a trade.
* Risk: 5-35% a trade. The four 35% trades all lost (-EUR 56.69 together). The account went from EUR 50 to EUR 3.79 before the top-up.
* By strategy (live): Confluence engine 58 trades, 29% win, -0.52R (t -4.1), -EUR 66; Key Level Absorption 7 trades, 14% win,
  -0.77R, -EUR 37; HVN about flat (already off).
* Shorts: 71 trades, 31% win, -EUR 83; longs: 31 trades, 39% win, -EUR 18.
* Worst symbols: EUR/USD (11 trades, 18% win, -EUR 27.8), Dow (-EUR 19.0), Bitcoin (-EUR 18.9), AUD/JPY (-EUR 14.9).
* Costs: entries filled on average 0.10R worse than the signal close (up to 0.35R), and stops filled 0.12R past the stop.
  Together that is about 0.2R a trade.

## Bugs found
1. **Forming-candle re-read in trade management.** The manager re-tested the forming candle's FULL high/low every cycle. After
   TP1 moved the stop to breakeven, or the trail moved it, price from before the move then "hit" the new stop.
   23 of 34 TP1 trades closed on the same candle that hit TP1. The backtest does not do this, so live winners were cut short.
   Fix: `broker.fresh_range`. Only new extremes count, plus the path from the previous close to the current close. On the
   entry candle, only the move from the entry price counts.
2. **Setups switched on with no sample.** Key Level Absorption was ON with 3 validation trades (test: 2 trades, both lost),
   then lost 6 of 7 live. Setups now need the same proof as other strategies (>= 30 validation trades, positive).
3. **Known-negative setups still traded.** Trades were taken at -0.33R and -0.52R expectancy because the skip only applied at
   <= -0.25R with n >= 50. Now any expectancy <= 0 with n >= 20 is skipped.
4. **Chasing.** Entries are re-anchored to the live price; a fill up to 0.35R worse was still taken. Now trades are skipped when
   price ran more than 0.15R past the signal close.

## Changes
* Evidence gate (`flowdesk/guard.py`, config `gate:`). The strategy needs validation >= 30 trades and > +0.02R, AND the
  untouched test >= 10 trades and > 0R; a strategy switched on by the regime check also passes. On the symbol it needs held-out
  >= 8 trades and >= +0.10R. Off on a symbol where it has >= 3 live trades averaging <= -0.5R. The whole strategy goes off once
  >= 15 trades after this fix average <= -0.25R.
  With rules v22 this leaves the Confluence engine on AUD/USD, Nasdaq and S&P only. Bitcoin is cut for losing live
  (-0.58R over 4); every other strategy and market is gated off. The bot will trade very little until something proves itself.
* Risk: 1.5-3% a trade (tiers 60%+ -> 3, 50%+ -> 2.5, else 2; 1.5% when the sample is small). Hard cap 3% per trade, open risk
  8%, same direction 6%, daily loss limit 6%, max 4 positions. Max cost 0.15R (was 0.20R).
