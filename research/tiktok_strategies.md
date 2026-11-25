# Strategies from the owner's TikTok videos

Seven videos were downloaded (yt-dlp), transcribed (Whisper) and read frame by frame. Only rules the video states are
used; everything the video leaves open is marked **unclear** and the choice made is listed under *assumed*.
FlowDesk is paper-only. All four implementable strategies are **off**: none has a positive result on data it was not tuned on.

Method (same as every other extra strategy): the live 15m scanner code (`flowdesk/strategies.py`), walk-forward on the
19-symbol watchlist (about 45 days of Yahoo 15m bars), exits simulated bar by bar (stop first when both are in one bar),
spread + slippage charged, one position per symbol. Fixed rules, nothing tuned. Time split per symbol: train 50% / validation 25% / test 25%.
A video strategy turns on only if validation AND the untouched test are both positive (>= 30 validation, >= 10 test trades).
The regime check can not switch them on. Raw results: `research/tiktok_native_5m.json` (5-minute chart check), Learning tab (15m).

| # | Video | Strategy | Trades | Win % | Exp R | Held-out (val+test) | State |
|---|-------|----------|-------:|------:|------:|---------------------|-------|
| 1 | victornqq "wicked" | none - P&L screenshots, no rules | - | - | - | - | not implementable |
| 2 | fluxcharts ORB | 15-min opening range breakout (`orb15`) | 638 | 34.8 | -0.12 | 106 trades, 36.8%, -0.04R | off |
| 3 | cam.nq1 "DOL Precision" | none - chart replay, no rules | - | - | - | - | not implementable |
| 4 | thequantbuilder bot that won 98.9% | martingale grid, no stop (a warning, not a strategy) | - | - | - | - | not implemented |
| 5 | itrades.capital first candle | First candle + FVG retest + engulfing (`fcr_fvg`) | 146 | 20.5 | -0.55 | 31 trades, 16.1%, -0.64R | off |
| 6 | thequantbuilder session momentum | First candle vs 12 EMA + trailing stop (`session_mom`) | 593 | 47.6 | -0.22 | 112 trades, 44.6%, -0.22R | off |
| 7 | keepssy OTE | ICT optimal trade entry 70.5% (`ote_fib`) | 538 | 26.2 | -0.25 | 101 trades, 26.7%, -0.11R | off |

## 1. victornqq - "@marketmaker #wicked #NQ"
12 s clip of GBP/USD and Micro Nasdaq trade screenshots with an anime voice-over. No entry, stop, target or filter is shown or said. Nothing to implement.

## 2. fluxcharts - Opening Range Breakout (`orb15`)
Stated: after the market opens, mark the high and low of the first 15 minutes. A candle **close** above the high = long, stop at the low of the range;
a close below the low = short, stop at the high; take profit at 2 x risk. (Claims 75% win rate over 100+ trades; the indicator's own panel shows 18 days, 70.59%.)
Unclear: which market's open (the demo is BTC/USDT and stocks), how long the entry stays valid, one trade per day or more, partial exits.
Assumed: New York cash open 09:30 ET (DST aware) on every instrument; first close beyond the range only, one trade per day, valid until 16:00 ET;
full exit at 2R (TP1 = TP2); trades whose range stop is under 0.4 or over 3 ATR are skipped (never moved).
15m chart: the first 15m bar IS the range, so this is exact. 5m check (range = first three 5m bars): 323 trades, 36.5%, -0.19R.

## 3. cam.nq1 - "DOL Precision"
15 s chart replay of a short on NQ with a stop above, a far target on a pink liquidity zone and a "going BE" caption; no voice-over, no rules stated.
Not enough to define entry, stop or target. Nothing implemented.

## 4. thequantbuilder - "This bot won 98.9% of the time"
A cautionary video: a bot that buys every drop, doubles the size each time and has no stop-loss won 98.9% of cycles, then lost $820,000 in one cycle
and was wiped out 14 times in 7 years of gold. The same bot without doubling still ended 99.9% green but $140,000 underwater. Their own NASDAQ system
"wins only 56.4%" but every trade has a stop (max drawdown 26.6% since 2019) - its rules are not given. Lesson used: a win rate is not an edge; FlowDesk
already ranks by expectancy and every trade has a stop. Martingale / no-stop grids are deliberately NOT implemented.

## 5. itrades.capital - First Candle Rule (`fcr_fvg`)
Stated: 09:30 ET, on the 5m chart wait for the first candle (09:30-09:35), mark its high and low. Drop to the 1m chart. Price must break a level and leave a
**fair value gap** (a gap between candle wicks, not just a wick or a close). Wait for price to **retest the gap**, then an **engulfing** candle: enter, fixed 3:1 risk-reward.
From the diagram: stop at the engulfing candle's far end, entry at its close.
Unclear: stop (read from the diagram), how long the setup lasts, what counts as engulfing, one trade per day.
Assumed: engulfing = body covers the previous opposite candle's body; gap dead if a close reclaims it; one trade per day; until 16:00 ET; stop-size skip as above.
Adaptation: the live scanner is 15m and Yahoo only gives 5 days of 1m bars, so the whole pattern runs on the 15m bars (first 15m bar = the "first candle"). 5m chart check: 139 trades, 24.5%, -0.48R.
Costs matter a lot here: stops of a few basis points make the spread a large part of 1R.

## 6. thequantbuilder - Session Momentum (`session_mom`)
Stated: wait for the New York open, watch one candle (the first five minutes). Closes above the 12 EMA = buy, below = sell. No fixed profit target: the winner runs and the stop follows the trend (trailing).
Claims 1,400+ trades, 57% win, +508% over 6 years (a frame shows "129 trades"; the numbers in the video disagree).
Unclear: EMA chart timeframe, initial stop, how the trail works.
Assumed: initial stop = first candle's far end; exit = FlowDesk's standard 1R partial + 1-ATR trail, TP2 at 8R (closest available to "let it run").
15m adaptation (first 15m bar vs the 15m 12 EMA). 5m chart check: 384 trades, 46.4%, -0.19R.

## 7. keepssy - ICT optimal trade entry (`ote_fib`)
Stated: price sweeps the sell-side liquidity under a low; displacement breaks structure and makes a new high; measure the move with the Fibonacci from the swing low to the new high;
62%-79% is the optimal trade entry with 70.5% the sweet spot; price pulls back and taps 70.5% = long; stop under the swing low; take profit at the buy-side liquidity above the high.
Unclear: what counts as a swept low / displacement / structure break, timeframe, limit vs market entry, the short side (only a long is shown).
Assumed: sweep = new low under the previous 10 bars; displacement = a bar with body >= 0.6 ATR closing above the highest high of those 10 bars; move >= 1 ATR; first pullback only;
the tap bar must trade to 70.5% and close inside the 62-79% zone; entered at that bar's close (market, not a limit at 70.5%); target = the high (needs >= 1R); mirrored for shorts; skipped when the stop is under 0.4 or over 3 ATR.
