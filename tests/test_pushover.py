"""Tests for Pushover notifications."""

import time
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.alert_service import AlertService
from app.services.pushover_service import PushoverService
from tests.conftest import utc_now_iso

client = TestClient(app)

VALID_USER_KEY = "u3Fpz9uT6vj1c5FkJrC858Xy9iP5Xq"
VALID_APP_TOKEN = "a4m45hkhm36iig7moh1s1er32onkqs"


def _wait_for_notifications() -> None:
    time.sleep(0.3)


@pytest.fixture()
def pushover_env(monkeypatch):
    monkeypatch.setattr("app.services.pushover_service.settings.pushover_enabled", "true")
    monkeypatch.setattr("app.services.pushover_service.settings.pushover_user_key", VALID_USER_KEY)
    monkeypatch.setattr("app.services.pushover_service.settings.pushover_app_token", VALID_APP_TOKEN)


@pytest.fixture()
def mock_pushover_post(monkeypatch, pushover_env):
    mock_response = MagicMock()
    mock_response.ok = True
    mock_response.json.return_value = {"status": 1, "request": "abc"}
    session = MagicMock()
    session.post.return_value = mock_response
    service = PushoverService(
        enabled=True,
        user_key=VALID_USER_KEY,
        app_token=VALID_APP_TOKEN,
        session=session,
    )
    from app.services.email_service import EmailService
    from app.services.telegram_service import TelegramService

    mock_email = MagicMock(spec=EmailService)
    mock_email.notify_signal_generated.return_value = False
    mock_email.notify_trade_approved.return_value = False
    mock_email.notify_position_closed.return_value = False

    mock_tg = MagicMock(spec=TelegramService)
    mock_tg.notify_signal_generated.return_value = False
    mock_tg.notify_trade_approved.return_value = False
    mock_tg.notify_position_closed.return_value = False

    alerts = AlertService(telegram=mock_tg, email=mock_email, pushover=service, blocking=True)

    from app import approval_api
    from app import paper_api

    monkeypatch.setattr(approval_api.signal_service, "alerts", alerts)
    monkeypatch.setattr(paper_api.paper_service, "alerts", alerts)
    monkeypatch.setattr("app.pushover_api.pushover_service", service)
    return session


def test_pushover_status_unconfigured():
    service = PushoverService(enabled=False, user_key=None, app_token=None)
    assert service.is_configured() is False


def test_pushover_status_configured(pushover_env):
    service = PushoverService()
    assert service.is_configured() is True


def test_pushover_status_endpoint(temp_db, pushover_env):
    resp = client.get("/pushover/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is True
    assert body["configured"] is True


def test_pushover_test_not_configured(temp_db, monkeypatch):
    unconfigured = PushoverService(enabled=False, user_key=None, app_token=None)
    monkeypatch.setattr("app.pushover_api.pushover_service", unconfigured)
    resp = client.post("/pushover/test")
    assert resp.status_code == 503


def test_pushover_test_success(temp_db, mock_pushover_post):
    resp = client.post("/pushover/test")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    mock_pushover_post.post.assert_called_once()


def test_signal_pushover_sent_once(temp_db, mock_pushover_post):
    from app.approval_api import signal_service

    ts = utc_now_iso()
    record = signal_service.persist_detected_signal(
        symbol="BTCUSDT",
        timeframe="5m",
        side="BUY",
        entry=62467.0,
        hh50=62794.0,
        ll50=62304.0,
        created_at=ts,
    )
    assert record is not None
    assert mock_pushover_post.post.call_count == 1
    call = mock_pushover_post.post.call_args
    assert call.kwargs["data"]["title"] == "🚀 BTCUSDT BUY"
    assert "62,467" in call.kwargs["data"]["message"]
    assert "Pending Approval" in call.kwargs["data"]["message"]

    signal_service.persist_detected_signal(
        symbol="BTCUSDT",
        timeframe="5m",
        side="BUY",
        entry=62467.0,
        hh50=62794.0,
        ll50=62304.0,
        created_at=ts,
    )
    assert mock_pushover_post.post.call_count == 1


def test_pushover_retry_on_failure(temp_db, pushover_env):
    session = MagicMock()
    bad = MagicMock()
    bad.ok = False
    bad.text = "error"
    bad.status_code = 500
    good = MagicMock()
    good.ok = True
    good.json.return_value = {"status": 1}
    session.post.side_effect = [bad, good]

    service = PushoverService(
        enabled=True,
        user_key=VALID_USER_KEY,
        app_token=VALID_APP_TOKEN,
        session=session,
    )
    result = service.send_test()
    assert result["ok"] is True
    assert session.post.call_count == 2


def test_sell_signal_format(temp_db, mock_pushover_post):
    service = PushoverService(
        enabled=True,
        user_key=VALID_USER_KEY,
        app_token=VALID_APP_TOKEN,
        session=mock_pushover_post,
    )
    service.notify_signal_generated(
        {
            "id": 99,
            "symbol": "ETHUSDT",
            "side": "SELL",
            "timeframe": "5m",
            "entry": 3500.0,
            "stop_loss": 3550.0,
            "take_profit": 3400.0,
            "risk_reward": 2.0,
        }
    )
    call = mock_pushover_post.post.call_args
    assert call.kwargs["data"]["title"] == "🔻 ETHUSDT SELL"


def test_alert_service_non_blocking(temp_db, monkeypatch, pushover_env):
    session = MagicMock()
    response = MagicMock()
    response.ok = True
    response.json.return_value = {"status": 1}
    session.post.return_value = response
    service = PushoverService(
        enabled=True,
        user_key=VALID_USER_KEY,
        app_token=VALID_APP_TOKEN,
        session=session,
    )
    alerts = AlertService(pushover=service, blocking=False)
    alerts.notify_signal_generated(
        {
            "id": 1,
            "symbol": "BTCUSDT",
            "side": "BUY",
            "timeframe": "5m",
            "entry": 1.0,
            "stop_loss": 0.9,
            "take_profit": 1.2,
        }
    )
    assert session.post.call_count == 0
    _wait_for_notifications()
    assert session.post.call_count == 1
