"""Tests for timeframe consistency and signal review workflow."""

from fastapi.testclient import TestClient

from app.approval_api import signal_service
from app.main import app
from tests.conftest import utc_now_iso

client = TestClient(app)


def test_pending_latest_strict_timeframe(temp_db):
    signal_service.persist_detected_signal(
        symbol="ETHUSDT",
        timeframe="1m",
        side="BUY",
        entry=100.0,
        hh50=110.0,
        ll50=95.0,
        created_at=utc_now_iso(),
    )
    on_5m = client.get("/pending-signals/latest?symbol=ETH&timeframe=5m")
    assert on_5m.status_code == 200
    assert on_5m.json() is None

    created_5m = signal_service.persist_detected_signal(
        symbol="ETHUSDT",
        timeframe="5m",
        side="BUY",
        entry=101.0,
        hh50=110.0,
        ll50=95.0,
        created_at=utc_now_iso(5),
    )
    match = client.get("/pending-signals/latest?symbol=ETH&signal_timeframe=5m")
    assert match.json()["id"] == created_5m["id"]
    assert match.json()["timeframe"] == "5m"
    assert match.json()["signal_timeframe"] == "5m"


def test_stored_signal_includes_signal_timeframe(temp_db):
    created = signal_service.persist_detected_signal(
        symbol="ETHUSDT",
        timeframe="15m",
        side="SELL",
        entry=1800.0,
        hh50=1850.0,
        ll50=1750.0,
        created_at=utc_now_iso(),
    )
    detail = client.get(f"/signal/{created['id']}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["signal_timeframe"] == "15m"
    assert body["timeframe"] == "15m"


def test_approve_reject_5m_workflow(temp_db):
    created = signal_service.persist_detected_signal(
        symbol="ETHUSDT",
        timeframe="5m",
        side="BUY",
        entry=100.0,
        hh50=110.0,
        ll50=95.0,
        created_at=utc_now_iso(),
    )
    assert created["side"] == "BUY"

    approved = client.post(
        f"/signal/{created['id']}/approve-trade",
        json={"leverage": 10, "margin_percent": 25},
    )
    assert approved.status_code == 200
    assert approved.json()["signal"]["status"] == "APPROVED"
    assert approved.json()["position"]["leverage"] == 10
    assert approved.json()["position"]["margin_used"] > 0

    created2 = signal_service.persist_detected_signal(
        symbol="BTCUSDT",
        timeframe="5m",
        side="SELL",
        entry=65000.0,
        hh50=66000.0,
        ll50=64000.0,
        created_at=utc_now_iso(),
    )
    rejected = client.post(f"/signal/{created2['id']}/reject")
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "REJECTED"
    assert client.get("/open-positions").json()["count"] == 1
