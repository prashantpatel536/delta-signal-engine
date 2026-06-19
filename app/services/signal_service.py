"""Signal approval workflow service."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from app.config import settings
from app.repositories.signal_repository import SignalRepository
from app.services.paper_trading_service import InsufficientMarginError, PaperTradingService
from app.trade_planner import build_trade_plan

logger = logging.getLogger(__name__)


class SignalService:
    def __init__(
        self,
        repository: SignalRepository | None = None,
        paper_service: PaperTradingService | None = None,
    ) -> None:
        self.repository = repository or SignalRepository()
        self.paper_service = paper_service or PaperTradingService()

    def persist_detected_signal(
        self,
        *,
        symbol: str,
        timeframe: str,
        side: str,
        entry: float,
        hh50: float,
        ll50: float,
        created_at: str,
    ) -> dict[str, Any] | None:
        """
        Save a newly detected signal with trade plan.

        Skips insert when a pending signal already exists for the same
        symbol/timeframe/side, or when this candle signal was already stored.
        """
        self.expire_stale_pending()

        if self.repository.has_pending(symbol, timeframe, side):
            logger.debug(
                "Skip persist: pending %s already exists for %s %s",
                side,
                symbol,
                timeframe,
            )
            return None

        if self.repository.exists_at_timestamp(symbol, timeframe, side, created_at):
            logger.debug(
                "Skip persist: duplicate timestamp for %s %s %s",
                symbol,
                timeframe,
                side,
            )
            return None

        plan = build_trade_plan(side, entry, hh50, ll50)  # type: ignore[arg-type]
        record = self.repository.create(
            symbol=symbol,
            timeframe=timeframe,
            side=plan.side,
            entry=plan.entry,
            stop_loss=plan.stop_loss,
            take_profit=plan.take_profit,
            risk_reward=plan.risk_reward,
            status="PENDING",
            created_at=created_at,
        )
        logger.info("Persisted pending signal id=%s %s %s %s", record["id"], symbol, timeframe, side)
        return record

    def persist_from_runtime_signal(
        self,
        signal: dict[str, Any],
        hh50: float,
        ll50: float,
    ) -> dict[str, Any] | None:
        return self.resolve_runtime_signal(signal, hh50, ll50)

    def resolve_runtime_signal(
        self,
        signal: dict[str, Any],
        hh50: float,
        ll50: float,
    ) -> dict[str, Any] | None:
        """Return stored record for a runtime signal; create PENDING when new."""
        if not signal:
            return None
        self.expire_stale_pending()
        symbol = signal["symbol"]
        timeframe = signal["timeframe"]
        side = signal["signal"]
        created_at = signal["timestamp"]

        existing = self.repository.find_by_key(symbol, timeframe, side, created_at)
        if existing:
            return existing

        return self.persist_detected_signal(
            symbol=symbol,
            timeframe=timeframe,
            side=side,
            entry=float(signal["price"]),
            hh50=hh50,
            ll50=ll50,
            created_at=created_at,
        )

    def enrich_chart_signals(
        self,
        chart_signals: list[dict[str, Any]],
        symbol: str,
        timeframe: str,
    ) -> list[dict[str, Any]]:
        records = self.repository.list_for_symbol_timeframe(symbol, timeframe)
        lookup = {f"{r['side']}:{r['created_at']}": r for r in records}
        enriched: list[dict[str, Any]] = []
        for item in chart_signals:
            row = dict(item)
            stored = lookup.get(f"{item['signal']}:{item['timestamp']}")
            if stored:
                row["status"] = stored["status"]
                row["signal_id"] = stored["id"]
            enriched.append(row)
        return enriched

    @staticmethod
    def stored_to_quality(stored: dict[str, Any], timeframe: str) -> dict[str, Any]:
        from app.signals import signal_reasons

        return {
            "timeframe": timeframe,
            "side": stored["side"],
            "entry": stored["entry"],
            "stop_loss": stored["stop_loss"],
            "take_profit": stored["take_profit"],
            "risk_reward": stored["risk_reward"],
            "reasons": signal_reasons(stored["side"]),
            "timestamp": stored["created_at"],
            "status": stored["status"],
            "id": stored["id"],
        }

    def mark_trade_exit(self, signal_id: int, exit_reason: str) -> None:
        status_map = {"TP": "TP_HIT", "SL": "SL_HIT"}
        target = status_map.get(exit_reason)
        if not target:
            return
        record = self.repository.get_by_id(signal_id)
        if record is None or record["status"] != "APPROVED":
            return
        self.repository.update_status(signal_id, target)
        logger.info("Signal %s marked %s after %s exit", signal_id, target, exit_reason)

    def expire_stale_pending(self) -> list[dict[str, Any]]:
        minutes = settings.pending_signal_expiry_minutes
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
        expired = self.repository.expire_stale_pending(cutoff)
        for record in expired:
            logger.info(
                "Signal expired: id=%s %s %s (>%sm pending)",
                record["id"],
                record["symbol"],
                record["timeframe"],
                minutes,
            )
        return expired

    def is_signal_expired(self, record: dict[str, Any]) -> bool:
        if record.get("status") != "PENDING":
            return record.get("status") == "EXPIRED"
        try:
            created = datetime.fromisoformat(record["created_at"].replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return False
        age = datetime.now(timezone.utc) - created.astimezone(timezone.utc)
        return age > timedelta(minutes=settings.pending_signal_expiry_minutes)

    def get_pending_signals(
        self,
        *,
        symbol: str | None = None,
        timeframe: str | None = None,
    ) -> list[dict[str, Any]]:
        self.expire_stale_pending()
        return self.repository.list_pending(symbol=symbol, timeframe=timeframe)

    def get_latest_pending_signal(
        self,
        *,
        symbol: str | None = None,
        timeframe: str | None = None,
    ) -> dict[str, Any] | None:
        """Return latest PENDING signal for exact symbol+timeframe only."""
        self.expire_stale_pending()
        return self.repository.get_latest_pending(symbol=symbol, timeframe=timeframe)

    def get_signal_history(
        self,
        status: str | None = None,
        *,
        symbol: str | None = None,
        timeframe: str | None = None,
    ) -> list[dict[str, Any]]:
        self.expire_stale_pending()
        return self.repository.list_filtered(
            status=status,
            symbol=symbol,
            timeframe=timeframe,
        )

    def get_signal(self, signal_id: int) -> dict[str, Any] | None:
        return self.repository.get_by_id(signal_id)

    def approve_signal(self, signal_id: int) -> dict[str, Any]:
        return self._transition(signal_id, from_status="PENDING", to_status="APPROVED")

    def reject_signal(self, signal_id: int) -> dict[str, Any]:
        return self._transition(signal_id, from_status="PENDING", to_status="REJECTED")

    def approve_and_execute(
        self,
        signal_id: int,
        *,
        leverage: float,
        margin_percent: float,
        stop_loss: float | None = None,
        take_profit: float | None = None,
        prices: dict[str, float] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        self.expire_stale_pending()
        record = self.repository.get_by_id(signal_id)
        if record is None:
            raise LookupError(f"Signal {signal_id} not found")
        if record["status"] == "EXPIRED" or self.is_signal_expired(record):
            if record["status"] == "PENDING":
                self.repository.update_status(signal_id, "EXPIRED")
            raise ValueError("Signal has expired and cannot be approved")
        if record["status"] != "PENDING":
            raise ValueError(
                f"Signal {signal_id} is {record['status']}, expected PENDING"
            )

        sl = float(stop_loss if stop_loss is not None else record["stop_loss"])
        tp = float(take_profit if take_profit is not None else record["take_profit"])

        try:
            position = self.paper_service.open_paper_trade(
                symbol=record["symbol"],
                side=record["side"],
                entry=float(record["entry"]),
                margin_percent=margin_percent,
                leverage=leverage,
                stop_loss=sl,
                take_profit=tp,
                signal_id=signal_id,
                prices=prices,
            )
        except InsufficientMarginError as exc:
            raise ValueError(str(exc)) from exc

        updated = self._transition(signal_id, from_status="PENDING", to_status="APPROVED")
        return updated, position

    def get_statistics(self) -> dict[str, int]:
        self.expire_stale_pending()
        return self.repository.count_by_status()

    def get_latest_signal(self) -> dict[str, Any] | None:
        return self.repository.get_latest()

    def _transition(
        self,
        signal_id: int,
        *,
        from_status: str,
        to_status: str,
    ) -> dict[str, Any]:
        record = self.repository.get_by_id(signal_id)
        if record is None:
            raise LookupError(f"Signal {signal_id} not found")
        if record["status"] != from_status:
            raise ValueError(
                f"Signal {signal_id} is {record['status']}, expected {from_status}"
            )
        updated = self.repository.update_status(signal_id, to_status)
        if updated is None:
            raise LookupError(f"Signal {signal_id} not found")
        logger.info("Signal %s transitioned %s -> %s", signal_id, from_status, to_status)
        return updated
