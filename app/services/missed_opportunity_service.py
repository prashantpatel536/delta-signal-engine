"""Track hypothetical outcomes for rejected or expired signals."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from app.config import settings
from app.paper_trader import (
    check_exit_reason,
    excursion_points,
    reward_points,
    risk_points,
)
from app.repositories.signal_repository import SignalRepository

logger = logging.getLogger(__name__)


class MissedOpportunityService:
    def __init__(self, repository: SignalRepository | None = None) -> None:
        self.repository = repository or SignalRepository()

    def start_monitoring(self, signal_id: int) -> dict[str, Any] | None:
        record = self.repository.start_missed_monitoring(signal_id)
        if record:
            logger.info(
                "Missed-opportunity monitoring started: id=%s %s %s",
                record["id"],
                record["symbol"],
                record["side"],
            )
        return record

    def ensure_monitoring_queue(self) -> int:
        """Enqueue legacy REJECTED/EXPIRED signals that were never monitored."""
        queued = 0
        for record in self.repository.list_unresolved_rejected_expired():
            if self.start_monitoring(record["id"]):
                queued += 1
        return queued

    def monitor_signals(self, prices: dict[str, float]) -> list[dict[str, Any]]:
        self.ensure_monitoring_queue()
        resolved: list[dict[str, Any]] = []
        for record in self.repository.list_missed_monitoring():
            symbol = record["symbol"]
            price = prices.get(symbol)
            if price is None:
                continue

            side = record["side"]
            entry = float(record["entry"])
            sl = float(record["stop_loss"])
            tp = float(record["take_profit"])

            favorable, adverse = excursion_points(side, entry, price)
            mfe = max(float(record.get("max_favorable_excursion") or 0), favorable)
            mae = max(float(record.get("max_adverse_excursion") or 0), adverse)
            if mfe != record.get("max_favorable_excursion") or mae != record.get(
                "max_adverse_excursion"
            ):
                self.repository.update_excursions(record["id"], mfe, mae)

            if self._monitoring_expired(record):
                self.repository.stop_missed_monitoring(record["id"])
                logger.info(
                    "Missed-opportunity monitoring ended (timeout): id=%s %s",
                    record["id"],
                    symbol,
                )
                continue

            exit_reason = check_exit_reason(side, price, sl, tp)
            if exit_reason == "TP":
                points = reward_points(side, entry, tp)
                updated = self.repository.resolve_missed(
                    record["id"], "MISSED_WINNER", points
                )
                if updated:
                    logger.info(
                        "Missed winner: id=%s %s %s +%.2f pts",
                        updated["id"],
                        symbol,
                        side,
                        points,
                    )
                    resolved.append(updated)
            elif exit_reason == "SL":
                points = -risk_points(side, entry, sl)
                updated = self.repository.resolve_missed(
                    record["id"], "MISSED_LOSER", points
                )
                if updated:
                    logger.info(
                        "Missed loser: id=%s %s %s %.2f pts",
                        updated["id"],
                        symbol,
                        side,
                        points,
                    )
                    resolved.append(updated)
        return resolved

    def get_summary(self) -> dict[str, float | int | bool]:
        summary = self.repository.get_missed_summary()
        diagnostics = self.repository.get_missed_diagnostics()
        logger.info(
            "Missed opportunity totals: total=%d winners=%d losers=%d "
            "consistent=%s monitoring=%d gross_profit=%.2f gross_loss=%.2f net=%.2f",
            summary["missed_opportunities"],
            summary["missed_winners"],
            summary["missed_losers"],
            diagnostics["totals_consistent"],
            summary["monitoring"],
            summary["gross_missed_profit"],
            summary["gross_missed_loss"],
            summary["net_missed_profit"],
        )
        if not diagnostics["totals_consistent"]:
            logger.warning(
                "Missed opportunity count mismatch: total=%s winners=%s losers=%s",
                diagnostics["total_missed"],
                diagnostics["total_winners"],
                diagnostics["total_losers"],
            )
        if diagnostics["resolved_still_monitoring"]:
            logger.warning(
                "Resolved missed signals still flagged monitoring: %d",
                diagnostics["resolved_still_monitoring"],
            )
        summary["diagnostics"] = diagnostics
        return summary

    def get_debug_audit(self) -> dict[str, Any]:
        summary = self.get_summary()
        records = self.repository.list_resolved_missed()
        return {
            **summary["diagnostics"],
            "gross_missed_profit": summary["gross_missed_profit"],
            "gross_missed_loss": summary["gross_missed_loss"],
            "net_missed_profit": summary["net_missed_profit"],
            "monitoring_active": summary["monitoring"],
            "signals": [
                {
                    "signal_id": row["id"],
                    "symbol": row["symbol"],
                    "outcome": row["status"],
                    "points_missed": row.get("points_captured"),
                }
                for row in records
            ],
        }

    @staticmethod
    def period_start(period: str) -> str:
        now = datetime.now(timezone.utc)
        if period == "7d":
            start = now - timedelta(days=7)
        elif period == "30d":
            start = now - timedelta(days=30)
        else:
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return start.isoformat()

    def get_analytics(self, period: str) -> dict[str, Any]:
        since = self.period_start(period)
        stats = self.repository.get_missed_analytics(since)
        stats["period"] = period
        stats["since"] = since
        return stats

    @staticmethod
    def _monitoring_expired(record: dict[str, Any]) -> bool:
        started = record.get("monitoring_started_at")
        if not started:
            return False
        try:
            start_dt = datetime.fromisoformat(str(started).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return False
        age = datetime.now(timezone.utc) - start_dt.astimezone(timezone.utc)
        return age > timedelta(hours=settings.missed_opportunity_monitor_hours)


missed_opportunity_service = MissedOpportunityService()
