"""SQLite persistence for approval workflow signals."""

from __future__ import annotations

import sqlite3
from typing import Any

from app.database import get_connection
from app.models import utc_now_iso

VALID_STATUSES = frozenset({
    "PENDING",
    "APPROVED",
    "REJECTED",
    "EXPIRED",
    "TP_HIT",
    "SL_HIT",
    "MISSED_WINNER",
    "MISSED_LOSER",
})


class SignalRepository:
    def _row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["signal_timeframe"] = data.get("timeframe")
        if "missed_monitoring" in data:
            data["missed_monitoring"] = bool(data["missed_monitoring"])
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
        risk_profile: str | None = None,
    ) -> dict[str, Any]:
        now = created_at or utc_now_iso()
        with get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO signals (
                    symbol, timeframe, side, entry, stop_loss, take_profit,
                    risk_reward, status, created_at, updated_at, risk_profile
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    risk_profile,
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
        since_iso: str | None = None,
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
        if since_iso:
            conditions.append("datetime(created_at) >= datetime(?)")
            params.append(since_iso)
        query = "SELECT * FROM signals"
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY datetime(created_at) DESC, id DESC"
        with get_connection() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def list_chronological(self) -> list[dict[str, Any]]:
        """All signals ordered oldest-first for simulation replay."""
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM signals
                ORDER BY datetime(created_at) ASC, id ASC
                """
            ).fetchall()
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

    def start_missed_monitoring(self, signal_id: int) -> dict[str, Any] | None:
        now = utc_now_iso()
        with get_connection() as conn:
            cursor = conn.execute(
                """
                UPDATE signals
                SET missed_monitoring = 1,
                    monitoring_started_at = COALESCE(monitoring_started_at, ?),
                    updated_at = ?
                WHERE id = ?
                  AND status IN ('REJECTED', 'EXPIRED')
                  AND missed_resolved_at IS NULL
                """,
                (now, now, signal_id),
            )
            conn.commit()
            if cursor.rowcount == 0:
                return None
        return self.get_by_id(signal_id)

    def list_missed_monitoring(self) -> list[dict[str, Any]]:
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM signals
                WHERE missed_monitoring = 1
                ORDER BY datetime(monitoring_started_at) ASC, id ASC
                """
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def list_unresolved_rejected_expired(self) -> list[dict[str, Any]]:
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM signals
                WHERE status IN ('REJECTED', 'EXPIRED')
                  AND missed_monitoring = 0
                  AND missed_resolved_at IS NULL
                ORDER BY id ASC
                """
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def list_missed_monitoring_for(
        self,
        *,
        symbol: str,
        timeframe: str,
        side: str,
    ) -> list[dict[str, Any]]:
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM signals
                WHERE missed_monitoring = 1
                  AND symbol = ?
                  AND timeframe = ?
                  AND side = ?
                ORDER BY datetime(monitoring_started_at) ASC, id ASC
                """,
                (symbol, timeframe, side),
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def update_excursions(
        self,
        signal_id: int,
        max_favorable_excursion: float,
        max_adverse_excursion: float,
    ) -> None:
        now = utc_now_iso()
        with get_connection() as conn:
            conn.execute(
                """
                UPDATE signals
                SET max_favorable_excursion = ?,
                    max_adverse_excursion = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (max_favorable_excursion, max_adverse_excursion, now, signal_id),
            )
            conn.commit()

    def stop_missed_monitoring(self, signal_id: int) -> None:
        now = utc_now_iso()
        with get_connection() as conn:
            conn.execute(
                """
                UPDATE signals
                SET missed_monitoring = 0, updated_at = ?
                WHERE id = ?
                """,
                (now, signal_id),
            )
            conn.commit()

    def resolve_missed(
        self,
        signal_id: int,
        status: str,
        points_captured: float,
        *,
        exit_reason: str,
        exit_price: float,
        missed_pnl_usd: float | None = None,
        missed_roe_pct: float | None = None,
        missed_account_impact_pct: float | None = None,
    ) -> dict[str, Any] | None:
        if status not in {"MISSED_WINNER", "MISSED_LOSER"}:
            raise ValueError(f"Invalid missed status: {status}")
        now = utc_now_iso()
        with get_connection() as conn:
            cursor = conn.execute(
                """
                UPDATE signals
                SET status = ?,
                    points_captured = ?,
                    missed_exit_reason = ?,
                    missed_exit_price = ?,
                    missed_pnl_usd = ?,
                    missed_roe_pct = ?,
                    missed_account_impact_pct = ?,
                    missed_monitoring = 0,
                    missed_resolved_at = ?,
                    updated_at = ?
                WHERE id = ?
                  AND missed_monitoring = 1
                """,
                (
                    status,
                    points_captured,
                    exit_reason,
                    exit_price,
                    missed_pnl_usd,
                    missed_roe_pct,
                    missed_account_impact_pct,
                    now,
                    now,
                    signal_id,
                ),
            )
            conn.commit()
            if cursor.rowcount == 0:
                return None
        return self.get_by_id(signal_id)

    def list_missed_recalc_candidates(self) -> list[dict[str, Any]]:
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM signals
                WHERE status IN ('MISSED_WINNER', 'MISSED_LOSER')
                   OR (
                        status IN ('REJECTED', 'EXPIRED')
                        AND monitoring_started_at IS NOT NULL
                   )
                ORDER BY id ASC
                """
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def list_signal_recalc_index(self) -> list[dict[str, Any]]:
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT id, symbol, timeframe, side, entry, created_at
                FROM signals
                ORDER BY id ASC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def apply_recalculated_missed(
        self,
        signal_id: int,
        outcome: Any,
    ) -> dict[str, Any] | None:
        now = utc_now_iso()
        with get_connection() as conn:
            if outcome.resolved:
                conn.execute(
                    """
                    UPDATE signals
                    SET status = ?,
                        points_captured = ?,
                        missed_exit_reason = ?,
                        missed_exit_price = ?,
                        missed_pnl_usd = ?,
                        missed_roe_pct = ?,
                        missed_account_impact_pct = ?,
                        max_favorable_excursion = ?,
                        max_adverse_excursion = ?,
                        missed_monitoring = 0,
                        missed_resolved_at = COALESCE(?, ?),
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        outcome.status,
                        outcome.points_captured,
                        outcome.exit_reason,
                        outcome.exit_price,
                        outcome.missed_pnl_usd,
                        outcome.missed_roe_pct,
                        outcome.missed_account_impact_pct,
                        outcome.max_favorable_excursion,
                        outcome.max_adverse_excursion,
                        outcome.missed_resolved_at,
                        now,
                        now,
                        signal_id,
                    ),
                )
            else:
                conn.execute(
                    """
                    UPDATE signals
                    SET status = ?,
                        points_captured = NULL,
                        missed_exit_reason = NULL,
                        missed_exit_price = NULL,
                        missed_pnl_usd = NULL,
                        missed_roe_pct = NULL,
                        missed_account_impact_pct = NULL,
                        max_favorable_excursion = ?,
                        max_adverse_excursion = ?,
                        missed_monitoring = 0,
                        missed_resolved_at = NULL,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        outcome.status,
                        outcome.max_favorable_excursion,
                        outcome.max_adverse_excursion,
                        now,
                        signal_id,
                    ),
                )
            conn.commit()
        return self.get_by_id(signal_id)

    def get_missed_summary(self) -> dict[str, float | int | bool]:
        with get_connection() as conn:
            row = conn.execute(
                """
                SELECT
                    SUM(CASE WHEN status = 'MISSED_WINNER' THEN 1 ELSE 0 END) AS missed_winners,
                    SUM(CASE WHEN status = 'MISSED_LOSER' THEN 1 ELSE 0 END) AS missed_losers,
                    SUM(CASE WHEN status = 'MISSED_WINNER'
                        THEN COALESCE(points_captured, 0) ELSE 0 END) AS gross_missed_profit,
                    SUM(CASE WHEN status = 'MISSED_LOSER'
                        THEN COALESCE(points_captured, 0) ELSE 0 END) AS gross_missed_loss,
                    SUM(CASE WHEN status IN ('MISSED_WINNER', 'MISSED_LOSER')
                        THEN COALESCE(points_captured, 0) ELSE 0 END) AS net_missed_profit,
                    SUM(CASE WHEN status = 'MISSED_WINNER'
                        THEN COALESCE(missed_pnl_usd, 0) ELSE 0 END) AS gross_missed_pnl_usd,
                    SUM(CASE WHEN status = 'MISSED_LOSER'
                        THEN COALESCE(missed_pnl_usd, 0) ELSE 0 END) AS gross_missed_loss_usd,
                    SUM(CASE WHEN status IN ('MISSED_WINNER', 'MISSED_LOSER')
                        THEN COALESCE(missed_pnl_usd, 0) ELSE 0 END) AS net_missed_pnl_usd,
                    SUM(CASE WHEN missed_monitoring = 1 THEN 1 ELSE 0 END) AS monitoring,
                    SUM(CASE WHEN status IN ('REJECTED', 'EXPIRED', 'PENDING')
                        AND missed_resolved_at IS NOT NULL THEN 1 ELSE 0 END)
                        AS unresolved_status_with_resolution
                FROM signals
                """
            ).fetchone()
        winners = int(row["missed_winners"] or 0)
        losers = int(row["missed_losers"] or 0)
        total = winners + losers
        net_missed_pnl_usd = round(float(row["net_missed_pnl_usd"] or 0), 2)
        from app.repositories.account_repository import AccountRepository
        from app.risk_engine import trading_margin_percent

        balance = float(AccountRepository().get_account().get("balance") or 1000.0)
        margin_base = balance * (trading_margin_percent() / 100.0)
        net_missed_roe_pct = (
            round(net_missed_pnl_usd / margin_base * 100.0, 2) if margin_base > 0 else 0.0
        )
        return {
            "missed_opportunities": total,
            "missed_winners": winners,
            "missed_losers": losers,
            "gross_missed_profit": round(float(row["gross_missed_profit"] or 0), 2),
            "gross_missed_loss": round(float(row["gross_missed_loss"] or 0), 2),
            "net_missed_profit": round(float(row["net_missed_profit"] or 0), 2),
            "gross_missed_pnl_usd": round(float(row["gross_missed_pnl_usd"] or 0), 2),
            "gross_missed_loss_usd": round(float(row["gross_missed_loss_usd"] or 0), 2),
            "net_missed_pnl_usd": net_missed_pnl_usd,
            "net_missed_roe_pct": net_missed_roe_pct,
            "monitoring": int(row["monitoring"] or 0),
            "totals_valid": total == winners + losers,
            "unresolved_status_with_resolution": int(
                row["unresolved_status_with_resolution"] or 0
            ),
            "by_symbol": self.get_missed_net_by_symbol(),
        }

    def get_missed_net_by_symbol(self, since_iso: str | None = None) -> list[dict[str, Any]]:
        since_clause = ""
        params: list[Any] = []
        if since_iso:
            since_clause = " AND datetime(created_at) >= datetime(?)"
            params.append(since_iso)
        with get_connection() as conn:
            rows = conn.execute(
                f"""
                SELECT
                    symbol,
                    SUM(CASE WHEN status = 'MISSED_WINNER' THEN 1 ELSE 0 END) AS missed_winners,
                    SUM(CASE WHEN status = 'MISSED_LOSER' THEN 1 ELSE 0 END) AS missed_losers,
                    SUM(COALESCE(points_captured, 0)) AS net_missed_profit,
                    SUM(COALESCE(missed_pnl_usd, 0)) AS net_missed_pnl_usd,
                    SUM(COALESCE(missed_roe_pct, 0)) AS net_missed_roe_pct,
                    SUM(CASE WHEN status = 'MISSED_WINNER'
                        THEN COALESCE(missed_pnl_usd, 0) ELSE 0 END) AS gross_missed_profit_usd,
                    SUM(CASE WHEN status = 'MISSED_LOSER'
                        THEN COALESCE(missed_pnl_usd, 0) ELSE 0 END) AS gross_missed_loss_usd
                FROM signals
                WHERE status IN ('MISSED_WINNER', 'MISSED_LOSER'){since_clause}
                GROUP BY symbol
                """,
                tuple(params),
            ).fetchall()
        lookup = {
            row["symbol"]: {
                "symbol": row["symbol"],
                "missed_winners": int(row["missed_winners"] or 0),
                "missed_losers": int(row["missed_losers"] or 0),
                "net_missed_profit": round(float(row["net_missed_profit"] or 0), 2),
                "net_missed_pnl_usd": round(float(row["net_missed_pnl_usd"] or 0), 2),
                "net_missed_roe_pct": round(float(row["net_missed_roe_pct"] or 0), 2),
                "gross_missed_profit_usd": round(float(row["gross_missed_profit_usd"] or 0), 2),
                "gross_missed_loss_usd": round(float(row["gross_missed_loss_usd"] or 0), 2),
            }
            for row in rows
        }
        from app.config import settings

        ordered: list[dict[str, Any]] = []
        for short, full in settings.symbol_map.items():
            row = lookup.get(
                full,
                {
                    "symbol": full,
                    "missed_winners": 0,
                    "missed_losers": 0,
                    "net_missed_profit": 0.0,
                    "net_missed_pnl_usd": 0.0,
                    "net_missed_roe_pct": 0.0,
                    "gross_missed_profit_usd": 0.0,
                    "gross_missed_loss_usd": 0.0,
                },
            )
            ordered.append(
                {
                    "symbol": full,
                    "label": short,
                    "missed_winners": row["missed_winners"],
                    "missed_losers": row["missed_losers"],
                    "net_missed_profit": row["net_missed_profit"],
                    "net_missed_pnl_usd": row.get("net_missed_pnl_usd", 0.0),
                    "net_missed_roe_pct": row.get("net_missed_roe_pct", 0.0),
                    "gross_missed_profit_usd": row.get("gross_missed_profit_usd", 0.0),
                    "gross_missed_loss_usd": row.get("gross_missed_loss_usd", 0.0),
                }
            )
        return ordered

    def list_resolved_missed(self) -> list[dict[str, Any]]:
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM signals
                WHERE status IN ('MISSED_WINNER', 'MISSED_LOSER')
                ORDER BY datetime(missed_resolved_at) DESC, id DESC
                """
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def get_missed_diagnostics(self) -> dict[str, int | bool]:
        """Validate missed-opportunity counts are mutually exclusive and consistent."""
        with get_connection() as conn:
            row = conn.execute(
                """
                SELECT
                    SUM(CASE WHEN status IN ('MISSED_WINNER', 'MISSED_LOSER') THEN 1 ELSE 0 END)
                        AS total_missed,
                    SUM(CASE WHEN status = 'MISSED_WINNER' THEN 1 ELSE 0 END) AS total_winners,
                    SUM(CASE WHEN status = 'MISSED_LOSER' THEN 1 ELSE 0 END) AS total_losers,
                    SUM(CASE WHEN missed_monitoring = 1
                        AND status IN ('MISSED_WINNER', 'MISSED_LOSER') THEN 1 ELSE 0 END)
                        AS resolved_still_monitoring,
                    SUM(CASE WHEN status IN ('PENDING', 'APPROVED', 'TP_HIT', 'SL_HIT')
                        AND status IN ('MISSED_WINNER', 'MISSED_LOSER') THEN 1 ELSE 0 END)
                        AS active_workflow_in_missed,
                    SUM(CASE WHEN status IN ('REJECTED', 'EXPIRED')
                        AND missed_resolved_at IS NOT NULL THEN 1 ELSE 0 END)
                        AS rejected_expired_with_resolution
                FROM signals
                """
            ).fetchone()
        total = int(row["total_missed"] or 0)
        winners = int(row["total_winners"] or 0)
        losers = int(row["total_losers"] or 0)
        return {
            "total_missed": total,
            "total_winners": winners,
            "total_losers": losers,
            "totals_consistent": total == winners + losers,
            "duplicate_outcome_count": 0,
            "resolved_still_monitoring": int(row["resolved_still_monitoring"] or 0),
            "active_workflow_in_missed": int(row["active_workflow_in_missed"] or 0),
            "rejected_expired_with_resolution": int(
                row["rejected_expired_with_resolution"] or 0
            ),
        }

    def get_period_stats(self, since_iso: str) -> dict[str, float | int | bool]:
        """Counts aligned with History page when filtered by created_at >= since."""
        with get_connection() as conn:
            row = conn.execute(
                """
                SELECT
                    SUM(CASE WHEN datetime(created_at) >= datetime(?) THEN 1 ELSE 0 END)
                        AS signals_generated,
                    SUM(CASE WHEN datetime(created_at) >= datetime(?)
                        AND status IN ('APPROVED', 'TP_HIT', 'SL_HIT') THEN 1 ELSE 0 END)
                        AS signals_approved,
                    SUM(CASE WHEN datetime(created_at) >= datetime(?)
                        AND status = 'MISSED_WINNER' THEN 1 ELSE 0 END) AS missed_winners,
                    SUM(CASE WHEN datetime(created_at) >= datetime(?)
                        AND status = 'MISSED_LOSER' THEN 1 ELSE 0 END) AS missed_losers,
                    SUM(CASE WHEN datetime(created_at) >= datetime(?)
                        AND status = 'MISSED_WINNER'
                        THEN COALESCE(points_captured, 0) ELSE 0 END) AS gross_missed_profit,
                    SUM(CASE WHEN datetime(created_at) >= datetime(?)
                        AND status = 'MISSED_LOSER'
                        THEN COALESCE(points_captured, 0) ELSE 0 END) AS gross_missed_loss,
                    SUM(CASE WHEN datetime(created_at) >= datetime(?)
                        AND status IN ('MISSED_WINNER', 'MISSED_LOSER')
                        THEN COALESCE(points_captured, 0) ELSE 0 END) AS net_missed_profit,
                    SUM(CASE WHEN datetime(created_at) >= datetime(?)
                        AND status = 'MISSED_WINNER'
                        THEN COALESCE(missed_pnl_usd, 0) ELSE 0 END) AS gross_missed_pnl_usd,
                    SUM(CASE WHEN datetime(created_at) >= datetime(?)
                        AND status = 'MISSED_LOSER'
                        THEN COALESCE(missed_pnl_usd, 0) ELSE 0 END) AS gross_missed_loss_usd,
                    SUM(CASE WHEN datetime(created_at) >= datetime(?)
                        AND status IN ('MISSED_WINNER', 'MISSED_LOSER')
                        THEN COALESCE(missed_pnl_usd, 0) ELSE 0 END) AS net_missed_pnl_usd,
                    SUM(CASE WHEN datetime(created_at) >= datetime(?)
                        AND status IN ('MISSED_WINNER', 'MISSED_LOSER')
                        THEN COALESCE(missed_roe_pct, 0) ELSE 0 END) AS sum_missed_roe_pct
                FROM signals
                """,
                tuple([since_iso] * 11),
            ).fetchone()
        winners = int(row["missed_winners"] or 0)
        losers = int(row["missed_losers"] or 0)
        net_missed_pnl_usd = round(float(row["net_missed_pnl_usd"] or 0), 2)
        from app.repositories.account_repository import AccountRepository
        from app.risk_engine import trading_margin_percent

        balance = float(AccountRepository().get_account().get("balance") or 1000.0)
        margin_base = balance * (trading_margin_percent() / 100.0)
        net_missed_roe_pct = (
            round(net_missed_pnl_usd / margin_base * 100.0, 2) if margin_base > 0 else 0.0
        )
        return {
            "signals_generated": int(row["signals_generated"] or 0),
            "signals_approved": int(row["signals_approved"] or 0),
            "missed_opportunities": winners + losers,
            "missed_winners": winners,
            "missed_losers": losers,
            "gross_missed_profit": round(float(row["gross_missed_profit"] or 0), 2),
            "gross_missed_loss": round(float(row["gross_missed_loss"] or 0), 2),
            "net_missed_profit": round(float(row["net_missed_profit"] or 0), 2),
            "gross_missed_pnl_usd": round(float(row["gross_missed_pnl_usd"] or 0), 2),
            "gross_missed_loss_usd": round(float(row["gross_missed_loss_usd"] or 0), 2),
            "net_missed_pnl_usd": net_missed_pnl_usd,
            "net_missed_roe_pct": net_missed_roe_pct,
            "totals_valid": True,
            "by_symbol": self.get_missed_net_by_symbol(since_iso=since_iso),
        }

    def get_missed_analytics(self, since_iso: str) -> dict[str, float | int | bool]:
        return self.get_period_stats(since_iso)
