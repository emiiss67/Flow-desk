# FlowDesk

**Paper-trading** order-flow + ICT bot for forex, indices and futures, with a cinematic web desk and Telegram control.
Modeled on the idea behind ProfitPro's *FlowPro Bot* for ATAS (trade surges in buying/selling pressure, volume spread,
absorption, high-volume nodes, psychological levels), combined with ICT concepts and economic-calendar awareness.

> **Paper only.** There is no live-broker code in this repository. Nothing here can place a real order.

## What it does

| Piece | What |
|---|---|
| `flowdesk/orderflow.py` | FlowPro-style order flow **estimated from OHLCV**: close-location delta (buy vs sell volume), pressure surges (`market_pressure` 300-900 = bar delta as % of average), volume spikes (`volume_spread` 2-4 = x average volume), aggressive vs passive (absorption) bars, bar-based volume profile (POC, VAH/VAL, HVN/LVN), round-number levels. Pluggable `OrderFlowProvider`. |
| `flowdesk/ict.py` | Swings, BOS / CHoCH, fair value gaps, order blocks, liquidity pools (PDH/PDL, Asia/London/NY highs & lows, equal highs/lows), liquidity sweeps, premium/discount, OTE (62-79%), killzones (NY time). |
| `flowdesk/events.py` | ForexFactory weekly calendar (`nfs.faireconomy.media`, cached 30 min) + RSS headlines (FXStreet, Investing.com, CNBC, MarketWatch), mapped to instruments by currency and keywords. High-impact events block new entries around release time. |
| `flowdesk/strategy.py` | Confluence scoring (0-100) for long vs short with plain-English reasons; structural SL (beyond sweep / OB / FVG / swing, clamped 0.6-3 ATR) and TP1/TP2 at opposing liquidity. `check()` is compute-only. |
| `flowdesk/publish.py` | When the cloudflared quick-tunnel URL changes, commits `docs/endpoint.json` (the URL only - never the desk key) with the deploy key. A saved desk that cannot reach its API reads that file and reconnects with the key it already has, so the desk link is pasted once per device. |
| `flowdesk/currency.py` | Account currency: converts size and P&L from each instrument's quote currency (USD for indices/futures/gold/oil/BTC, JPY/CHF/GBP… for crosses) to EUR with live FX from the data provider (10 min cache, last known rate as fallback; no rate = no entry). On first start it converts an old USD journal (trades, fills, balance, equity history) at each fill's own-time rate, after backing up the DB. |
| `flowdesk/strategies.py` | Six extra rule-based strategies computed causally on the bar close (ICT Silver Bullet, London/NY opening-range breakout, Asian range sweep reversal, VWAP deviation reversion, EMA trend pullback with order-flow confirmation, prior-day level break & retest) plus the entry features stored with every trade (session, killzone, HTF alignment, ATR regime, distance to prior-day levels, stop size, score). High-impact news windows block their entries. |
| `flowdesk/learning.py` | Nightly (02:00 UTC) and on-demand learning: splits every backtest trade by time per symbol into train 50% / validation 25% / test 25%, blocks feature buckets that lose in train AND validation (t-stat, sample minimums, max 12 new blocks per night), moves strategy settings at most one grid step when validation expectancy improves, enables extra strategies only with a positive validation edge, ranks strategies per symbol. Test results are only reported. Rules are versioned in `data/learned/` with rollback (desk Learning tab or `/api/learning/rollback`). |
| `flowdesk/broker.py` | Paper broker in the account currency (`broker.account_currency`, default **EUR**, €50 start), risk % per trade (10% = €5, configurable), fractional units/contracts, paper leverage cap (200x), optional min size / lot step, spread + slippage, TP1 partial (50%) then breakeven, ATR trailing, TP2, max positions, daily loss limit. Conservative fills (SL wins if SL and TP are in the same bar). |
| `flowdesk/journal.py`, `stats.py` | SQLite journal of every signal and trade; net, win rate, profit factor, max drawdown, equity curve, heatmap. |
| `flowdesk/bot.py` | Scanner loop over the watchlist + Telegram long-polling (answers **only** `FLOWDESK_TELEGRAM_CHAT_ID`). |
| `flowdesk/api.py` | FastAPI on `127.0.0.1:8790`, desk key required, CORS for `https://emiiss67.github.io`. |
| `flowdesk/tunnel.py` | cloudflared quick tunnel; when the URL changes it sends the owner `https://emiiss67.github.io/Flow-desk/#api=<tunnel>&key=<key>` on Telegram. |
| `docs/` | The desk (GitHub Pages from `main` / `docs`). Static HTML/CSS/JS, no build step. |

### Honest data notes
* **Order flow is estimated.** True footprint / bid-ask order flow needs a paid tick feed (e.g. Rithmic) and spot forex
  has no central order book. FlowDesk approximates it from candles and labels it *estimated* everywhere. Yahoo carries no
  forex volume, so for FX the bar range is used as an activity proxy (shown as `range proxy`).
* Default market data is **Yahoo Finance** (free). Futures/indices can be delayed 10-15 min. Optional **OANDA practice**
  prices are used automatically when `OANDA_API_KEY` and `OANDA_ACCOUNT_ID` are set (data only - no orders).
* If a provider fails, the API returns `"error": "data unavailable"` - it never invents numbers.
* News "tone" arrows are simple keyword matches, not a sentiment model.

## API
All endpoints need the desk key: header `X-Desk-Key: <key>` or `?key=<key>`. The key is generated on first run in
`data/desk_key.txt` (0600).

`GET /api/check?symbol=EURUSD=X&tf=15m` → `decision` (LONG / SHORT / NO TRADE), `confidence`, `levels` (entry, sl, tp1, tp2, rr1, rr2),
`reasons[]`, `against[]`, `warnings[]` (upcoming high-impact events), `headlines[]`, and `chart` (candles, estimated delta,
FVGs, order blocks, liquidity, sweeps, structure, volume profile, killzone boxes).

Also: `/api/dashboard`, `/api/positions`, `/api/signals`, `/api/journal`, `/api/performance`, `/api/calendar`, `/api/news`,
`/api/instruments?q=&category=`, `/api/chart?symbol=&tf=`, `/health` (no key).

Timeframes: `1m 5m 15m 30m 1h 4h 1d`. Symbols: anything Yahoo knows (`EURUSD=X`, `NQ=F`, `^GDAXI`, `GC=F`, `BTC-USD`, `AAPL`…);
shortcuts like `EURUSD`, `NQ`, `XAUUSD`, `US100`, `DAX` are normalised.

## Telegram
`/check SYMBOL [tf]`, `/positions`, `/pnl`, `/pause`, `/resume`, `/close SYMBOL`, `/watchlist`, `/news`, `/calendar`, `/status`, `/desk`.
Alerts: paper entries/exits, and high-impact events 30 min ahead for watched instruments.

Find your chat id after pressing **Start** on the bot:
```
venv/bin/python scripts/discover_chat_id.py --write      # stores FLOWDESK_TELEGRAM_CHAT_ID in .env
```

## Install (Debian VM, user `grokbot`)
```
git clone https://github.com/emiiss67/Flow-desk.git && cd Flow-desk
bash deploy/install.sh            # venv + deps + systemd units into /home/grokbot/flowdesk
nano /home/grokbot/flowdesk/.env  # FLOWDESK_TELEGRAM_TOKEN, FLOWDESK_TELEGRAM_CHAT_ID
sudo systemctl enable --now flowdesk-api flowdesk-bot flowdesk-tunnel
```
Settings live in `config.yaml` (watchlist, FlowPro thresholds, risk, event blackout windows). Secrets only in `.env`
(never committed).

## Local dev
```
python3 -m venv venv && venv/bin/pip install -r requirements.txt
venv/bin/python -m pytest -q            # unit tests + live Yahoo smoke test (skips offline)
venv/bin/python -m flowdesk.api         # API on 127.0.0.1:8790
cd docs && python3 -m http.server 8000  # desk; open http://127.0.0.1:8000/#api=http://127.0.0.1:8790&key=<data/desk_key.txt>
```
Settings → Colours has palettes (Neon, Gold, Ice blue, Purple, Monochrome, Matrix) plus custom long/short/accent/panel colours, opacity and glow, saved in the browser.

Without an API the desk runs in **DEMO** mode with sample data and a clear "DEMO - sample data" banner.

## Credits
* Background photographs (docs/assets/bg/): The Metropolitan Museum of Art, Open Access, **CC0 / public domain**.
  All are recoloured, cropped and composited for FlowDesk (tint, vignette, grain; the light versions are cut out onto a
  pale studio backdrop). "Ascend" and "Order flow" backgrounds are generated in-browser.

  | File | Theme | Met object | Image |
  |---|---|---|---|
  | bust-augustus.jpg | Neon (green eye glow added) | [Marble portrait of the emperor Augustus](https://www.metmuseum.org/art/collection/search/247993) (#247993) | DP337225 |
  | bust-antinoos.jpg | Neon | [Marble portrait head of Antinoos](https://www.metmuseum.org/art/collection/search/257825) (#257825) | DP333685 |
  | bust-antoninus-gold.jpg | Gold & Bronze | [Marble portrait bust of Antoninus Pius](https://www.metmuseum.org/art/collection/search/246984) (#246984) | DP338125 |
  | bust-verus-crimson.jpg | Crimson | [Marble portrait of the co-emperor Lucius Verus](https://www.metmuseum.org/art/collection/search/248783) (#248783) | DP337237 |
  | bust-antinoos-ocean.jpg | Ocean | [Marble portrait head of Antinoos](https://www.metmuseum.org/art/collection/search/257825) (#257825) | DP333683 |
  | bust-bronze-emerald.jpg | Emerald | [Bronze portrait of a man](https://www.metmuseum.org/art/collection/search/248892) (#248892) | DP337268 |
  | bust-herodotos.jpg | Gold / Emerald scenes | [Marble bust of Herodotos](https://www.metmuseum.org/art/collection/search/245829) (#245829) | DP328506 |
  | bust-severus.jpg | Neon / Crimson / Ocean scenes | [Marble portrait bust of Severus Alexander](https://www.metmuseum.org/art/collection/search/258540) (#258540) | DP345023 |
  | statue-warrior.jpg | Gold / Crimson / Ocean scenes | [Marble statue of a wounded warrior](https://www.metmuseum.org/art/collection/search/251929) (#251929) | DP-39853-001 |
  | marble-woman-light.jpg | White Marble (light) | [Portrait head of a woman](https://www.metmuseum.org/art/collection/search/246997) (#246997) | DP333728 |
  | marble-herodotos-light.jpg | White Marble (light) | [Marble bust of Herodotos](https://www.metmuseum.org/art/collection/search/245829) (#245829) | DP328506 |
* Charts: [TradingView Lightweight Charts](https://www.tradingview.com/lightweight-charts/) v4.2 (Apache-2.0), vendored in `docs/js`.
* Fonts: Inter, Playfair Display, JetBrains Mono (Google Fonts, OFL).
* Concept inspiration: ProfitPro Trading's FlowPro bot for ATAS. FlowDesk is an independent implementation and is not affiliated.

Not financial advice. Paper trading only.
