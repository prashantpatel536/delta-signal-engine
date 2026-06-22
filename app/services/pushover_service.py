"""Pushover mobile push notifications for signals and trades."""

from __future__ import annotations

import logging
import time
from typing import Any

import requests

from app.config import settings
from app.paper_trader import calculate_roe
from app.repositories.telegram_notification_repository import TelegramNotificationRepository
from app.services.telegram_service import _format_price, _side_label

logger = logging.getLogger(__name__)

PUSHOVER_API = "https://api.pushover.net/1/messages.json"
PUSHOVER_KEY_LEN = 30
_UNSET = object()


def _key_format_ok(value: str | None) -> bool:
    cleaned = PushoverService._clean(value)
    return bool(cleaned and len(cleaned) == PUSHOVER_KEY_LEN and cleaned.isalnum())


def _parse_pushover_error(exc: requests.RequestException) -> str:
    text = str(exc)
    if "application token is invalid" in text:
        return (
            "Invalid app token — create an application at pushover.net/apps/build "
            "and paste the 30-character API token into PUSHOVER_APP_TOKEN"
        )
    if "user is invalid" in text or '"user":"invalid"' in text:
        return (
            "Invalid user key — copy your 30-character user key from the Pushover dashboard "
            "into PUSHOVER_USER_KEY"
        )
    if "HTTP 400" in text and "errors" in text:
        try:
            import json

            payload = text.split("HTTP 400: ", 1)[1]
            body = json.loads(payload)
            errors = body.get("errors") or []
            if errors:
                return "; ".join(str(e) for e in errors)
        except (IndexError, json.JSONDecodeError, TypeError):
            pass
    return "Pushover API request failed — check server logs"


def _signal_tf(record: dict[str, Any]) -> str:
    return str(record.get("signal_timeframe") or record.get("timeframe") or "—")


class PushoverService:
    def __init__(
        self,
        *,
        user_key: str | None | object = _UNSET,
        app_token: str | None | object = _UNSET,
        enabled: bool | None | object = _UNSET,
        repository: TelegramNotificationRepository | None = None,
        session: requests.Session | None = None,
    ) -> None:
        self._user_key_override = user_key
        self._app_token_override = app_token
        self._enabled_override = enabled
        self.repository = repository or TelegramNotificationRepository()
        self._session = session or requests.Session()

    @staticmethod
    def _clean(value: str | None) -> str | None:
        if not value:
            return None
        return str(value).strip().strip('"').strip("'")

    @staticmethod
    def _parse_enabled(value: str | None) -> bool:
        if value is None:
            return False
        return str(value).strip().lower() in ("1", "true", "yes", "on")

    @property
    def enabled(self) -> bool:
        if self._enabled_override is not _UNSET:
            return bool(self._enabled_override)  # type: ignore[arg-type]
        return self._parse_enabled(settings.pushover_enabled)

    @property
    def user_key(self) -> str | None:
        if self._user_key_override is not _UNSET:
            return self._clean(self._user_key_override)  # type: ignore[arg-type]
        return self._clean(settings.pushover_user_key)

    @property
    def app_token(self) -> str | None:
        if self._app_token_override is not _UNSET:
            return self._clean(self._app_token_override)  # type: ignore[arg-type]
        return self._clean(settings.pushover_app_token)

    def is_configured(self) -> bool:
        return (
            self.enabled
            and _key_format_ok(self.user_key)
            and _key_format_ok(self.app_token)
        )

    def status(self) -> dict[str, Any]:
        user_ok = _key_format_ok(self.user_key)
        token_ok = _key_format_ok(self.app_token)
        hint: str | None = None
        if self.enabled:
            if not self.user_key:
                hint = "Set PUSHOVER_USER_KEY in .env (30-character key from pushover.net)"
            elif not user_ok:
                hint = "PUSHOVER_USER_KEY must be exactly 30 alphanumeric characters"
            elif not self.app_token:
                hint = "Set PUSHOVER_APP_TOKEN in .env (30-character token from pushover.net/apps/build)"
            elif not token_ok:
                hint = (
                    "PUSHOVER_APP_TOKEN must be exactly 30 alphanumeric characters "
                    "(create an app at pushover.net/apps/build)"
                )
        return {
            "configured": self.is_configured(),
            "enabled": self.enabled,
            "user_key_set": bool(self.user_key),
            "app_token_set": bool(self.app_token),
            "user_key_valid": user_ok,
            "app_token_valid": token_ok,
            "config_hint": hint,
        }

    def send_test(self) -> dict[str, Any]:
        title = "Delta Signal Engine"
        message = "\n".join(
            [
                "✅ Pushover test notification",
                "",
                "🚀 BTCUSDT BUY",
                "TF: 5m",
                "Entry: 62467",
                "SL: 62304",
                "TP: 62794",
                "Status: Pending Approval",
            ]
        )
        ok, error = self._send_once(title=title, message=message, dedupe_key=None)
        return {
            "ok": ok,
            "message": "Test Pushover notification sent" if ok else error,
        }

    def notify_signal_generated(self, signal: dict[str, Any]) -> bool:
        signal_id = int(signal["id"])
        dedupe_key = f"pushover:signal:{signal_id}:generated"
        if not self.repository.claim(
            dedupe_key,
            event_type="SIGNAL_GENERATED",
            entity_type="signal",
            entity_id=signal_id,
        ):
            return False
        title, message = self._format_new_signal(signal)
        return self._send_claimed(dedupe_key, title, message)

    def notify_trade_approved(
        self,
        signal: dict[str, Any],
        position: dict[str, Any],
    ) -> bool:
        signal_id = int(signal["id"])
        dedupe_key = f"pushover:signal:{signal_id}:approved"
        if not self.repository.claim(
            dedupe_key,
            event_type="TRADE_APPROVED",
            entity_type="signal",
            entity_id=signal_id,
        ):
            return False
        title, message = self._format_trade_approved(signal, position)
        return self._send_claimed(dedupe_key, title, message)

    def notify_position_closed(self, position: dict[str, Any]) -> bool:
        position_id = int(position["id"])
        reason = str(position.get("exit_reason") or "MANUAL").upper()
        event_map = {
            "TP": ("TP_HIT", "🎯 TP HIT"),
            "SL": ("SL_HIT", "🛑 SL HIT"),
            "MANUAL": ("MANUAL_CLOSE", "✋ POSITION CLOSED"),
        }
        event_type, heading = event_map.get(reason, ("POSITION_CLOSED", "📤 POSITION CLOSED"))
        dedupe_key = f"pushover:position:{position_id}:{event_type.lower()}"
        if not self.repository.claim(
            dedupe_key,
            event_type=event_type,
            entity_type="position",
            entity_id=position_id,
        ):
            return False
        title, message = self._format_position_closed(position, heading)
        return self._send_claimed(dedupe_key, title, message)

    def _format_new_signal(self, signal: dict[str, Any]) -> tuple[str, str]:
        side = signal["side"]
        emoji = "🚀" if side == "BUY" else "🔻"
        title = f"{emoji} {signal['symbol']} {side}"
        tf = _signal_tf(signal)
        lines = [
            f"TF: {tf}",
            f"Entry: {_format_price(signal['entry'])}",
            f"SL: {_format_price(signal['stop_loss'])}",
            f"TP: {_format_price(signal['take_profit'])}",
            "Status: Pending Approval",
        ]
        if signal.get("risk_reward") is not None:
            lines.insert(1, f"RR: {float(signal['risk_reward']):.1f}")
        return title, "\n".join(lines)

    def _format_trade_approved(
        self,
        signal: dict[str, Any],
        position: dict[str, Any],
    ) -> tuple[str, str]:
        title = f"✅ Trade Approved — {signal['symbol']}"
        tf = _signal_tf(signal)
        message = "\n".join(
            [
                f"TF: {tf}",
                f"Side: {_side_label(signal['side'])}",
                f"Entry: {_format_price(position.get('entry', signal['entry']))}",
                f"SL: {_format_price(position.get('stop_loss', signal['stop_loss']))}",
                f"TP: {_format_price(position.get('take_profit', signal['take_profit']))}",
                f"Leverage: {float(position.get('leverage', 1)):.0f}x",
            ]
        )
        return title, message

    def _format_position_closed(
        self,
        position: dict[str, Any],
        heading: str,
    ) -> tuple[str, str]:
        pnl = position.get("pnl")
        margin = float(position.get("margin_used") or 0.0)
        roe = calculate_roe(float(pnl or 0), margin) if margin > 0 and pnl is not None else None
        pnl_text = _format_price(pnl)
        if pnl is not None and float(pnl) > 0:
            pnl_text = f"+{pnl_text}"
        title = f"{heading} — {position['symbol']}"
        message = "\n".join(
            [
                f"Side: {_side_label(position['side'])}",
                f"Entry: {_format_price(position['entry'])}",
                f"Exit: {_format_price(position.get('exit_price'))}",
                f"PnL: {pnl_text}",
                f"ROE: {roe:.2f}%" if roe is not None else "ROE: —",
            ]
        )
        return title, message

    def _send_claimed(self, dedupe_key: str, title: str, message: str) -> bool:
        ok, error = self._send_once(title=title, message=message, dedupe_key=dedupe_key)
        preview = title[:120]
        if ok:
            self.repository.mark_success(dedupe_key, message_preview=preview)
        else:
            self.repository.mark_failure(dedupe_key, error or "Pushover API request failed")
        return ok

    def _send_once(
        self,
        *,
        title: str,
        message: str,
        dedupe_key: str | None,
    ) -> tuple[bool, str | None]:
        if not self.is_configured():
            logger.debug("Pushover skipped — not enabled or invalid credentials")
            return False, self.status().get("config_hint") or "Pushover not configured"

        try:
            self._deliver(title, message)
            logger.info(
                "Pushover sent: title=%r dedupe=%s",
                title,
                dedupe_key or "test",
            )
            return True, None
        except requests.RequestException as exc:
            logger.error("Pushover send failed (attempt 1): %s", exc)
            time.sleep(1.0)
            try:
                self._deliver(title, message)
                logger.info("Pushover sent on retry: title=%r", title)
                return True, None
            except requests.RequestException as retry_exc:
                logger.error("Pushover send failed (attempt 2): %s", retry_exc)
                return False, _parse_pushover_error(retry_exc)

    def _deliver(self, title: str, message: str) -> None:
        response = self._session.post(
            PUSHOVER_API,
            data={
                "token": self.app_token,
                "user": self.user_key,
                "title": title,
                "message": message,
            },
            timeout=15,
        )
        if not response.ok:
            raise requests.RequestException(
                f"HTTP {response.status_code}: {response.text[:300]}"
            )
        body = response.json()
        if body.get("status") != 1:
            raise requests.RequestException(f"Pushover API error: {body}")


pushover_service = PushoverService()
