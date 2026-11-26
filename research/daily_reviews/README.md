# Daily reviews

The bot writes one file per NY trading day here (`YYYY-MM-DD.md`) right after the end-of-day flat (16:45 NY), and the same
summary goes into the `daily_reviews` table and the desk's Learning tab (Telegram: `/review`). The files are created on the
server in `~/flowdesk/research/daily_reviews/` (not committed). What the review checks and how it tightens the bot:
see the docstring of `flowdesk/review.py`; the end-of-day schedule is in `flowdesk/eod.py` and `eod:` in `config.yaml`.
