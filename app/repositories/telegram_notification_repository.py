"""Deduplication log for Telegram notifications."""

from __future__ import annotations

import sqlite3
from typing import Any

from app.database import get_connection
from app.models import utc_now_iso


class TelegramNotificationRepository:
    def claim(self, dedupe_key: str, *, event_type: str, entity_type: str, entity_id: int) -> bool:
        """Insert dedupe key; return True only for the first claim."""
        now = utc_now_iso()
        with get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO telegram_notifications (
                    dedupe_key, event_type, entity_type, entity_id, sent_at, success
                ) VALUES (?, ?, ?, ?, ?, 0)
                """,
                (dedupe_key, event_type, entity_type, entity_id, now),
            )
            conn.commit()
            return cursor.rowcount == 1

    def mark_success(self, dedupe_key: str, *, message_preview: str | None = None) -> None:
        with get_connection() as conn:
            conn.execute(
                """
                UPDATE telegram_notifications
                SET success = 1, message_preview = ?, error = NULL
                WHERE dedupe_key = ?
                """,
                (message_preview, dedupe_key),
            )
            conn.commit()

    def mark_failure(self, dedupe_key: str, error: str) -> None:
        with get_connection() as conn:
            conn.execute(
                """
                UPDATE telegram_notifications
                SET success = 0, error = ?
                WHERE dedupe_key = ?
                """,
                (error[:500], dedupe_key),
            )
            conn.commit()

    def was_sent(self, dedupe_key: str) -> bool:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM telegram_notifications WHERE dedupe_key = ? AND success = 1",
                (dedupe_key,),
            ).fetchone()
        return row is not None

    def list_recent(self, limit: int = 50) -> list[dict[str, Any]]:
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM telegram_notifications
                ORDER BY datetime(sent_at) DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]
