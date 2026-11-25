# Strategies from the owner's TikTok videos

Seven videos were downloaded (yt-dlp), transcribed (Whisper) and read frame by frame. Only rules the video states are
used; everything the video leaves open is marked **unclear** and the choice made is listed under *assumed*.
FlowDesk is paper-only. All implementable strategies are **off**: none has a positive result on data it was not tuned on.

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
| 8 | "wicked's trading model" (3 screenshots) | LVN ledge 3-step: TPO bias + SMT + LVN (`lvn_ledge`) | 26 | 11.5 | -0.69 | 4 trades, 0%, -1.15R | off (every symbol) |
| 8b | same, NY-open aggressive | LVN ledge at 09:30-10:30 ET, no SMT (`lvn_ledge_open`) | 2 | 50.0 | +0.52 | 1 trade, 100%, +2.05R | off (every symbol) |

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

## 8. "wicked's trading model" - LVN ledge 3-step (`lvn_ledge`, `lvn_ledge_open`) - added 25 Nov 2026
Source: three screenshots of a notes doc (not a video). Stated:
* 1-minute chart, **Session Volume Profile 6PM-6PM New York** (a full daily profile).
* Mark **LVNs ("ledges")**. Filter them: they should **line up with LVNs of other session profiles**; avoid LVNs that **push straight
  into a POC**; drop any LVN price has **clearly consolidated through**. Keep only clean, respected levels.
* **Single prints** are mainly **targets**, and help with bias (especially ones respected overnight).
* **3-step model: single print + ISMT/SMT + LVN** = high-quality setup. ISMT = a simple SMT between two candles; classic SMT between
  correlated markets also works.
* **Aggressive ledge trades** around the 09:30 NY open, where ledges are respected well.
* **Bias from the 30-minute TPO**: stronger acceptance in the upper half = bullish, lower half = bearish; LVNs are for entries, not bias.
  Order: bias first, then the LVN entry, single prints as targets.

Unclear: exact LVN / single-print definitions, how close "aligned" is, what "consolidated through" means, the stop, entry trigger,
which TPO (current or previous session), trading hours, one trade per level or more.

Assumed (code: `flowdesk/ledge.py` + `_lvn_ledge` in `flowdesk/strategies.py`; all causal, tested in `tests/test_lvn_ledge.py`):
* Profiles: each completed 18:00-18:00 NY session (80 price bins) + **the current session's developing profile** (bars before the current
  30-minute period, used once it has 4 hours). Each bar's volume is spread evenly over its high-low.
* LVN = local minimum of the 3-bin-smoothed profile at <= 35% of the POC with a node >= 2x on both sides. Kept only if it lies within
  2.5 bins of an LVN of a **different** profile (developing or one of the last three sessions); dropped once 4+ bars this session have
  straddled it (consolidated through).
* "Pushes straight into a POC": skipped if the previous session's or the developing POC lies between entry and 1R in the trade direction.
* Single prints = runs of 2+ bins touched by exactly one 30-minute TPO period (last two sessions + developing). Target = the nearest
  single print at least 1R away; if none, 2R. Full exit at the target (no partial).
* Bias = current session's 30-min TPO so far: share of TPO range in the upper half of the session range; >= 0.55 long only, <= 0.45 short only, needs 2 h of TPO.
* Entry (closed 15m bar, 03:00-16:00 NY): the bar trades into a ledge from the bias side (wick within -0.5/+0.25 ATR of it) and
  **closes back on the bias side**, with an SMT on this bar or the two before: **ISMT** = the newer candle's wick takes the older
  candle's low (high) while its body low (high) holds, closing green (red); or **classic SMT** = a new 5-bar low (high) that the
  correlated market does not make (NQ/ES, YM/ES, RTY/ES, EUR/USD-GBP/USD, AUD/USD-NZD/USD, EUR/JPY-GBP/JPY; others ISMT only).
  Stop = beyond the sweep low/high and the ledge, at least 0.5 ATR (the doc gives no stop); skipped if over 3 ATR.
* Aggressive variant `lvn_ledge_open`: 09:30-10:30 NY only, bias + ledge tap + a rejection candle (green/red, closing in the far half), no SMT.
* Switch-on rule (stricter than other strategies, `per_symbol`): **on only for a symbol whose validation AND untouched test are both
  positive** with >= 10 validation and >= 8 test trades on that symbol; blocked on every other symbol. Off until then, but the 04:00
  learning loop re-tests it every night (fixed rules, never tuned, never switched on by the regime check).

**Approximations (honest caveats):**
* **No 1-minute history**: Yahoo keeps 1m bars for only ~5 days, so the model runs on 15m bars (the live scanner's chart); a 5m check was also run.
  Wicks, ISMT and ledge taps on 15m are much coarser than on 1m.
* **Forex has no volume on Yahoo**: FX "volume profiles" are time-at-price (TPO-style) profiles, every bar weighted equally.
  Futures use Yahoo's exchange volume per 15m bar (not tick-level, futures data ~10 min delayed). BTC uses Yahoo's volume.
* Profiles are built from bar ranges (volume spread evenly over high-low), not from real traded prices - LVNs are estimates.
* Short history (~45-60 days) -> few setups. The held-out window is the learning loop's: 14-20 Nov (validation) and 20-25 Nov (test).

**Results** (`tools/ledge_check.py`, raw numbers in `research/lvn_ledge_check.json`; spread + slippage charged, live quality gate applied):

| Variant | Chart | All trades | Train (before 14 Nov) | Validation (14-20 Nov) | Test (20-25 Nov) |
|---|---|---|---|---|---|
| `lvn_ledge` | 15m | 26, 11.5% win, -0.69R | 22, 13.6%, -0.60R | 1, 0%, -1.16R | 3, 0%, -1.15R |
| `lvn_ledge_open` | 15m | 2, 50%, +0.52R | 1, 0%, -1.02R | 1 (crude oil), 100%, +2.05R | 0 |
| `lvn_ledge` | 5m | 7, 0% | 1, 0% | 5, 0%, -1.13R | 1, 0%, -1.19R |
| `lvn_ledge_open` | 5m | 5, 20% | 1, 100%, +2.35R | 4, 0%, -1.13R | 0 |

Per symbol (15m held-out = validation + test): EUR/USD 1 trade -1.19R; GBP/JPY 1, -1.15R; Nasdaq 1, -1.10R; S&P 1, -1.16R; crude oil (open variant) 1, +2.05R;
every other symbol 0 held-out trades. **No symbol comes close to the switch-on rule** (needs >= 10 validation + >= 8 test trades, both positive).
Before costs and the quality gate the 15m model took 84 trades at 20% win, **-0.17R gross** (-0.56R after costs): the setup itself
lost money here, it is not only the spread. Of 117 raw 15m signals, 76 were skipped because spread + slippage would cost > 0.20R
(ledge stops are tight) and 7 for low volatility; 34 passed (overlapping trades on one symbol are then skipped -> 26).
Verdict: **off on every symbol**, tracked nightly by the learning loop; it switches on by itself for a symbol only if it earns it there.
