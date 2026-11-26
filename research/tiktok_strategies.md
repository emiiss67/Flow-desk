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
| 9 | OTE PDF (owner's photos; same PDF as the account's "akram explains OTE" post) | OTE golden zone, major leg (`ote_major`) | 275 | 41.1 | -0.04 | val 35, 42.9%, +0.09R / test 34, 38.2%, -0.10R | off (every symbol) |
| 9b | same, internal leg | OTE golden zone, internal leg + rejection candle (`ote_internal`) | 35 | 48.6 | +0.09 | val 6, 66.7%, +0.56R / test 6, 16.7%, -0.64R | off (every symbol) |
| 10 | resellingleague - Powell / Dodgy | Data high / low, 08:30 ET candle (`data_hl`) | 46 | 19.6 | -0.67 | val 3, 66.7%, +0.45R / test 1, 0%, -1.14R | off (every symbol) |
| 11 | resellingleague - Powell | 10 AM key open (`ko10`) | 18 | 55.6 | -0.15 | val 0 / test 1, 100%, +0.87R | off (every symbol) |
| 12 | resellingleague - Powell | Rejection block, wick 50% (`rej_block`) | 41 | 41.5 | -0.40 | val 6, 66.7%, +0.27R / test 3, 0%, -1.10R | off (every symbol) |
| 13 | resellingleague - PB | Mech model, inversion FVG (`pb_mech`) | 114 | 34.2 | -0.23 | val 15, 40.0%, -0.12R / test 9, 33.3%, -0.39R | off (every symbol) |
| 14 | resellingleague - Dutch / Wicked | Std deviations of the London leg (`stdv_london`) | 3 | 0.0 | -1.16 | val 0 / test 1, 0%, -1.10R | off (every symbol) |
| 15 | resellingleague - Aval | Sweep + change in state of delivery (`cisd`) | 388 | 32.0 | -0.19 | val 45, 31.1%, -0.24R / test 52, 32.7%, -0.22R | off (every symbol) |
| 16 | evankrutchikk - "How I trade to have a 90% win rate" (TTP, time then price) | none - no entry/stop/target rules; it is the time-window idea already covered by #2, #10, #11, #14 | - | - | - | - | not implementable (duplicate idea, re-checked) |
| 17 | thequantbuilder - "learn one strategy" (26 Nov) | Same model as #6 with the missing rules: first 09:30 ET candle vs 12 EMA, stop 8 ATR, trailing stop (`session_mom_wide`) | 419 | 83.8 | -0.03 | val 56, 83.9%, -0.00R / test 31, 71.0%, -0.16R | off (every symbol) |

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


## Batch 2 (25 Nov 2026): the OTE PDF + the @resellingleague account

Columns 9-15 in the table above: "Trades / Win % / Exp R" = the TRAIN segment, then validation and the untouched test separately.
Same method as above (live 15m scanner code, `learning.simulate_strategy`: spread + slippage, the live quality gate - costs <= 0.20R,
no quiet markets - one position per symbol, per-symbol time split train 50% / validation 25% / test 25%). Numbers are from the server's own
data on 25 Nov 2026 (`tools/strategy_eval.py`, raw output `research/batch2_check.json`). The validation and test windows are only about
four trading days each (the replay period of the cached walk-forward), so samples are small. All are fixed rules (never tuned), never
regime-switched, and `per_symbol`: the learning loop switches one on only for a symbol where validation (>= 10 trades) AND the test (>= 8)
are both positive on that symbol. **Result: no symbol qualifies for any of them, so all are off but tracked** (the nightly 04:00 cycle
re-checks them on fresh data every night).

### 9. OTE (optimal trade entry) - the 18-page PDF (`ote_major`, `ote_internal`)
Stated: Fibonacci 0 / 0.5 / 0.62 / 0.7 / 0.78 / 1; the 0.62-0.78 "golden zone" is the entry; long = fib from the swing low (1) to the
swing high (0), wait for the retrace into the zone; short mirrored; above 0.5 premium, below discount. Usually drawn on the big move
(highest to lowest point), internal legs also work. Target = opposing liquidity (the 0 level or beyond). Examples put the stop just
beyond 0.78 or near the 1. Needs extra confirmation, never a sure thing.
Assumed: *major leg* = lowest low -> highest high of the last 64 closed 15m bars (16 h), low first, >= 3 ATR, the 0 at least 3 bars old;
*internal leg* = newest confirmed 2-bar fractal swing high and the lowest low since the swing high before it, >= 1.5 ATR. Entry = close
of the first bar that trades into the zone (<= 0.62) without breaking the 1, closing between 0.78 and the 0. Target = the 0 level (needs >= 1R).
Variants (12): leg {major, internal} x stop {beyond 0.78 by 0.1 ATR, at the 1 level} x filter {none, 50/200 EMA trend, rejection candle
closing back above 0.62}. **The variant was picked on TRAIN only** (best train expectancy with >= 30 trades), never on held-out data:
major -> stop at the 1, no filter (train -0.04R / 275 - every major variant lost in training); internal -> stop beyond 0.78 + rejection
candle (train +0.09R / 35). Train results of all 12 are in `research/batch2_check.json` (several look good on validation alone - e.g.
major + trend +0.62R over 24 - but all of them lose on the untouched test, so picking them would have been curve-fitting).
**Nasdaq (NQ=F) on its own** (the PDF's examples are NQ): `ote_major` train 17 trades, 41.2%, +0.17R; validation 1 trade (loss, -1.04R);
test 1 trade (win, +2.41R). `ote_internal` train 5, 60%, +0.35R; validation 1 (win, +0.96R); test none. Best-looking NQ variant in training was
major + trend filter (9 trades, 55.6%, +0.61R) - same 1 loss / 1 win out of sample. Nasdaq looks positive in training but has only 1-2
out-of-sample trades, far below the 10 validation / 8 test needed, so it stays off on NQ too. (ES: `ote_major` train 15, 46.7%, +0.03R; 1 + 2 held-out trades.)
The account's "akram explains OTE in PDF" post is this same PDF; Powell's "fib levels and OTE" clip (0.62 / 0.79, enter at the level,
target the high) is the same idea. The older `ote_fib` (keepssy, 70.5%) stays as it was.

### The @resellingleague account
60 newest posts listed (yt-dlp), 59 downloaded (one blocked for this IP), audio transcribed (faster-whisper base.en), photo posts read
image by image. It reposts clips from paid "ICT"-style Discord courses (Powell, Dodgy, PB, Aval, Arctic, Hunnyu, Dutch, Wicked, LIT, Fearing,
luc tran, MMXM, Casper, Salman). Most clips are discretionary chart replays; the concrete models were built:

| Model (source clips) | Built as | Why / why not |
|---|---|---|
| Data high / low (Powell "data high and low", Dodgy "one setup for life") | `data_hl` | concrete: 08:30 candle high/low, first side taken, opposite close, target the other side |
| 10 AM key open + rejection block (Powell "10 AM KO") | `ko10` | concrete enough: sweep into 10:00, return to the 10:00 open, stop < 20 pts, break-even then runner |
| Rejection block / wick CE (Powell "rejection wicks", "wick theory", "entry triggers"; Aval 583 s) | `rej_block` | concrete: wick that swept liquidity, enter at the wick's 50%, stop beyond the wick |
| PB Mech model (PB "Mech Model", 30 min) | `pb_mech` | concrete: inversion of the leg's highest-timeframe FVG, target an unfilled 5/15m gap, stop at the swing |
| Standard deviations / last London leg (Dutch course, Wicked "stdv") | `stdv_london` | concrete: last London leg wick to wick, negative SDs, reversals in the -2 to -4 zone |
| Sweep + CISD toward the draw on liquidity (Aval 57 min + 2 min) | `cisd` | concrete: sweep, close through the open of the delivery run, target relative equal highs/lows |
| OTE PDF (akram) / Powell fib + OTE | `ote_major`, `ote_internal` | = part 9 |
| "Wicked's trading model" (3 screenshots) | `lvn_ledge` (separate job) | duplicate - already built |
| Dodgy 30-second model | not built | needs a 30-second chart and fixed 10/12-point stop/target; meaningless on 15m bars |
| SMT divergence (Aval 2 min, Hunnyu "anticipating SMT", Arctic) | not built standalone | needs a second instrument inside the entry rule; already part of `lvn_ledge` (ISMT + correlated SMT) |
| Powell gap fills / new week + new day opening gaps | not built | levels and bias ("treat it as a key open", "free bias"), no entry/stop rule |
| Time / killzones (Dodgy "uses time", Salman macros 09:45-10:15 etc.) | not built | a time filter, not an entry model (FlowDesk already records the killzone of every trade) |
| Arctic PO3 / AMD, structure, liquidity, news; MMXM failure swings; Casper SMC structure; LIT inducement cycle; Fearing narrative; Powell top-down analysis and trade recaps | not built | discretionary narrative / bias, no fixed entry, stop or target |
| luc tran | not built | risk-management talk (3:1 R:R), no entry |
| 8 photo posts | not built | adverts for a paid Discord ("all for $47"), no content |
| music-only clips (pb 16 s, arctic pdf 7 s) | not built | screen recordings of course folders |

Rules as built (15m bars, entry at the close of a finished candle, everything from bars <= the entry bar):
* **`data_hl`**: the 08:30-08:45 ET candle must be >= 1 ATR (FlowDesk has no calendar history, so a big 08:30 candle stands in for a news print).
  The first side taken out (both in one bar = no trade); then the first candle closing back inside in the other direction (bearish close below the
  high / bullish above the low) = entry, stop = the sweep extreme, target = the opposing side of the data candle (>= 1R). Valid 08:45-11:00 ET.
  *Unclear*: 1-minute entry on the rejection block (here the 15m close), CPI / NFP use 5m. *Assumed*: as stated.
* **`ko10`**: pre-market = 04:00-09:30 ET. If 09:30-10:00 takes the pre-market high (only one side) = buy-side manipulation -> short bias (mirror for the low).
  After 10:00 a close >= 0.5 ATR away from the 10:00 open, then the first return to the 10:00 open that closes back on the bias side = entry;
  stop = the 09:30+ extreme; 1R partial (the video moves to break-even there) and a 3R runner. Until 12:00 ET, no Mondays ("I don't trade Mondays").
  *Unclear*: the 4h-wick "sufficient manipulation" test and the 1-minute entry trigger.
* **`rej_block`**: a candle (last 30 bars) with range >= 1.2 ATR, a wick >= half its range that took the 20-bar high (low). Price must have left by >= 1 ATR
  beyond its body; the first return to the wick's 50% (CE) that closes back below (above) it = entry; stop 0.05 ATR beyond the wick; 1R partial, 3R runner.
* **`pb_mech`**: swing low of the last 20 bars that took the 10 bars before it (liquidity); the largest bearish FVG (>= 0.2 ATR) of the leg into it
  (the 1-5m "highest timeframe gap" becomes the largest 15m gap); the first close above it = entry; stop 0.05 ATR under the swing low; target = the nearest
  unfilled bearish FVG above (last 24 h, never traded back to its top), must be >= 1R; mirrored. *Not used*: "don't trade against SMT" (second instrument),
  the HTF key-level rejection (the swept swing stands in for it).
* **`stdv_london`**: last London leg = high/low of 04:30-05:30 ET (wick to wick), 0.5-3 ATR; bullish if the low came first (drawn bottom -> top), extensions
  above it (mirror for bearish). 07:00-12:00 ET: the first candle reaching -2 SD (2 leg lengths beyond the leg) but not past -4 that closes against the move
  = entry, stop 0.1 ATR beyond that candle, target = the leg's end (0). No trade once the leg's other side broke. Price rarely gets there (3 trades in 7 weeks).
* **`cisd`**: within the last 6 bars a bar took the 20-bar high and is still the high; the run of up-close candles that made it; the first close below the
  open of that run (change in state of delivery) = short, stop 0.05 ATR above the sweep high, target = the 20-bar low before the sweep (draw on liquidity,
  >= 1R); mirrored; 02:00-16:00 ET.

## 16. evankrutchikk - "How I trade to have a 90% win rate" (TTP model: Time Then Price) - 26 Nov
74 s talking-head clip (yt-dlp, Whisper, 25 frames; the only chart shown is a single 1-min NQ screenshot with the 08:30 candle and a -2.5 std-dev level, no rules). What it says, in full: the model is built on **time** - he does not trade all day, only fixed time windows that show good price action; in a window price either runs to a liquidity target (continuation) or manipulates (reversal); he works on the **1-minute chart only**, no daily/4h/1h PD arrays; he trades "his own model" (not IFVG), "catches a trade almost every day", claims 90% win rate. **No entry trigger, stop, target, window times or filter are given** ("not giving away too much sauce"). The win-rate claim is unverifiable.
Result: **not implementable** - nothing to code without inventing the rules. The only concrete hints (a time window such as the 08:30 candle, a std-dev extension, continuation vs reversal at liquidity) are already built and tested as `data_hl` (08:30 ET data high/low), `ko10` (10 AM key open), `stdv_london` (std deviations of the London leg), `orb15` (opening range) and `sweep+CISD`. Re-check of that family (research/batch2_check.json, tiktok_native_5m.json): all off on every symbol. Nasdaq (NQ): `data_hl` 3 trades in train (33%, -0.19R), none held-out; `ko10` 3 train trades (33%, -0.61R), none held-out; `stdv_london` 0 trades. Too few trades to judge, and the evidence gate (guard.py: validation >= 30 and test >= 10 trades, positive; per-symbol +0.10R over 8+ trades) stays closed. Real 1-min data would be needed to test the "1-minute, time-window" claim properly; we only have 15m bars (about 45 days).
No code change; risk, end-of-day flat and open trades untouched. The model is not added to the strategy table.

## 17. thequantbuilder - "If I had to start from zero again, I'd learn one strategy" (`session_mom_wide`) - 26 Nov
68 s animated explainer (yt-dlp, Whisper, 23 frames read). **Same model as #6 (`session_mom`)**, this time with the numbers #6 left open. Stated: at the 09:30 ET New York open look at **only the first 5-minute candle**; closes **above the fast (12) moving average = long, below = short**. **Stop far away - the slide says 8 x ATR** - so normal noise does not stop it out. If the trade runs the **stop follows** (trailing); if the trend holds you stay in, **sometimes for days**. Risk 1% per trade. Claims (unverifiable): since 2019, 1,792 trades, +505.8%, 56% winners, last week 5 of 5.
New vs #6: the 8-ATR initial stop and the multi-day hold. Still unclear: which ATR period / chart, how the trail is computed. Assumed: 12 EMA and ATR of FlowDesk's 15m chart (first 15m candle of the NY session, entry at its close); exit = FlowDesk's standard management: half off at 1 ATR (= 0.125R on an 8-ATR stop), stop to breakeven then trailing 1 ATR, rest to 8 ATR (= 1R). **The multi-day hold cannot be tested or traded**: the bot's end-of-day flat closes everything before the 17:00 ET close, and FlowDesk has no multi-day exit. Only the intraday part is covered (an intraday-only run with max hold 28 bars is included). A fixed variant, picked before any result (no tuning). `max_sl_atr: 8` lifts the 3-ATR stop cap for this strategy only.
Result (fresh run, live quality filters + costs, 45 days of 15m bars, 19 symbols, train/validation/test = 50/25/25 per symbol; `research/session_mom_wide_check.json`, `tools/smw_check.py`):

| Run | Train | Validation | Test | Held-out |
|-----|-------|------------|------|----------|
| `session_mom_wide`, 24 h max hold | 332, 84.9%, -0.02R | 56, 83.9%, -0.00R | 31, 71.0%, -0.16R | 87, 79.3%, -0.06R |
| same, intraday only (28 bars) | 334, 76.3%, +0.01R | 59, 83.1%, +0.02R | 31, 61.3%, -0.13R | 90, 75.6%, -0.03R |
| `session_mom` (#6 exit), same data/filters | 169, 54.4%, +0.01R | 28, 53.6%, +0.14R | 24, 33.3%, -0.36R | 52, 44.2%, -0.09R |

Nasdaq (NQ=F), `session_mom_wide`: train 15 trades, 86.7%, +0.005R; validation 3, 33.3%, -0.66R; test 1, 100%, +0.06R. (Intraday-only: val 3, 33.3%, -0.53R / test 1, 100%, +0.06R.) Far too few Nasdaq trades (one NY open per day, 45 days) to judge. For comparison S&P (ES=F) val 3, 100%, +0.29R / test 1, 0%, -1.01R; Dow (YM=F) val 2 / test 3, all winners, +0.10R / +0.11R (5 held-out trades, below the 8 the symbol gate needs).
Why it wins often but earns nothing: the stop is 8x the target distance, so a 1 ATR partial plus a 1 ATR trail makes ~80% winners that each pay a few hundredths of an R, and one stop-out (-1R) wipes out ~15-20 of them; after costs the edge is about zero. The video's edge (if real) comes from holding winners for days, which this bot does not do. The test segment is negative on both runs.
Gate: strategy level fails (test is negative: -0.16R / -0.13R), no symbol reaches +0.10R over 8+ held-out trades -> **off on every symbol**, tracked (re-tested nightly; switches on per symbol only through guard.py). #6 `session_mom` re-checked: also negative on test (-0.36R) and off. Note: #6's table row (593 trades) was measured before the live quality/cost filters; the numbers above use today's filters, so counts are lower.
Risk, end-of-day flat and open trades untouched.
