"""Telegram Bot API notifications for signals and trades."""

from __future__ import annotations

import logging
from typing import Any

import requests

from app.config import settings
from app.repositories.telegram_notification_repository import TelegramNotificationRepository

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
_UNSET = object()


def _format_price(value: float | int | None) -> str:
    if value is None:
        return "—"
    number = float(value)
    if number >= 1000 and number == int(number):
        return f"{int(number):,}"
    if number == int(number):
        return str(int(number))
    return f"{number:.2f}".rstrip("0").rstrip(".")


def _side_label(side: str) -> str:
    return "LONG" if side == "BUY" else "SHORT"


class TelegramService:
    def __init__(
        self,
        *,
        bot_token: str | None | object = _UNSET,
        chat_id: str | None | object = _UNSET,
        repository: TelegramNotificationRepository | None = None,
        session: requests.Session | None = None,
    ) -> None:
        self._bot_token_override = bot_token
        self._chat_id_override = chat_id
        self.repository = repository or TelegramNotificationRepository()
        self._session = session or requests.Session()

    @staticmethod
    def _clean(value: str | None) -> str | None:
        if not value:
            return None
        return str(value).strip().strip('"').strip("'")

    @property
    def bot_token(self) -> str | None:
        if self._bot_token_override is not _UNSET:
            return self._clean(self._bot_token_override)  # type: ignore[arg-type]
        return self._clean(settings.telegram_bot_token)

    @property
    def chat_id(self) -> str | None:
        if self._chat_id_override is not _UNSET:
            return self._clean(self._chat_id_override)  # type: ignore[arg-type]
        return self._clean(settings.telegram_chat_id)

    def is_configured(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    def status(self) -> dict[str, Any]:
        return {
            "configured": self.is_configured(),
            "chat_id_set": bool(self.chat_id),
            "bot_token_set": bool(self.bot_token),
        }

    def send_test(self) -> dict[str, Any]:
        text = (
            "✅ Delta Signal Engine\n\n"
            "Telegram test notification — your bot is connected."
        )
        ok = self._deliver(text)
        return {"ok": ok, "message": "Test notification sent" if ok else "Send failed — check logs"}

    def notify_signal_generated(self, signal: dict[str, Any]) -> bool:
        signal_id = int(signal["id"])
        dedupe_key = f"signal:{signal_id}:generated"
        if not self.repository.claim(
            dedupe_key,
            event_type="SIGNAL_GENERATED",
            entity_type="signal",
            entity_id=signal_id,
        ):
            return False
        text = self._format_new_signal(signal)
        return self._send_claimed(dedupe_key, text)

    def notify_trade_approved(
        self,
        signal: dict[str, Any],
        position: dict[str, Any],
    ) -> bool:
        signal_id = int(signal["id"])
        dedupe_key = f"signal:{signal_id}:approved"
        if not self.repository.claim(
            dedupe_key,
            event_type="TRADE_APPROVED",
            entity_type="signal",
            entity_id=signal_id,
        ):
            return False
        text = self._format_trade_approved(signal, position)
        return self._send_claimed(dedupe_key, text)

    def notify_position_closed(self, position: dict[str, Any]) -> bool:
        position_id = int(position["id"])
        reason = str(position.get("exit_reason") or "MANUAL").upper()
        event_map = {
            "TP": ("TP_HIT", "🎯 TP HIT"),
            "SL": ("SL_HIT", "🛑 SL HIT"),
            "MANUAL": ("MANUAL_CLOSE", "✋ POSITION CLOSED MANUALLY"),
        }
        event_type, heading = event_map.get(reason, ("POSITION_CLOSED", "📤 POSITION CLOSED"))
        dedupe_key = f"position:{position_id}:{event_type.lower()}"
        if not self.repository.claim(
            dedupe_key,
            event_type=event_type,
            entity_type="position",
            entity_id=position_id,
        ):
            return False
        text = self._format_position_closed(position, heading)
        return self._send_claimed(dedupe_key, text)

    def _format_new_signal(self, signal: dict[str, Any]) -> str:
        side = signal["side"]
        header = "🚀 BUY SIGNAL" if side == "BUY" else "🔻 SELL SIGNAL"
        tf = signal.get("timeframe") or signal.get("signal_timeframe") or "—"
        lines = [
            header,
            "",
            f"Symbol: {signal['symbol']}",
            f"TF: {tf}",
            f"Entry: {_format_price(signal['entry'])}",
            f"SL: {_format_price(signal['stop_loss'])}",
            f"TP: {_format_price(signal['take_profit'])}",
        ]
        if signal.get("risk_reward") is not None:
            lines.append(f"RR: {float(signal['risk_reward']):.1f}")
        lines.extend(["", "Status: PENDING APPROVAL"])
        return "\n".join(lines)

    def _format_trade_approved(
        self,
        signal: dict[str, Any],
        position: dict[str, Any],
    ) -> str:
        tf = signal.get("timeframe") or "—"
        return "\n".join(
            [
                "✅ TRADE APPROVED",
                "",
                f"Symbol: {signal['symbol']}",
                f"TF: {tf}",
                f"Side: {_side_label(signal['side'])}",
                f"Entry: {_format_price(position.get('entry', signal['entry']))}",
                f"SL: {_format_price(position.get('stop_loss', signal['stop_loss']))}",
                f"TP: {_format_price(position.get('take_profit', signal['take_profit']))}",
                f"Leverage: {float(position.get('leverage', 1)):.0f}x",
                f"Margin Used: {_format_price(position.get('margin_used'))}",
            ]
        )

    def _format_position_closed(self, position: dict[str, Any], heading: str) -> str:
        pnl = position.get("pnl")
        pnl_text = _format_price(pnl)
        if pnl is not None and float(pnl) > 0:
            pnl_text = f"+{pnl_text}"
        return "\n".join(
            [
                heading,
                "",
                f"Symbol: {position['symbol']}",
                f"Side: {_side_label(position['side'])}",
                f"Entry: {_format_price(position['entry'])}",
                f"Exit: {_format_price(position.get('exit_price'))}",
                f"PnL: {pnl_text}",
            ]
        )

    def _send_claimed(self, dedupe_key: str, text: str) -> bool:
        ok = self._deliver(text)
        preview = text.split("\n", 1)[0][:120]
        if ok:
            self.repository.mark_success(dedupe_key, message_preview=preview)
        else:
            self.repository.mark_failure(dedupe_key, "Telegram API request failed")
        return ok

    def _deliver(self, text: str) -> bool:
        if not self.is_configured():
            logger.warning("Telegram not configured — set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID")
            return False
        url = TELEGRAM_API.format(token=self.bot_token)
        try:
            response = self._session.post(
                url,
                json={
                    "chat_id": self.chat_id,
                    "text": text,
                    "disable_web_page_preview": True,
                },
                timeout=15,
            )
            if not response.ok:
                logger.error(
                    "Telegram send failed: HTTP %s %s",
                    response.status_code,
                    response.text[:300],
                )
                return False
            body = response.json()
            if not body.get("ok"):
                logger.error("Telegram API error: %s", body)
                return False
            logger.info("Telegram notification sent (%s chars)", len(text))
            return True
        except requests.RequestException as exc:
            logger.error("Telegram send error: %s", exc)
            return False


telegram_service = TelegramService()
