"""One-off owner action: back up the DB, then reset the PAPER balance to a fresh baseline.

    python tools/reset_paper.py --to 50 --confirm [--note "..."]

Keeps every trade/signal (stats + learning still use them); the equity curve, net P&L and drawdown restart
at the reset, and the daily-loss window restarts. Open paper trades stay open. Paper only - no broker is touched.
"""
from __future__ import annotations
import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from flowdesk.broker import PaperBroker  # noqa: E402
from flowdesk.config import get_config  # noqa: E402
from flowdesk.journal import Journal  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--to", type=float, required=True)
    ap.add_argument("--note", default="")
    ap.add_argument("--confirm", action="store_true")
    a = ap.parse_args()
    j = Journal()
    src = Path(j.path)
    bak = src.with_name(f"{src.name}.bak-reset-{int(time.time())}")
    if not a.confirm:
        print("dry run (add --confirm):", json.dumps({"db": str(src), "balance_now": float(j.get("balance", 0)), "to": a.to}))
        return 0
    with sqlite3.connect(src) as s, sqlite3.connect(bak) as d:   # consistent copy incl. WAL
        s.backup(d)
    b = PaperBroker(j, get_config().get("broker", {}))
    rec = b.reset_paper(a.to, a.note)
    print(json.dumps({"backup": str(bak), **rec, "open_trades": len(b.open_trades()), "equity": round(b.equity(), 2)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
