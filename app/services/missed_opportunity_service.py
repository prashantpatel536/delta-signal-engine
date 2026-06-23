"""Track hypothetical outcomes for rejected or expired signals."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from app.config import settings
from app.paper_trader import (
    check_exit_reason,
    excursion_points,
    realized_points,
    reward_points,
    risk_points,
)
from app.repositories.signal_repository import SignalRepository

logger = logging.getLogger(__name__)

MISSED_EXIT_TP = "TP"
MISSED_EXIT_SL = "SL"
MISSED_EXIT_OPPOSITE = "Opposite Signal"


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

    def on_opposite_signal(self, new_signal: dict[str, Any]) -> list[dict[str, Any]]:
        """Close monitored missed trades when a reverse signal is generated."""
        opposite_side = "SELL" if new_signal["side"] == "BUY" else "BUY"
        candidates = self.repository.list_missed_monitoring_for(
            symbol=new_signal["symbol"],
            timeframe=new_signal["timeframe"],
            side=opposite_side,
        )
        if not candidates:
            return []

        exit_price = float(new_signal["entry"])
        resolved: list[dict[str, Any]] = []
        for record in candidates:
            if int(record["id"]) >= int(new_signal["id"]):
                continue
            updated = self._resolve_opposite(record, exit_price, new_signal["id"])
            if updated:
                resolved.append(updated)
        return resolved

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
                updated = self._resolve(
                    record,
                    status="MISSED_WINNER",
                    points=points,
                    exit_reason=MISSED_EXIT_TP,
                    exit_price=tp,
                )
                if updated:
                    resolved.append(updated)
            elif exit_reason == "SL":
                points = -risk_points(side, entry, sl)
                updated = self._resolve(
                    record,
                    status="MISSED_LOSER",
                    points=points,
                    exit_reason=MISSED_EXIT_SL,
                    exit_price=sl,
                )
                if updated:
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
                    "exit_reason": row.get("missed_exit_reason"),
                    "exit_price": row.get("missed_exit_price"),
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

    def _resolve_opposite(
        self,
        record: dict[str, Any],
        exit_price: float,
        closing_signal_id: int,
    ) -> dict[str, Any] | None:
        points = realized_points(record["side"], record["entry"], exit_price)
        status = "MISSED_WINNER" if points > 0 else "MISSED_LOSER"
        updated = self._resolve(
            record,
            status=status,
            points=points,
            exit_reason=MISSED_EXIT_OPPOSITE,
            exit_price=exit_price,
        )
        if updated:
            logger.info(
                "Missed %s via opposite signal: id=%s %s %s %.2f pts "
                "exit=%.4f closing_signal=%s",
                status.replace("_", " ").lower(),
                updated["id"],
                record["symbol"],
                record["side"],
                points,
                exit_price,
                closing_signal_id,
            )
        return updated

    def _resolve(
        self,
        record: dict[str, Any],
        *,
        status: str,
        points: float,
        exit_reason: str,
        exit_price: float,
    ) -> dict[str, Any] | None:
        from app.repositories.account_repository import AccountRepository
        from app.risk_engine import missed_opportunity_metrics

        balance = float(AccountRepository().get_account().get("balance") or 1000.0)
        metrics = missed_opportunity_metrics(
            record["side"],
            float(record["entry"]),
            float(exit_price),
            balance,
            record["symbol"],
        )
        updated = self.repository.resolve_missed(
            record["id"],
            status,
            points,
            exit_reason=exit_reason,
            exit_price=exit_price,
            missed_pnl_usd=metrics["pnl_usd"],
            missed_roe_pct=metrics["roe_pct"],
            missed_account_impact_pct=metrics["account_impact_pct"],
        )
        if not updated:
            return None

        if exit_reason == MISSED_EXIT_TP:
            logger.info(
                "Missed winner: id=%s %s %s +%.2f pts (TP)",
                updated["id"],
                record["symbol"],
                record["side"],
                points,
            )
        elif exit_reason == MISSED_EXIT_SL:
            logger.info(
                "Missed loser: id=%s %s %s %.2f pts (SL)",
                updated["id"],
                record["symbol"],
                record["side"],
                points,
            )
        return updated

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
