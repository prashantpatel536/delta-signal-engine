"""Validate /trade-history rows against ClosedTrade model."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.models import ClosedTrade  # noqa: E402
from app.services.paper_trading_service import PaperTradingService  # noqa: E402


def main() -> int:
    svc = PaperTradingService()
    trades = svc.get_closed_trades()
    print(f"closed trades: {len(trades)}")
    failed = 0
    for item in trades:
        try:
            ClosedTrade(**item)
        except Exception as exc:
            failed += 1
            print(f"FAIL id={item.get('id')}: {exc}")
            for key, value in sorted(item.items()):
                print(f"  {key}: {value!r}")

    db = ROOT / "data" / "signals.db"
    if db.exists():
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, side, status, exit_reason, stop_loss, take_profit, opened_at, closed_at "
            "FROM positions WHERE status='CLOSED'"
        ).fetchall()
        print(f"raw rows: {len(rows)}")
        print("exit_reasons:", {r["exit_reason"] for r in rows})
        print("sides:", {r["side"] for r in rows})

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
