"""SQLite persistence for paper trading positions."""

from __future__ import annotations

import sqlite3
from typing import Any

from app.database import get_connection
from app.models import utc_now_iso

POSITION_STATUSES = frozenset({"OPEN", "CLOSED"})


class PositionRepository:
    def _row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        return dict(row)

    def create(
        self,
        *,
        symbol: str,
        side: str,
        entry: float,
        stop_loss: float,
        take_profit: float,
        quantity: float,
        leverage: float,
        margin_used: float,
        position_value: float,
        risk_reward: float = 0.0,
        signal_id: int | None = None,
        opened_at: str | None = None,
    ) -> dict[str, Any]:
        now = opened_at or utc_now_iso()
        with get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO positions (
                    signal_id, symbol, side, entry, stop_loss, take_profit,
                    original_stop_loss, original_take_profit, risk_reward,
                    quantity, leverage, margin_used, position_value,
                    status, opened_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN', ?)
                """,
                (
                    signal_id,
                    symbol,
                    side,
                    entry,
                    stop_loss,
                    take_profit,
                    stop_loss,
                    take_profit,
                    risk_reward,
                    quantity,
                    leverage,
                    margin_used,
                    position_value,
                    now,
                ),
            )
            conn.commit()
            position_id = cursor.lastrowid
        return self.get_by_id(position_id)

    def _normalize_row(self, row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        data = dict(row)
        if data.get("original_stop_loss") is None:
            data["original_stop_loss"] = data.get("stop_loss")
        if data.get("original_take_profit") is None:
            data["original_take_profit"] = data.get("take_profit")
        return data

    def get_by_id(self, position_id: int) -> dict[str, Any] | None:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM positions WHERE id = ?",
                (position_id,),
            ).fetchone()
        return self._normalize_row(row) if row else None

    def get_by_signal_id(self, signal_id: int) -> dict[str, Any] | None:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM positions WHERE signal_id = ?",
                (signal_id,),
            ).fetchone()
        return self._normalize_row(row) if row else None

    def update_levels(
        self,
        position_id: int,
        *,
        stop_loss: float | None = None,
        take_profit: float | None = None,
        risk_reward: float | None = None,
    ) -> dict[str, Any] | None:
        position = self.get_by_id(position_id)
        if position is None or position["status"] != "OPEN":
            return None

        new_sl = float(stop_loss if stop_loss is not None else position["stop_loss"])
        new_tp = float(take_profit if take_profit is not None else position["take_profit"])
        new_rr = float(risk_reward if risk_reward is not None else position.get("risk_reward") or 0)

        with get_connection() as conn:
            cursor = conn.execute(
                """
                UPDATE positions
                SET stop_loss = ?, take_profit = ?, risk_reward = ?
                WHERE id = ? AND status = 'OPEN'
                """,
                (new_sl, new_tp, new_rr, position_id),
            )
            conn.commit()
            if cursor.rowcount == 0:
                return None
        return self.get_by_id(position_id)

    def list_open(self) -> list[dict[str, Any]]:
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM positions
                WHERE status = 'OPEN'
                ORDER BY datetime(opened_at) DESC, id DESC
                """
            ).fetchall()
        return [self._normalize_row(row) for row in rows]

    def list_closed(self) -> list[dict[str, Any]]:
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM positions
                WHERE status = 'CLOSED'
                ORDER BY datetime(closed_at) DESC, id DESC
                """
            ).fetchall()
        return [self._normalize_row(row) for row in rows]

    def list_closed_chronological(self) -> list[dict[str, Any]]:
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM positions
                WHERE status = 'CLOSED'
                ORDER BY datetime(closed_at) ASC, id ASC
                """
            ).fetchall()
        return [self._normalize_row(row) for row in rows]

    def sum_open_margin(self) -> float:
        with get_connection() as conn:
            row = conn.execute(
                """
                SELECT COALESCE(SUM(margin_used), 0) AS total
                FROM positions WHERE status = 'OPEN'
                """
            ).fetchone()
        return float(row["total"]) if row else 0.0

    def close(
        self,
        position_id: int,
        *,
        exit_price: float,
        exit_reason: str,
        pnl: float,
        closed_at: str | None = None,
        price_points: float | None = None,
        account_impact_pct: float | None = None,
    ) -> dict[str, Any] | None:
        now = closed_at or utc_now_iso()
        with get_connection() as conn:
            cursor = conn.execute(
                """
                UPDATE positions
                SET status = 'CLOSED',
                    closed_at = ?,
                    exit_price = ?,
                    exit_reason = ?,
                    pnl = ?,
                    price_points = ?,
                    account_impact_pct = ?
                WHERE id = ? AND status = 'OPEN'
                """,
                (now, exit_price, exit_reason, pnl, price_points, account_impact_pct, position_id),
            )
            conn.commit()
            if cursor.rowcount == 0:
                return None
        return self.get_by_id(position_id)

    def update_closed_metrics(
        self,
        position_id: int,
        *,
        pnl: float,
        quantity: float,
        leverage: float,
        margin_used: float,
        position_value: float,
        price_points: float,
        account_impact_pct: float,
    ) -> dict[str, Any] | None:
        with get_connection() as conn:
            cursor = conn.execute(
                """
                UPDATE positions
                SET pnl = ?,
                    quantity = ?,
                    leverage = ?,
                    margin_used = ?,
                    position_value = ?,
                    price_points = ?,
                    account_impact_pct = ?
                WHERE id = ? AND status = 'CLOSED'
                """,
                (
                    pnl,
                    quantity,
                    leverage,
                    margin_used,
                    position_value,
                    price_points,
                    account_impact_pct,
                    position_id,
                ),
            )
            conn.commit()
            if cursor.rowcount == 0:
                return None
        return self.get_by_id(position_id)

    def closed_pnl_rows(self) -> list[dict[str, Any]]:
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT pnl, exit_reason FROM positions
                WHERE status = 'CLOSED' AND pnl IS NOT NULL
                """
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def has_open_for_symbol(self, symbol: str) -> bool:
        with get_connection() as conn:
            row = conn.execute(
                """
                SELECT 1 FROM positions
                WHERE symbol = ? AND status = 'OPEN'
                LIMIT 1
                """,
                (symbol,),
            ).fetchone()
        return row is not None
