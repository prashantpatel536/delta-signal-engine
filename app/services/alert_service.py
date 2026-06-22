"""Fan-out alerts to Telegram and email without blocking the app."""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable

from app.services.email_service import EmailService, email_service
from app.services.pushover_service import PushoverService, pushover_service
from app.services.telegram_service import TelegramService, telegram_service

logger = logging.getLogger(__name__)


class AlertService:
    def __init__(
        self,
        *,
        telegram: TelegramService | None = None,
        email: EmailService | None = None,
        pushover: PushoverService | None = None,
        blocking: bool = False,
    ) -> None:
        self.telegram = telegram if telegram is not None else telegram_service
        self.email = email if email is not None else email_service
        self.pushover = pushover if pushover is not None else pushover_service
        self._blocking = blocking

    def notify_signal_generated(self, signal: dict[str, Any]) -> None:
        self._dispatch(self.telegram.notify_signal_generated, signal, label="Telegram signal")
        self._dispatch(self.email.notify_signal_generated, signal, label="Email signal")
        self._dispatch(self.pushover.notify_signal_generated, signal, label="Pushover signal")

    def notify_trade_approved(
        self,
        signal: dict[str, Any],
        position: dict[str, Any],
    ) -> None:
        self._dispatch(
            lambda: self.telegram.notify_trade_approved(signal, position),
            label="Telegram trade approved",
        )
        self._dispatch(
            lambda: self.email.notify_trade_approved(signal, position),
            label="Email trade approved",
        )
        self._dispatch(
            lambda: self.pushover.notify_trade_approved(signal, position),
            label="Pushover trade approved",
        )

    def notify_position_closed(self, position: dict[str, Any]) -> None:
        self._dispatch(self.telegram.notify_position_closed, position, label="Telegram close")
        self._dispatch(self.email.notify_position_closed, position, label="Email close")
        self._dispatch(self.pushover.notify_position_closed, position, label="Pushover close")

    def _dispatch(self, fn: Callable[..., Any], *args: Any, label: str = "alert") -> None:
        if self._blocking:
            self._safe(fn, *args, label=label)
            return

        def run() -> None:
            self._safe(fn, *args, label=label)

        threading.Thread(target=run, daemon=True, name=f"alert-{label}").start()

    @staticmethod
    def _safe(fn: Callable[..., Any], *args: Any, label: str = "alert") -> None:
        try:
            fn(*args) if args else fn()
        except Exception:
            logger.exception("%s notification failed — continuing", label)


alert_service = AlertService()
