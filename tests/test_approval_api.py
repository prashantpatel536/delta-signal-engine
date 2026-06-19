"""Tests for approval workflow API endpoints."""

from fastapi.testclient import TestClient

from app.approval_api import signal_service
from app.main import app
from tests.conftest import utc_now_iso

client = TestClient(app)


def test_pending_and_approve_flow(temp_db):
    created = signal_service.persist_detected_signal(
        symbol="ETHUSDT",
        timeframe="5m",
        side="BUY",
        entry=1776.65,
        hh50=1800.0,
        ll50=1767.0,
        created_at=utc_now_iso(),
    )
    assert created is not None

    pending = client.get("/pending-signals")
    assert pending.status_code == 200
    body = pending.json()
    assert body["count"] == 1
    assert body["signals"][0]["side"] == "BUY"

    signal_id = body["signals"][0]["id"]
    detail = client.get(f"/signal/{signal_id}")
    assert detail.status_code == 200
    assert detail.json()["take_profit"] > detail.json()["entry"]

    approved = client.post(f"/signal/{signal_id}/approve")
    assert approved.status_code == 200
    assert approved.json()["status"] == "APPROVED"

    pending_after = client.get("/pending-signals")
    assert pending_after.json()["count"] == 0


def test_reject_signal(temp_db):
    created = signal_service.persist_detected_signal(
        symbol="BTCUSDT",
        timeframe="5m",
        side="SELL",
        entry=65000.0,
        hh50=66000.0,
        ll50=64000.0,
        created_at=utc_now_iso(),
    )
    rejected = client.post(f"/signal/{created['id']}/reject")
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "REJECTED"


def test_signal_history_and_statistics(temp_db):
    signal_service.persist_detected_signal(
        symbol="ETHUSDT",
        timeframe="5m",
        side="BUY",
        entry=1776.65,
        hh50=1800.0,
        ll50=1767.0,
        created_at=utc_now_iso(30),
    )
    record = signal_service.persist_detected_signal(
        symbol="SOLUSDT",
        timeframe="5m",
        side="SELL",
        entry=150.0,
        hh50=155.0,
        ll50=145.0,
        created_at=utc_now_iso(),
    )
    signal_service.approve_signal(record["id"])

    history = client.get("/signal-history")
    assert history.status_code == 200
    assert history.json()["count"] == 2

    filtered = client.get("/signal-history?status=APPROVED")
    assert filtered.json()["count"] == 1

    stats = client.get("/signal-statistics")
    assert stats.status_code == 200
    body = stats.json()
    assert body["total"] == 2
    assert body["pending"] == 1
    assert body["approved"] == 1


def test_latest_signal_endpoint(temp_db):
    empty = client.get("/signals/latest")
    assert empty.status_code == 200
    assert empty.json() is None

    first = signal_service.persist_detected_signal(
        symbol="ETHUSDT",
        timeframe="5m",
        side="BUY",
        entry=100.0,
        hh50=110.0,
        ll50=95.0,
        created_at=utc_now_iso(60),
    )
    second = signal_service.persist_detected_signal(
        symbol="BTCUSDT",
        timeframe="5m",
        side="SELL",
        entry=200.0,
        hh50=210.0,
        ll50=190.0,
        created_at=utc_now_iso(),
    )

    latest = client.get("/signals/latest")
    assert latest.status_code == 200
    body = latest.json()
    assert body["id"] == second["id"]
    assert body["side"] == "SELL"
    assert body["symbol"] == "BTCUSDT"
    assert first["id"] < second["id"]


def test_history_and_stats_pages():
    assert client.get("/history").status_code == 200
    assert client.get("/performance").status_code == 200
    assert client.get("/stats", follow_redirects=False).status_code == 302


def test_latest_pending_signal_endpoint(temp_db):
    empty = client.get("/pending-signals/latest")
    assert empty.status_code == 200
    assert empty.json() is None

    created = signal_service.persist_detected_signal(
        symbol="ETHUSDT",
        timeframe="5m",
        side="BUY",
        entry=1776.65,
        hh50=1800.0,
        ll50=1767.0,
        created_at=utc_now_iso(),
    )
    latest = client.get("/pending-signals/latest?symbol=ETH&timeframe=5m")
    assert latest.status_code == 200
    body = latest.json()
    assert body["id"] == created["id"]
    assert body["status"] == "PENDING"


def test_approve_trade_opens_position(temp_db):
    created = signal_service.persist_detected_signal(
        symbol="ETHUSDT",
        timeframe="5m",
        side="BUY",
        entry=100.0,
        hh50=110.0,
        ll50=95.0,
        created_at=utc_now_iso(),
    )
    resp = client.post(
        f"/signal/{created['id']}/approve-trade",
        json={"leverage": 10, "margin_percent": 25},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["signal"]["status"] == "APPROVED"
    assert body["position"]["signal_id"] == created["id"]
    assert body["position"]["status"] == "OPEN"

    opens = client.get("/open-positions").json()
    assert opens["count"] == 1

    pending = client.get("/pending-signals")
    assert pending.json()["count"] == 0


def test_expired_signal_cannot_be_approved(temp_db):
    created = signal_service.persist_detected_signal(
        symbol="BTCUSDT",
        timeframe="5m",
        side="SELL",
        entry=65000.0,
        hh50=66000.0,
        ll50=64000.0,
        created_at="2020-01-01T00:00:00+00:00",
    )
    expired = signal_service.expire_stale_pending()
    assert any(r["id"] == created["id"] for r in expired)

    record = signal_service.get_signal(created["id"])
    assert record["status"] == "EXPIRED"

    resp = client.post(
        f"/signal/{created['id']}/approve-trade",
        json={"leverage": 10, "margin_percent": 25},
    )
    assert resp.status_code == 409
    assert "expired" in resp.json()["detail"].lower()

    stats = client.get("/signal-statistics").json()
    assert stats["expired"] >= 1
