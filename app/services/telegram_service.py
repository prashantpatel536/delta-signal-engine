"""Telegram Bot API notifications for signals and trades."""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

import requests

from app.config import settings
from app.repositories.telegram_notification_repository import TelegramNotificationRepository

logger = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org"
TELEGRAM_SEND_MESSAGE = TELEGRAM_API_BASE + "/bot{token}/sendMessage"
TELEGRAM_GET_ME = TELEGRAM_API_BASE + "/bot{token}/getMe"
BOT_TOKEN_RE = re.compile(r"^\d+:[A-Za-z0-9_-]{30,}$")
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


def _bot_token_format_ok(token: str | None) -> bool:
    return bool(token and BOT_TOKEN_RE.match(token))


def _parse_telegram_error(exc: requests.RequestException | str, response_text: str = "") -> str:
    if response_text:
        try:
            body = json.loads(response_text)
            code = body.get("error_code")
            description = str(body.get("description") or "").lower()
            if code == 404 or description == "not found":
                return (
                    "Invalid bot token — open @BotFather, select your bot, tap "
                    "API Token, copy the full token into TELEGRAM_BOT_TOKEN, and restart"
                )
            if code == 401 or "unauthorized" in description:
                return "Invalid bot token — regenerate it with @BotFather and update .env"
            if "chat not found" in description:
                return (
                    "Invalid chat ID — open your bot in Telegram, send /start, then copy "
                    "your chat ID from @userinfobot into TELEGRAM_CHAT_ID"
                )
            if "bot was blocked by the user" in description:
                return "Bot blocked — open Telegram, find your bot, and tap Start"
            if description:
                return str(body.get("description"))
        except (json.JSONDecodeError, TypeError, AttributeError):
            pass

    text = f"{exc} {response_text}".lower()
    if "connecttimeout" in text or "timed out" in text or "failed to establish" in text:
        return (
            "Cannot reach api.telegram.org — Telegram is likely blocked on this network. "
            "Use Pushover/Email, run the app on a network that can reach Telegram, "
            "or set TELEGRAM_PROXY in .env"
        )
    if "chat not found" in text:
        return (
            "Invalid chat ID — open your bot in Telegram, send /start, then copy your chat ID "
            "from @userinfobot into TELEGRAM_CHAT_ID"
        )
    if "bot was blocked by the user" in text:
        return "Bot blocked — open Telegram, find your bot, and tap Start"
    if "unauthorized" in text or "401" in text:
        return "Invalid bot token — check TELEGRAM_BOT_TOKEN from @BotFather"
    if "not found" in text and "error_code" in text:
        return (
            "Invalid bot token — open @BotFather, regenerate the API token, "
            "update TELEGRAM_BOT_TOKEN in .env, and restart"
        )
    if response_text:
        return response_text[:240]
    return "Telegram API request failed — check server logs"


class TelegramService:
    def __init__(
        self,
        *,
        bot_token: str | None | object = _UNSET,
        chat_id: str | None | object = _UNSET,
        proxy: str | None | object = _UNSET,
        repository: TelegramNotificationRepository | None = None,
        session: requests.Session | None = None,
    ) -> None:
        self._bot_token_override = bot_token
        self._chat_id_override = chat_id
        self._proxy_override = proxy
        self.repository = repository or TelegramNotificationRepository()
        self._session = session or requests.Session()
        if session is None:
            from app.ssl_utils import configure_requests_session

            configure_requests_session(self._session)

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

    @property
    def proxy(self) -> str | None:
        if self._proxy_override is not _UNSET:
            return self._clean(self._proxy_override)  # type: ignore[arg-type]
        return self._clean(settings.telegram_proxy)

    def is_configured(self) -> bool:
        return bool(_bot_token_format_ok(self.bot_token) and self.chat_id)

    def status(self) -> dict[str, Any]:
        token_ok = _bot_token_format_ok(self.bot_token)
        hint: str | None = None
        if self.bot_token and not token_ok:
            hint = (
                "TELEGRAM_BOT_TOKEN format looks wrong — copy the full token from @BotFather "
                "(looks like 123456789:AAHxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx)"
            )
        elif self.is_configured() and self._last_error:
            hint = self._last_error
        elif self.is_configured() and self.proxy:
            hint = f"Using proxy {self.proxy}"
        return {
            "configured": self.is_configured(),
            "chat_id_set": bool(self.chat_id),
            "bot_token_set": bool(self.bot_token),
            "bot_token_valid": token_ok,
            "proxy_set": bool(self.proxy),
            "last_error": self._last_error,
            "config_hint": hint,
        }

    def send_test(self) -> dict[str, Any]:
        verify = self.verify_bot()
        if not verify["ok"]:
            return {"ok": False, "message": verify["message"]}

        text = (
            "✅ Delta Signal Engine\n\n"
            "Telegram test notification — your bot is connected."
        )
        ok, error = self._deliver(text)
        message = "Test notification sent" if ok else (error or "Send failed — check logs")
        return {"ok": ok, "message": message}

    def verify_bot(self) -> dict[str, Any]:
        if not self.bot_token:
            return {"ok": False, "message": "Missing TELEGRAM_BOT_TOKEN"}
        url = TELEGRAM_GET_ME.format(token=self.bot_token)
        try:
            response = self._session.get(url, timeout=15, proxies=self._proxies())
            if not response.ok:
                message = _parse_telegram_error("", response.text[:300])
                self._last_error = message
                return {"ok": False, "message": message}
            body = response.json()
            if not body.get("ok"):
                message = _parse_telegram_error("", str(body))
                self._last_error = message
                return {"ok": False, "message": message}
            username = body.get("result", {}).get("username")
            self._last_error = None
            return {
                "ok": True,
                "message": f"Bot verified (@{username})" if username else "Bot verified",
            }
        except requests.RequestException as exc:
            message = _parse_telegram_error(exc)
            self._last_error = message
            return {"ok": False, "message": message}

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

    def _proxies(self) -> dict[str, str] | None:
        if not self.proxy:
            return None
        return {"http": self.proxy, "https": self.proxy}

    def _send_claimed(self, dedupe_key: str, text: str) -> bool:
        ok, _error = self._deliver(text)
        preview = text.split("\n", 1)[0][:120]
        if ok:
            self.repository.mark_success(dedupe_key, message_preview=preview)
        else:
            self.repository.mark_failure(dedupe_key, self._last_error or "Telegram API request failed")
        return ok

    def _deliver(self, text: str) -> tuple[bool, str | None]:
        if not self.is_configured():
            message = "Telegram not configured — set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID"
            logger.warning(message)
            self._last_error = message
            return False, message

        url = TELEGRAM_SEND_MESSAGE.format(token=self.bot_token)
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "disable_web_page_preview": True,
        }

        for attempt in (1, 2):
            try:
                response = self._session.post(
                    url,
                    json=payload,
                    timeout=15,
                    proxies=self._proxies(),
                )
                if not response.ok:
                    message = _parse_telegram_error("", response.text[:300])
                    logger.error(
                        "Telegram send failed (attempt %s): HTTP %s %s",
                        attempt,
                        response.status_code,
                        response.text[:300],
                    )
                    if attempt == 1:
                        time.sleep(1.0)
                        continue
                    self._last_error = message
                    return False, message
                body = response.json()
                if not body.get("ok"):
                    message = _parse_telegram_error("", str(body))
                    logger.error("Telegram API error (attempt %s): %s", attempt, body)
                    if attempt == 1:
                        time.sleep(1.0)
                        continue
                    self._last_error = message
                    return False, message
                logger.info("Telegram notification sent (%s chars)", len(text))
                self._last_error = None
                return True, None
            except requests.RequestException as exc:
                message = _parse_telegram_error(exc)
                logger.error("Telegram send error (attempt %s): %s", attempt, exc)
                if attempt == 1:
                    time.sleep(1.0)
                    continue
                self._last_error = message
                return False, message
        return False, self._last_error


telegram_service = TelegramService()
