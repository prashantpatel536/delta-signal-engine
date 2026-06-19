"""Tests for signal persistence and approval workflow."""

from app.repositories.signal_repository import SignalRepository
from app.services.signal_service import SignalService
from tests.conftest import utc_now_iso


def test_persist_skips_duplicate_pending(temp_db):
    service = SignalService()
    first = service.persist_detected_signal(
        symbol="ETHUSDT",
        timeframe="5m",
        side="BUY",
        entry=1776.65,
        hh50=1800.0,
        ll50=1767.0,
        created_at=utc_now_iso(),
    )
    second = service.persist_detected_signal(
        symbol="ETHUSDT",
        timeframe="5m",
        side="BUY",
        entry=1777.0,
        hh50=1800.0,
        ll50=1767.0,
        created_at=utc_now_iso(30),
    )

    assert first is not None
    assert second is None
    assert len(service.get_pending_signals()) == 1


def test_persist_skips_same_timestamp(temp_db):
    service = SignalService()
    ts = utc_now_iso()
    first = service.persist_detected_signal(
        symbol="ETHUSDT",
        timeframe="5m",
        side="BUY",
        entry=1776.65,
        hh50=1800.0,
        ll50=1767.0,
        created_at=ts,
    )
    second = service.persist_detected_signal(
        symbol="ETHUSDT",
        timeframe="5m",
        side="BUY",
        entry=1776.65,
        hh50=1800.0,
        ll50=1767.0,
        created_at=ts,
    )

    assert first is not None
    assert second is None


def test_approve_and_reject(temp_db):
    repo = SignalRepository()
    record = repo.create(
        symbol="BTCUSDT",
        timeframe="5m",
        side="SELL",
        entry=65000.0,
        stop_loss=66000.0,
        take_profit=63000.0,
        risk_reward=2.0,
    )
    service = SignalService(repo)

    approved = service.approve_signal(record["id"])
    assert approved["status"] == "APPROVED"

    rejected_record = repo.create(
        symbol="SOLUSDT",
        timeframe="15m",
        side="BUY",
        entry=150.0,
        stop_loss=145.0,
        take_profit=160.0,
        risk_reward=2.0,
    )
    rejected = service.reject_signal(rejected_record["id"])
    assert rejected["status"] == "REJECTED"

    stats = service.get_statistics()
    assert stats["APPROVED"] == 1
    assert stats["REJECTED"] == 1
