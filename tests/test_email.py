"""Tests for SMTP email notifications."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.repositories.telegram_notification_repository import TelegramNotificationRepository
from app.services.email_service import EmailService
from app.services.alert_service import AlertService
from app.services.signal_service import SignalService
from tests.conftest import utc_now_iso

client = TestClient(app)


@pytest.fixture()
def smtp_env(monkeypatch):
    monkeypatch.setattr("app.services.email_service.settings.smtp_server", "smtp.test.com")
    monkeypatch.setattr("app.services.email_service.settings.smtp_port", 587)
    monkeypatch.setattr("app.services.email_service.settings.smtp_username", "user@test.com")
    monkeypatch.setattr("app.services.email_service.settings.smtp_password", "secret")
    monkeypatch.setattr("app.services.email_service.settings.alert_email_to", "alert@test.com")


@pytest.fixture()
def mock_smtp():
    with patch("app.services.email_service.smtplib.SMTP") as smtp_cls:
        server = MagicMock()
        smtp_cls.return_value.__enter__.return_value = server
        yield server


@pytest.fixture()
def alert_mocks(monkeypatch, smtp_env, mock_smtp):
    tg_session = MagicMock()
    tg_response = MagicMock()
    tg_response.ok = True
    tg_response.json.return_value = {"ok": True}
    tg_session.post.return_value = tg_response

    from app.services.telegram_service import TelegramService

    tg = TelegramService(bot_token="tok", chat_id="1", session=tg_session)
    email = EmailService()
    alerts = AlertService(telegram=tg, email=email)

    from app import approval_api
    from app import paper_api

    monkeypatch.setattr(approval_api.signal_service, "alerts", alerts)
    monkeypatch.setattr(paper_api.paper_service, "alerts", alerts)
    monkeypatch.setattr("app.telegram_api.telegram_service", tg)
    return mock_smtp


def test_email_status_unconfigured(temp_db, monkeypatch):
    monkeypatch.setattr("app.services.email_service.settings.smtp_server", None)
    monkeypatch.setattr("app.services.email_service.settings.smtp_username", None)
    service = EmailService()
    assert service.is_configured() is False


def test_email_status_endpoint(temp_db, smtp_env):
    resp = client.get("/email/status")
    assert resp.status_code == 200
    assert resp.json()["configured"] is True


def test_email_test_success(temp_db, smtp_env, mock_smtp):
    resp = client.post("/test-email")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    mock_smtp.sendmail.assert_called()


def test_test_email_alias(temp_db, smtp_env, mock_smtp):
    resp = client.post("/email/test")
    assert resp.status_code == 200


def test_email_test_not_configured(temp_db, monkeypatch):
    monkeypatch.setattr("app.services.email_service.settings.smtp_server", None)
    monkeypatch.setattr("app.settings_api.email_service", EmailService())
    resp = client.post("/test-email")
    assert resp.status_code == 503


def test_signal_email_sent_once(temp_db, alert_mocks, smtp_env):
    from app.approval_api import signal_service

    ts = utc_now_iso()
    record = signal_service.persist_detected_signal(
        symbol="BTCUSDT",
        timeframe="5m",
        side="BUY",
        entry=105230.0,
        hh50=105900.0,
        ll50=104950.0,
        created_at=ts,
    )
    assert record is not None
    assert alert_mocks.sendmail.call_count == 1

    again = signal_service.persist_detected_signal(
        symbol="BTCUSDT",
        timeframe="5m",
        side="BUY",
        entry=105230.0,
        hh50=105900.0,
        ll50=104950.0,
        created_at=ts,
    )
    assert again is None
    assert alert_mocks.sendmail.call_count == 1


def test_email_retry_on_failure(temp_db, smtp_env):
    service = EmailService()
    with patch("app.services.email_service.smtplib.SMTP") as smtp_cls:
        server = MagicMock()
        smtp_cls.return_value.__enter__.return_value = server
        server.sendmail.side_effect = [OSError("fail"), None]
        ok = service.send_test()["ok"]
    assert ok is True
    assert server.sendmail.call_count == 2


def test_email_failure_does_not_raise(temp_db, smtp_env):
    service = EmailService()
    with patch("app.services.email_service.smtplib.SMTP") as smtp_cls:
        server = MagicMock()
        smtp_cls.return_value.__enter__.return_value = server
        server.sendmail.side_effect = OSError("permanent fail")
        ok = service.send_test()["ok"]
    assert ok is False

    signal_service = SignalService(alerts=AlertService(email=service))
    record = signal_service.persist_detected_signal(
        symbol="ETHUSDT",
        timeframe="5m",
        side="BUY",
        entry=100.0,
        hh50=110.0,
        ll50=95.0,
        created_at=utc_now_iso(),
    )
    assert record is not None


def test_email_dedupe_keys_separate_from_telegram(temp_db):
    repo = TelegramNotificationRepository()
    assert repo.claim("email:signal:1:generated", event_type="X", entity_type="signal", entity_id=1)
    assert repo.claim("signal:1:generated", event_type="X", entity_type="signal", entity_id=1)


def test_email_body_includes_all_fields():
    service = EmailService()
    text = service._format_new_signal(
        {
            "id": 1,
            "symbol": "BTCUSDT",
            "timeframe": "5m",
            "side": "BUY",
            "entry": 105230,
            "stop_loss": 104950,
            "take_profit": 105900,
            "risk_reward": 2.4,
        }
    )
    for field in ("Symbol:", "Signal TF: 5m", "Entry:", "SL:", "TP:", "RR:", "PnL:", "ROE:"):
        assert field in text
