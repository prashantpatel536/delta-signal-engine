"""SQLite persistence for approval workflow signals."""

from __future__ import annotations

import sqlite3
from typing import Any

from app.database import get_connection
from app.models import utc_now_iso

VALID_STATUSES = frozenset({"PENDING", "APPROVED", "REJECTED", "EXPIRED", "TP_HIT", "SL_HIT"})


class SignalRepository:
    def _row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["signal_timeframe"] = data.get("timeframe")
        return data

    def create(
        self,
        *,
        symbol: str,
        timeframe: str,
        side: str,
        entry: float,
        stop_loss: float,
        take_profit: float,
        risk_reward: float,
        status: str = "PENDING",
        created_at: str | None = None,
    ) -> dict[str, Any]:
        now = created_at or utc_now_iso()
        with get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO signals (
                    symbol, timeframe, side, entry, stop_loss, take_profit,
                    risk_reward, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    symbol,
                    timeframe,
                    side,
                    entry,
                    stop_loss,
                    take_profit,
                    risk_reward,
                    status,
                    now,
                    now,
                ),
            )
            conn.commit()
            signal_id = cursor.lastrowid
        return self.get_by_id(signal_id)

    def get_by_id(self, signal_id: int) -> dict[str, Any] | None:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM signals WHERE id = ?",
                (signal_id,),
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def find_by_key(
        self,
        symbol: str,
        timeframe: str,
        side: str,
        created_at: str,
    ) -> dict[str, Any] | None:
        with get_connection() as conn:
            row = conn.execute(
                """
                SELECT * FROM signals
                WHERE symbol = ? AND timeframe = ? AND side = ? AND created_at = ?
                LIMIT 1
                """,
                (symbol, timeframe, side, created_at),
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def list_for_symbol_timeframe(
        self,
        symbol: str,
        timeframe: str,
    ) -> list[dict[str, Any]]:
        return self.list_filtered(symbol=symbol, timeframe=timeframe)

    def has_pending(self, symbol: str, timeframe: str, side: str) -> bool:
        with get_connection() as conn:
            row = conn.execute(
                """
                SELECT 1 FROM signals
                WHERE symbol = ? AND timeframe = ? AND side = ? AND status = 'PENDING'
                LIMIT 1
                """,
                (symbol, timeframe, side),
            ).fetchone()
        return row is not None

    def exists_at_timestamp(
        self,
        symbol: str,
        timeframe: str,
        side: str,
        created_at: str,
    ) -> bool:
        with get_connection() as conn:
            row = conn.execute(
                """
                SELECT 1 FROM signals
                WHERE symbol = ? AND timeframe = ? AND side = ? AND created_at = ?
                LIMIT 1
                """,
                (symbol, timeframe, side, created_at),
            ).fetchone()
        return row is not None

    def list_by_status(self, status: str | None = None) -> list[dict[str, Any]]:
        return self.list_filtered(status=status)

    def list_filtered(
        self,
        *,
        status: str | None = None,
        symbol: str | None = None,
        timeframe: str | None = None,
    ) -> list[dict[str, Any]]:
        conditions: list[str] = []
        params: list[Any] = []
        if status:
            conditions.append("status = ?")
            params.append(status)
        if symbol:
            conditions.append("symbol = ?")
            params.append(symbol)
        if timeframe:
            conditions.append("timeframe = ?")
            params.append(timeframe)
        query = "SELECT * FROM signals"
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY datetime(created_at) DESC, id DESC"
        with get_connection() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def list_pending(
        self,
        *,
        symbol: str | None = None,
        timeframe: str | None = None,
    ) -> list[dict[str, Any]]:
        return self.list_filtered(status="PENDING", symbol=symbol, timeframe=timeframe)

    def update_status(self, signal_id: int, status: str) -> dict[str, Any] | None:
        if status not in VALID_STATUSES:
            raise ValueError(f"Invalid status: {status}")
        now = utc_now_iso()
        with get_connection() as conn:
            cursor = conn.execute(
                """
                UPDATE signals SET status = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, now, signal_id),
            )
            conn.commit()
            if cursor.rowcount == 0:
                return None
        return self.get_by_id(signal_id)

    def count_by_status(self) -> dict[str, int]:
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS count FROM signals GROUP BY status"
            ).fetchall()
        counts = {status: 0 for status in VALID_STATUSES}
        total = 0
        for row in rows:
            counts[row["status"]] = row["count"]
            total += row["count"]
        counts["TOTAL"] = total
        return counts

    def get_latest(self) -> dict[str, Any] | None:
        with get_connection() as conn:
            row = conn.execute(
                """
                SELECT * FROM signals
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def get_latest_pending(
        self,
        *,
        symbol: str | None = None,
        timeframe: str | None = None,
    ) -> dict[str, Any] | None:
        conditions = ["status = 'PENDING'"]
        params: list[Any] = []
        if symbol:
            conditions.append("symbol = ?")
            params.append(symbol)
        if timeframe:
            conditions.append("timeframe = ?")
            params.append(timeframe)
        query = f"""
            SELECT * FROM signals
            WHERE {' AND '.join(conditions)}
            ORDER BY datetime(created_at) DESC, id DESC
            LIMIT 1
        """
        with get_connection() as conn:
            row = conn.execute(query, tuple(params)).fetchone()
        return self._row_to_dict(row) if row else None

    def expire_stale_pending(self, cutoff_iso: str) -> list[dict[str, Any]]:
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT id FROM signals
                WHERE status = 'PENDING' AND created_at < ?
                """,
                (cutoff_iso,),
            ).fetchall()
            if not rows:
                return []
            now = utc_now_iso()
            ids = [row["id"] for row in rows]
            placeholders = ",".join("?" * len(ids))
            conn.execute(
                f"""
                UPDATE signals SET status = 'EXPIRED', updated_at = ?
                WHERE id IN ({placeholders})
                """,
                (now, *ids),
            )
            conn.commit()
            expired = conn.execute(
                f"SELECT * FROM signals WHERE id IN ({placeholders})",
                tuple(ids),
            ).fetchall()
        return [self._row_to_dict(row) for row in expired]
