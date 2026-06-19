"""SMTP email alerts for signals and trades."""

from __future__ import annotations

import logging
import smtplib
import time
from email.mime.text import MIMEText
from typing import Any

from app.config import settings
from app.paper_trader import calculate_roe
from app.repositories.telegram_notification_repository import TelegramNotificationRepository
from app.services.telegram_service import _format_price, _side_label

logger = logging.getLogger(__name__)


def _side_label(side: str) -> str:
    return "LONG" if side == "BUY" else "SHORT"


def _signal_tf(record: dict[str, Any]) -> str:
    return str(record.get("signal_timeframe") or record.get("timeframe") or "—")


def _field_lines(fields: list[tuple[str, str]]) -> list[str]:
    return [f"{label}: {value}" for label, value in fields if value is not None]


class EmailService:
    def __init__(
        self,
        *,
        repository: TelegramNotificationRepository | None = None,
    ) -> None:
        self.repository = repository or TelegramNotificationRepository()

    def is_configured(self) -> bool:
        return bool(
            settings.smtp_server
            and settings.smtp_port
            and settings.smtp_username
            and settings.smtp_password
            and settings.alert_email_to
        )

    def status(self) -> dict[str, Any]:
        return {
            "configured": self.is_configured(),
            "smtp_server_set": bool(settings.smtp_server),
            "smtp_port_set": bool(settings.smtp_port),
            "smtp_username_set": bool(settings.smtp_username),
            "smtp_password_set": bool(settings.smtp_password),
            "alert_email_to_set": bool(settings.alert_email_to),
        }

    def send_test(self) -> dict[str, Any]:
        tf = _signal_tf({"timeframe": "5m"})
        body = "\n".join(
            [
                "Delta Signal Engine — Test Email",
                "",
                "Your SMTP configuration is working.",
                "",
                "Sample alert fields:",
                "Symbol: BTCUSDT",
                f"Signal TF: {tf}",
                "Entry: 105230",
                "SL: 104950",
                "TP: 105900",
                "RR: 2.4",
                "PnL: —",
                "ROE: —",
            ]
        )
        ok = self._send_once(
            subject="Delta Signal Engine — Test Email",
            body=body,
            dedupe_key=None,
        )
        return {"ok": ok, "message": "Test email sent" if ok else "Send failed — check logs"}

    def notify_signal_generated(self, signal: dict[str, Any]) -> bool:
        signal_id = int(signal["id"])
        side = signal["side"]
        tf = signal.get("timeframe") or signal.get("signal_timeframe") or "—"
        symbol = signal["symbol"]
        subject = f"{side} Signal - {symbol} ({tf})"
        body = self._format_new_signal(signal)
        dedupe_key = f"email:signal:{signal_id}:generated"
        return self._send_deduped(
            dedupe_key,
            subject=subject,
            body=body,
            event_type="SIGNAL_GENERATED",
            entity_type="signal",
            entity_id=signal_id,
        )

    def notify_trade_approved(
        self,
        signal: dict[str, Any],
        position: dict[str, Any],
    ) -> bool:
        signal_id = int(signal["id"])
        symbol = signal["symbol"]
        subject = f"Trade Approved - {symbol}"
        body = self._format_trade_approved(signal, position)
        dedupe_key = f"email:signal:{signal_id}:approved"
        return self._send_deduped(
            dedupe_key,
            subject=subject,
            body=body,
            event_type="TRADE_APPROVED",
            entity_type="signal",
            entity_id=signal_id,
        )

    def notify_position_closed(self, position: dict[str, Any]) -> bool:
        position_id = int(position["id"])
        symbol = position["symbol"]
        reason = str(position.get("exit_reason") or "MANUAL").upper()
        subject_map = {
            "TP": f"Take Profit Hit - {symbol}",
            "SL": f"Stop Loss Hit - {symbol}",
            "MANUAL": f"Position Closed - {symbol}",
        }
        event_map = {
            "TP": "TP_HIT",
            "SL": "SL_HIT",
            "MANUAL": "MANUAL_CLOSE",
        }
        subject = subject_map.get(reason, f"Position Closed - {symbol}")
        event_type = event_map.get(reason, "POSITION_CLOSED")
        body = self._format_position_closed(position, reason)
        dedupe_key = f"email:position:{position_id}:{event_type.lower()}"
        return self._send_deduped(
            dedupe_key,
            subject=subject,
            body=body,
            event_type=event_type,
            entity_type="position",
            entity_id=position_id,
        )

    def _format_new_signal(self, signal: dict[str, Any]) -> str:
        side = "BUY" if signal["side"] == "BUY" else "SELL"
        tf = _signal_tf(signal)
        rr = f"{float(signal['risk_reward']):.1f}" if signal.get("risk_reward") is not None else "—"
        lines = [
            f"{side} SIGNAL",
            "",
            *_field_lines(
                [
                    ("Symbol", signal["symbol"]),
                    ("Signal TF", tf),
                    ("Entry", _format_price(signal["entry"])),
                    ("SL", _format_price(signal["stop_loss"])),
                    ("TP", _format_price(signal["take_profit"])),
                    ("RR", rr),
                    ("PnL", "—"),
                    ("ROE", "—"),
                ]
            ),
            "",
            "Status: PENDING APPROVAL",
        ]
        return "\n".join(lines)

    def _format_trade_approved(
        self,
        signal: dict[str, Any],
        position: dict[str, Any],
    ) -> str:
        tf = _signal_tf(signal)
        rr_raw = signal.get("risk_reward")
        if rr_raw is None:
            rr_raw = position.get("risk_reward")
        rr = f"{float(rr_raw):.1f}" if rr_raw is not None else "—"
        return "\n".join(
            [
                "TRADE APPROVED",
                "",
                *_field_lines(
                    [
                        ("Symbol", signal["symbol"]),
                        ("Signal TF", tf),
                        ("Side", _side_label(signal["side"])),
                        ("Entry", _format_price(position.get("entry", signal["entry"]))),
                        ("SL", _format_price(position.get("stop_loss", signal["stop_loss"]))),
                        ("TP", _format_price(position.get("take_profit", signal["take_profit"]))),
                        ("RR", rr),
                        ("PnL", "—"),
                        ("ROE", "—"),
                    ]
                ),
                "",
                f"Leverage: {float(position.get('leverage', 1)):.0f}x",
                f"Margin Used: {_format_price(position.get('margin_used'))}",
            ]
        )

    def _format_position_closed(self, position: dict[str, Any], reason: str) -> str:
        pnl = position.get("pnl")
        margin = float(position.get("margin_used") or 0.0)
        roe = calculate_roe(float(pnl or 0), margin) if margin > 0 and pnl is not None else None
        rr_val = position.get("risk_reward")
        rr = f"{float(rr_val):.1f}" if rr_val is not None else "—"
        heading = {
            "TP": "TAKE PROFIT HIT",
            "SL": "STOP LOSS HIT",
            "MANUAL": "POSITION CLOSED MANUALLY",
        }.get(reason, "POSITION CLOSED")
        pnl_text = _format_price(pnl)
        if pnl is not None and float(pnl) > 0:
            pnl_text = f"+{pnl_text}"
        roe_text = f"{roe:.2f}%" if roe is not None else "—"
        return "\n".join(
            [
                heading,
                "",
                *_field_lines(
                    [
                        ("Symbol", position["symbol"]),
                        ("Signal TF", "—"),
                        ("Side", _side_label(position["side"])),
                        ("Entry", _format_price(position["entry"])),
                        ("SL", _format_price(position.get("stop_loss"))),
                        ("TP", _format_price(position.get("take_profit"))),
                        ("RR", rr),
                        ("PnL", pnl_text),
                        ("ROE", roe_text),
                    ]
                ),
                "",
                f"Exit: {_format_price(position.get('exit_price'))}",
            ]
        )

    def _send_deduped(
        self,
        dedupe_key: str,
        *,
        subject: str,
        body: str,
        event_type: str,
        entity_type: str,
        entity_id: int,
    ) -> bool:
        if not self.repository.claim(
            dedupe_key,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
        ):
            logger.debug("Email skip duplicate: %s", dedupe_key)
            return False
        ok = self._send_once(subject=subject, body=body, dedupe_key=dedupe_key)
        preview = subject[:120]
        if ok:
            self.repository.mark_success(dedupe_key, message_preview=preview)
        else:
            self.repository.mark_failure(dedupe_key, "SMTP send failed")
        return ok

    def _send_once(
        self,
        *,
        subject: str,
        body: str,
        dedupe_key: str | None,
    ) -> bool:
        if not self.is_configured():
            logger.warning(
                "Email not configured — set SMTP_SERVER, SMTP_PORT, SMTP_USERNAME, "
                "SMTP_PASSWORD, ALERT_EMAIL_TO"
            )
            return False

        try:
            self._deliver(subject, body)
            logger.info("Email sent: subject=%r dedupe=%s", subject, dedupe_key or "test")
            return True
        except Exception as exc:
            logger.error("Email send failed (attempt 1): %s", exc)
            time.sleep(1.0)
            try:
                self._deliver(subject, body)
                logger.info("Email sent on retry: subject=%r", subject)
                return True
            except Exception as retry_exc:
                logger.error("Email send failed (attempt 2): %s", retry_exc)
                return False

    def _deliver(self, subject: str, body: str) -> None:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = settings.smtp_username
        msg["To"] = settings.alert_email_to

        port = int(settings.smtp_port or 587)
        password = (settings.smtp_password or "").strip().strip('"').strip("'")
        username = (settings.smtp_username or "").strip()

        if port == 465:
            with smtplib.SMTP_SSL(settings.smtp_server, port, timeout=20) as server:
                server.login(username, password)
                server.sendmail(username, [settings.alert_email_to], msg.as_string())
            return

        with smtplib.SMTP(settings.smtp_server, port, timeout=20) as server:
            server.ehlo()
            if port == 587:
                server.starttls()
                server.ehlo()
            server.login(username, password)
            server.sendmail(username, [settings.alert_email_to], msg.as_string())


email_service = EmailService()
