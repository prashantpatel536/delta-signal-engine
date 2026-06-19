"""Audit log for position TP/SL changes and manual closes."""

from __future__ import annotations

import sqlite3
from typing import Any

from app.database import get_connection
from app.models import utc_now_iso


class PositionEventRepository:
    def create(
        self,
        *,
        position_id: int,
        event_type: str,
        field_name: str | None = None,
        old_value: float | None = None,
        new_value: float | None = None,
        message: str | None = None,
    ) -> dict[str, Any]:
        now = utc_now_iso()
        with get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO position_events (
                    position_id, event_type, field_name, old_value, new_value, message, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (position_id, event_type, field_name, old_value, new_value, message, now),
            )
            conn.commit()
            event_id = cursor.lastrowid
        return self.get_by_id(event_id)

    def get_by_id(self, event_id: int) -> dict[str, Any] | None:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM position_events WHERE id = ?",
                (event_id,),
            ).fetchone()
        return dict(row) if row else None

    def list_for_position(self, position_id: int) -> list[dict[str, Any]]:
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM position_events
                WHERE position_id = ?
                ORDER BY datetime(created_at) DESC, id DESC
                """,
                (position_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_recent(self, limit: int = 100) -> list[dict[str, Any]]:
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM position_events
                ORDER BY datetime(created_at) DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]
