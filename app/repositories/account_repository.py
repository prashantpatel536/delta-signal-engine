"""Virtual paper trading account persistence."""

from __future__ import annotations

import sqlite3
from typing import Any

from app.database import get_connection

STARTING_BALANCE = 1000.0


class AccountRepository:
    def _row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        return dict(row)

    def ensure_account(self) -> dict[str, Any]:
        with get_connection() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO paper_account (id, balance, realized_pnl)
                VALUES (1, ?, 0.0)
                """,
                (STARTING_BALANCE,),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM paper_account WHERE id = 1").fetchone()
        return self._row_to_dict(row)

    def get_account(self) -> dict[str, Any]:
        account = self.ensure_account()
        return account

    def apply_realized_pnl(self, pnl: float) -> dict[str, Any]:
        with get_connection() as conn:
            conn.execute(
                """
                UPDATE paper_account
                SET balance = balance + ?,
                    realized_pnl = realized_pnl + ?
                WHERE id = 1
                """,
                (pnl, pnl),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM paper_account WHERE id = 1").fetchone()
        return self._row_to_dict(row)
