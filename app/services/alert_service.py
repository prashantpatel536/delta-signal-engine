"""Fan-out alerts to Telegram and email without blocking the app."""

from __future__ import annotations

import logging
from typing import Any

from app.services.email_service import EmailService, email_service
from app.services.telegram_service import TelegramService, telegram_service

logger = logging.getLogger(__name__)


class AlertService:
    def __init__(
        self,
        *,
        telegram: TelegramService | None = None,
        email: EmailService | None = None,
    ) -> None:
        self.telegram = telegram if telegram is not None else telegram_service
        self.email = email if email is not None else email_service

    def notify_signal_generated(self, signal: dict[str, Any]) -> None:
        self._safe(self.telegram.notify_signal_generated, signal, label="Telegram signal")
        self._safe(self.email.notify_signal_generated, signal, label="Email signal")

    def notify_trade_approved(
        self,
        signal: dict[str, Any],
        position: dict[str, Any],
    ) -> None:
        self._safe(
            lambda: self.telegram.notify_trade_approved(signal, position),
            label="Telegram trade approved",
        )
        self._safe(
            lambda: self.email.notify_trade_approved(signal, position),
            label="Email trade approved",
        )

    def notify_position_closed(self, position: dict[str, Any]) -> None:
        self._safe(self.telegram.notify_position_closed, position, label="Telegram close")
        self._safe(self.email.notify_position_closed, position, label="Email close")

    @staticmethod
    def _safe(fn, *args, label: str = "alert") -> None:
        try:
            fn(*args) if args else fn()
        except Exception:
            logger.exception("%s notification failed — continuing", label)


alert_service = AlertService()
