"""System and database diagnostics for localhost vs VPS parity checks."""

from __future__ import annotations

import os
import platform
import socket
from pathlib import Path
from typing import Any

from app.config import PROJECT_ROOT, settings
from app.database import get_connection, get_db_path
from app.repositories.account_repository import AccountRepository
from app.version import SIGNAL_ENGINE_VERSION, get_build_timestamp, get_git_commit

TRACKED_TABLES = (
    "signals",
    "positions",
    "paper_account",
    "app_settings",
    "position_events",
    "telegram_notifications",
)

PRODUCTION_SYNC_META = PROJECT_ROOT / "data" / "production_sync.json"
VPS_CANONICAL_NOTE = (
    "Production: VPS only (24/7). Edit code locally, deploy to VPS, verify metrics on VPS. "
    "Localhost stats are not comparable unless using a separate dev database."
)


class SystemDebugService:
    def _production_sync_meta(self) -> dict[str, Any] | None:
        if not PRODUCTION_SYNC_META.exists():
            return None
        try:
            import json

            return json.loads(PRODUCTION_SYNC_META.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _database_size_bytes(self, db_path: Path) -> int:
        if not db_path.exists():
            return 0
        return int(db_path.stat().st_size)

    def _table_row_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        with get_connection() as conn:
            for table in TRACKED_TABLES:
                try:
                    row = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()
                    counts[table] = int(row["n"] if row else 0)
                except Exception:
                    counts[table] = -1
        return counts

    def _signal_status_counts(self) -> dict[str, int]:
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT status, COUNT(*) AS n
                FROM signals
                GROUP BY status
                ORDER BY status
                """
            ).fetchall()
        return {str(row["status"]): int(row["n"]) for row in rows}

    def _position_status_counts(self) -> dict[str, int]:
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT status, COUNT(*) AS n
                FROM positions
                GROUP BY status
                ORDER BY status
                """
            ).fetchall()
        return {str(row["status"]): int(row["n"]) for row in rows}

    def _latest_signal_ids(self, limit: int = 20) -> list[dict[str, Any]]:
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT id, symbol, side, status, created_at
                FROM signals
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def _latest_trade_ids(self, limit: int = 20) -> list[dict[str, Any]]:
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT id, signal_id, symbol, side, status, pnl, opened_at, closed_at
                FROM positions
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def _scalar(self, sql: str) -> Any:
        with get_connection() as conn:
            row = conn.execute(sql).fetchone()
            return row[0] if row else None

    def core_system_payload(self) -> dict[str, Any]:
        db_path = get_db_path().resolve()
        signal_count = int(self._scalar("SELECT COUNT(*) FROM signals") or 0)
        trade_count = int(self._scalar("SELECT COUNT(*) FROM positions") or 0)
        approved_count = int(
            self._scalar(
                """
                SELECT COUNT(*) FROM signals
                WHERE status IN ('APPROVED', 'TP_HIT', 'SL_HIT')
                """
            )
            or 0
        )
        latest_signal_time = self._scalar(
            "SELECT MAX(created_at) FROM signals"
        )
        latest_trade_time = self._scalar(
            """
            SELECT MAX(COALESCE(closed_at, opened_at)) FROM positions
            """
        )

        return {
            "git_commit": get_git_commit(),
            "database_path": str(db_path),
            "database_size": self._database_size_bytes(db_path),
            "signal_count": signal_count,
            "trade_count": trade_count,
            "approved_count": approved_count,
            "latest_signal_time": latest_signal_time,
            "latest_trade_time": latest_trade_time,
        }

    def full_diagnostics(self) -> dict[str, Any]:
        db_path = get_db_path().resolve()
        account = AccountRepository().get_account()
        status_counts = self._signal_status_counts()
        missed_winners = int(status_counts.get("MISSED_WINNER", 0))
        missed_losers = int(status_counts.get("MISSED_LOSER", 0))

        return {
            **self.core_system_payload(),
            "build_timestamp": get_build_timestamp(),
            "signal_engine_version": SIGNAL_ENGINE_VERSION,
            "hostname": socket.gethostname(),
            "platform": platform.platform(),
            "python_version": platform.python_version(),
            "project_root": str(PROJECT_ROOT.resolve()),
            "database_exists": db_path.exists(),
            "database_path_env": os.getenv("DATABASE_PATH", ""),
            "database_size_human": self._format_bytes(self._database_size_bytes(db_path)),
            "table_row_counts": self._table_row_counts(),
            "signal_status_counts": status_counts,
            "position_status_counts": self._position_status_counts(),
            "paper_account": {
                "balance": float(account.get("balance") or 0),
                "realized_pnl": float(account.get("realized_pnl") or 0),
            },
            "database_info": {
                "total_signals": int(self._scalar("SELECT COUNT(*) FROM signals") or 0),
                "total_trades": int(self._scalar("SELECT COUNT(*) FROM positions") or 0),
                "total_approved_signals": int(
                    self._scalar(
                        """
                        SELECT COUNT(*) FROM signals
                        WHERE status IN ('APPROVED', 'TP_HIT', 'SL_HIT')
                        """
                    )
                    or 0
                ),
                "total_missed_winners": missed_winners,
                "total_missed_losers": missed_losers,
                "open_positions": int(
                    self._scalar("SELECT COUNT(*) FROM positions WHERE status = 'OPEN'") or 0
                ),
                "closed_positions": int(
                    self._scalar("SELECT COUNT(*) FROM positions WHERE status = 'CLOSED'") or 0
                ),
            },
            "latest_signals": self._latest_signal_ids(20),
            "latest_trades": self._latest_trade_ids(20),
            "production_source": "vps",
            "production_sync": self._production_sync_meta(),
            "sync_note": VPS_CANONICAL_NOTE,
        }

    @staticmethod
    def _format_bytes(size: int) -> str:
        if size < 1024:
            return f"{size} B"
        if size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        return f"{size / (1024 * 1024):.2f} MB"

    def compare_with_remote(self, remote: dict[str, Any]) -> dict[str, Any]:
        """Diff local stats against another /api/debug/system payload."""
        local = self.full_diagnostics()
        local_core = self.core_system_payload()
        remote_core = {
            k: remote.get(k)
            for k in (
                "git_commit",
                "database_path",
                "database_size",
                "signal_count",
                "trade_count",
                "approved_count",
                "latest_signal_time",
                "latest_trade_time",
            )
        }

        field_diffs: dict[str, dict[str, Any]] = {}
        for key in remote_core:
            local_val = local_core.get(key)
            remote_val = remote_core.get(key)
            if local_val != remote_val:
                field_diffs[key] = {"local": local_val, "remote": remote_val}

        local_tables = local.get("table_row_counts") or {}
        remote_tables = remote.get("table_row_counts") or remote.get("tables") or {}
        table_diffs: list[dict[str, Any]] = []
        all_tables = sorted(set(local_tables) | set(remote_tables))
        for table in all_tables:
            local_rows = int(local_tables.get(table, 0))
            remote_rows = int(remote_tables.get(table, 0))
            if local_rows != remote_rows:
                table_diffs.append({
                    "table": table,
                    "local_rows": local_rows,
                    "remote_rows": remote_rows,
                    "difference": local_rows - remote_rows,
                })

        local_status = local.get("signal_status_counts") or {}
        remote_status = remote.get("signal_status_counts") or {}
        status_diffs: list[dict[str, Any]] = []
        for status in sorted(set(local_status) | set(remote_status)):
            local_n = int(local_status.get(status, 0))
            remote_n = int(remote_status.get(status, 0))
            if local_n != remote_n:
                status_diffs.append({
                    "status": status,
                    "local": local_n,
                    "remote": remote_n,
                    "difference": local_n - remote_n,
                })

        identical = not field_diffs and not table_diffs and not status_diffs

        explanation: list[str] = []
        if not identical:
            if local_core.get("database_path") != remote_core.get("database_path"):
                explanation.append(
                    "DATABASE_PATH differs — each host is reading a different SQLite file."
                )
            if local_core.get("git_commit") != remote_core.get("git_commit"):
                explanation.append(
                    "Git commit differs — code versions may compute or display metrics differently."
                )
            if table_diffs:
                names = ", ".join(d["table"] for d in table_diffs)
                explanation.append(f"Table row counts differ: {names}.")
            if status_diffs:
                explanation.append(
                    "Signal status breakdown differs — engines accumulated different signal histories."
                )
            if local.get("paper_account") != remote.get("paper_account"):
                explanation.append(
                    "paper_account balance differs — independent trade PnL on each host."
                )

        return {
            "identical": identical,
            "local": local_core,
            "remote": remote_core,
            "field_differences": field_diffs,
            "table_differences": table_diffs,
            "signal_status_differences": status_diffs,
            "explanation": explanation,
            "root_cause": (
                "Separate SQLite databases per host (data/signals.db is local and gitignored). "
                "Each running engine writes signals/trades only to its own file."
                if not identical
                else None
            ),
        }


system_debug_service = SystemDebugService()
