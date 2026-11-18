# FlowDesk

Paper-only desk for forex, indices, and futures. It reads pressure from candles (an order-flow **estimate**, not a footprint), combines that with ICT-style structure, and stands down around high-impact calendar events. Nothing in this repo sends a broker order.

The desk in `/docs` is a static site for GitHub Pages. The API, scanner, and Telegram bot run on a Linux VM and stay on `127.0.0.1` until you put a Cloudflare quick tunnel in front.

## What a check is

`GET` or `POST /api/check` returns `LONG`, `SHORT`, or `NO TRADE`. It does **not** open a paper trade. The scanner does that, on its own loop, and only inside the paper ledger.

Confidence is a weighted confluence score from 0 to 92. It is not a probability. A call needs the score in `config.yaml` (`min_score`, default 55) and a clear calendar.

Levels come from the candles that were actually fetched:

- stop: under a sweep wick, swing, or order block when one sits between 0.15 and 3 ATR, otherwise 1.2 ATR, then clamped to 0.4–2.8 ATR
- TP1: opposing liquidity inside 0.8R–2.4R, otherwise 1.5R
- TP2: the next liquidity level, otherwise 2.5R

The plain-English reasons name the structure that produced them.

## Honest data limits

| Input | What FlowDesk actually has |
| --- | --- |
| Order flow | Candle delta, volume vs its average, wick absorption, and a bar-volume POC/HVN. Labeled **estimate**. If the feed has no volume (common on Yahoo forex), the UI says **data unavailable**. |
| Market data | Yahoo Finance by default. Futures are often delayed about 10–15 minutes. The payload names the source and the delay. |
| OANDA | Practice host only (`api-fxpractice.oanda.com`), and only when **both** `OANDA_API_KEY` and `OANDA_ACCOUNT_ID` are set. Candles and account summary. No order routes exist in the code. |
| Calendar | Forex Factory weekly JSON, cached. A failed fetch with no cache is **data unavailable**, and the scanner will not open a new paper trade until the calendar can be read. |
| News | RSS (ForexLive, FXStreet, CNBC). Headlines are scored against the instrument with keywords. A dead feed is **data unavailable**, not a made-up story. |

If a provider fails, the API returns `{"error": "data unavailable"}`. The desk shows that sentence. It does not fill in zeros.

## Layout

```
flowdesk/           strategy, paper broker, API, Telegram, tunnel watcher
config.yaml         watchlist, risk, blackout — no secrets
docs/               GitHub Pages desk (HTML, CSS, vanilla JS)
deploy/             systemd units and the tunnel helper
tests/              scoring, levels, paper SL/TP, read-only check
```

## Local run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
pytest
python -m flowdesk.server
```

The API binds to `127.0.0.1:8787`. The first start writes `data/desk.key` (mode `0600`).

Open the desk without an API and it stays in demo mode, with a banner: **DEMO – sample data**. Sample figures are layout only.

To point the desk at your API, open:

```
http://127.0.0.1:8080/#api=http://127.0.0.1:8787&key=THE_KEY
```

Serve `docs/` with any static server (`python -m http.server 8080` from `docs/`). The hash is stored in `localStorage`. Trading settings are not edited in the browser. Change them in `config.yaml` or by Telegram.

`config.yaml` `server.cors_origins` includes `https://emiiss67.github.io` and local preview origins.

## Paper account

Defaults in `config.yaml`:

- 10,000 USD
- 1% of balance risked at the stop, **including** stop slippage
- 3 concurrent positions, one per symbol
- 3% daily loss limit. New entries stop. Open stops still run.
- Spread and slippage come from `flowdesk/catalog.json`
- Half the position is closed at TP1 and the stop moves to the fill. The rest is aimed at TP2.
- A trailing stop (`trail_atr_mult` × ATR) only ratchets in the favorable direction.
- If a stop and a target are both touched in one bar, the stop is filled.

`/pause` stops new entries. It does not freeze stops.

## Telegram

Set `FLOWDESK_TELEGRAM_TOKEN`. Lock the chat before anyone else talks to the bot:

```bash
python -m flowdesk.discover_chat --save
```

or send `/start` once while `FLOWDESK_TELEGRAM_CHAT_ID` is empty. The first chat id is written to `data/telegram_chat_id`. Every other chat is ignored.

Commands: `/check SYMBOL [tf]`, `/positions`, `/pnl`, `/pause`, `/resume`, `/close SYMBOL`, `/watchlist`, `/news`, `/calendar`, `/status`.

The bot process is also the scanner. It journals every pass and, when `auto_trade` is true, opens paper trades. Alerts are entries, exits, and high-impact events inside `event_alert_minutes` for the watchlist.

## API

All `/api/*` routes require the desk key as `X-FlowDesk-Key` or `?key=`. The only write is `/api/check`, and that write is a journal row, not a fill.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/` | Public liveness ping. No account data. |
| GET | `/api/health` | Paper flag, pause, provider. |
| GET | `/api/status` | Risk settings, last scan, optional OANDA practice summary. |
| GET | `/api/dashboard` | Balance, daily loss, streak, last trades. |
| GET | `/api/positions` | Open paper positions and open P&L. |
| GET | `/api/signals` | Recent check and scanner rows. |
| GET | `/api/journal` | Signals plus the paper trade when one was opened. |
| GET | `/api/performance` | Net, win rate, profit factor, drawdown, equity, weekday grid. |
| GET | `/api/calendar` | This week's events, or `data unavailable`. |
| GET | `/api/news` | Headlines scored against the catalog, or `data unavailable`. |
| GET | `/api/watchlist` | Configured symbols. |
| GET | `/api/instruments?q=&category=` | Search the catalog. |
| GET | `/api/candles?symbol=&timeframe=` | Closed candles. |
| GET | `/api/chart?symbol=&timeframe=` | Candles plus FVG, order block, liquidity, POC overlays. |
| GET, POST | `/api/check?symbol=&timeframe=` | The call. Does not place a trade. |

Timeframes: `M5`, `M15`, `M30`, `H1`, `H4`, `D1`.

CORS allows `https://emiiss67.github.io`.

## GitHub Pages

Repo `emiiss67/Flow-desk`, Pages source **main** / **docs**. The public desk is:

`https://emiiss67.github.io/Flow-desk/`

Leave it on demo until a tunnel URL exists. The private link the tunnel sends is:

`https://emiiss67.github.io/Flow-desk/#api=<tunnel>&key=<key>`

## VM install

On a Debian machine, as root, from this repo:

```bash
sudo ./install.sh
```

That creates user `grokbot`, a venv at `/home/grokbot/flowdesk`, and three systemd units:

- `flowdesk-api` — `python -m flowdesk.server` on `127.0.0.1:8787`
- `flowdesk-bot` — scanner and Telegram long-poll
- `flowdesk-tunnel` — `cloudflared tunnel --url http://127.0.0.1:8787` plus `python -m flowdesk.tunnel`

When the `trycloudflare.com` host changes, the watcher sends the owner the desk link on Telegram. The URL is also in `data/tunnel_url.txt`. Quick tunnels change on restart. This is not a stable hostname.

Then:

```bash
sudoedit /home/grokbot/flowdesk/.env
sudo systemctl restart flowdesk-bot flowdesk-tunnel
```

`.env` is never committed. `data/desk.key` and `data/telegram_chat_id` are mode `0600` and gitignored.

## Tests

```bash
pytest
```

Covers swing and fair-value-gap detection, candle-delta estimates (including “no volume”), confluence scoring, stop and target math, spread and slippage, partial TP then breakeven, trailing, daily loss, max positions, the event blackout, and the guarantee that `/api/check` does not call the paper broker.

## Owner input still required

- `FLOWDESK_TELEGRAM_TOKEN` from BotFather, and your chat id
- Optional `OANDA_API_KEY` and `OANDA_ACCOUNT_ID` if you want practice forex prices instead of Yahoo
- GitHub Pages enabled on `main` / `docs`
- A real tick feed later, behind `OrderFlowProvider`, if you want footprint instead of the OHLCV estimate
