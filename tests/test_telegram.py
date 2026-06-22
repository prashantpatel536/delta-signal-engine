"""Tests for Telegram notifications."""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.repositories.telegram_notification_repository import TelegramNotificationRepository
from app.services.signal_service import SignalService
from app.services.alert_service import AlertService
from app.services.telegram_service import TelegramService
from app.services.paper_trading_service import PaperTradingService
from tests.conftest import utc_now_iso

client = TestClient(app)


@pytest.fixture()
def mock_telegram_post(monkeypatch):
    mock_response = MagicMock()
    mock_response.ok = True
    mock_response.json.return_value = {"ok": True}
    session = MagicMock()
    session.post.return_value = mock_response
    service = TelegramService(
        bot_token="test-token",
        chat_id="12345",
        session=session,
    )
    from app.services.alert_service import AlertService
    from app.services.email_service import EmailService

    mock_email = MagicMock(spec=EmailService)
    mock_email.notify_signal_generated.return_value = False
    mock_email.notify_trade_approved.return_value = False
    mock_email.notify_position_closed.return_value = False
    alerts = AlertService(telegram=service, email=mock_email)

    from app import approval_api
    from app import paper_api

    monkeypatch.setattr(approval_api.signal_service, "alerts", alerts)
    monkeypatch.setattr(paper_api.paper_service, "alerts", alerts)
    monkeypatch.setattr("app.main.paper_service", paper_api.paper_service)
    monkeypatch.setattr("app.telegram_api.telegram_service", service)
    return session


def test_telegram_status_unconfigured():
    service = TelegramService(bot_token=None, chat_id=None)
    assert service.is_configured() is False


def test_telegram_status_endpoint(temp_db):
    resp = client.get("/telegram/status")
    assert resp.status_code == 200
    body = resp.json()
    assert "configured" in body
    assert "bot_token_set" in body


def test_telegram_test_not_configured(temp_db, monkeypatch):
    unconfigured = TelegramService(bot_token=None, chat_id=None)
    monkeypatch.setattr("app.telegram_api.telegram_service", unconfigured)
    resp = client.post("/telegram/test")
    assert resp.status_code == 503


def test_telegram_test_success(temp_db, mock_telegram_post):
    resp = client.post("/telegram/test")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    mock_telegram_post.post.assert_called_once()


def test_signal_generated_sends_once(temp_db, mock_telegram_post):
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
    assert mock_telegram_post.post.call_count == 1

    # Second persist for same candle is skipped — no duplicate Telegram
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
    assert mock_telegram_post.post.call_count == 1


def test_signal_message_format_buy():
    service = TelegramService(bot_token="t", chat_id="1")
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
    assert "🚀 BUY SIGNAL" in text
    assert "Status: PENDING APPROVAL" in text
    assert "RR: 2.4" in text


def test_signal_message_format_sell():
    service = TelegramService(bot_token="t", chat_id="1")
    text = service._format_new_signal(
        {
            "id": 2,
            "symbol": "ETHUSDT",
            "timeframe": "5m",
            "side": "SELL",
            "entry": 3500,
            "stop_loss": 3550,
            "take_profit": 3400,
            "risk_reward": 2.0,
        }
    )
    assert "🔻 SELL SIGNAL" in text
    assert "ETHUSDT" in text


def test_dedupe_repository(temp_db):
    repo = TelegramNotificationRepository()
    assert repo.claim("signal:1:generated", event_type="X", entity_type="signal", entity_id=1)
    assert not repo.claim("signal:1:generated", event_type="X", entity_type="signal", entity_id=1)


def test_telegram_failure_does_not_raise(temp_db, monkeypatch):
    session = MagicMock()
    session.post.side_effect = ConnectionError("network down")
    tg = TelegramService(bot_token="tok", chat_id="99", session=session)
    signal_service = SignalService(alerts=AlertService(telegram=tg))
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


def test_trade_approved_notification(temp_db, mock_telegram_post):
    from app.approval_api import signal_service

    signal = signal_service.persist_detected_signal(
        symbol="ETHUSDT",
        timeframe="5m",
        side="BUY",
        entry=100.0,
        hh50=110.0,
        ll50=95.0,
        created_at=utc_now_iso(),
    )
    mock_telegram_post.post.reset_mock()

    resp = client.post(
        f"/signal/{signal['id']}/approve-trade",
        json={"leverage": 10, "margin_percent": 25},
    )
    assert resp.status_code == 200
    assert mock_telegram_post.post.call_count == 1
    body = mock_telegram_post.post.call_args.kwargs["json"]["text"]
    assert "TRADE APPROVED" in body


def test_tp_hit_notification(temp_db, mock_telegram_post):
    from app.paper_api import paper_service

    open_resp = client.post(
        "/paper/open",
        json={
            "symbol": "ETHUSDT",
            "side": "BUY",
            "entry": 100.0,
            "margin_percent": 25,
            "leverage": 10,
            "stop_loss": 95.0,
            "take_profit": 110.0,
        },
    )
    position_id = open_resp.json()["id"]
    mock_telegram_post.post.reset_mock()

    closed = paper_service.monitor_positions({"ETHUSDT": 120.0})
    assert len(closed) == 1
    assert mock_telegram_post.post.call_count == 1
    text = mock_telegram_post.post.call_args.kwargs["json"]["text"]
    assert "TP HIT" in text


def test_settings_page():
    assert client.get("/settings").status_code == 200
