"""Tests for missed opportunity tracking."""

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.approval_api import signal_service
from app.database import get_connection
from app.main import app
from app.paper_trader import excursion_points, reward_points, risk_points
from app.services.missed_opportunity_service import MissedOpportunityService
from tests.conftest import utc_now_iso

client = TestClient(app)


def _create_pending(**kwargs):
    defaults = {
        "symbol": "ETHUSDT",
        "timeframe": "5m",
        "side": "BUY",
        "entry": 100.0,
        "hh50": 110.0,
        "ll50": 95.0,
        "created_at": utc_now_iso(),
    }
    defaults.update(kwargs)
    return signal_service.persist_detected_signal(**defaults)


def test_excursion_points_buy():
    fav, adv = excursion_points("BUY", 100.0, 105.0)
    assert fav == 5.0
    assert adv == 0.0
    fav, adv = excursion_points("BUY", 100.0, 97.0)
    assert fav == 0.0
    assert adv == 3.0


def test_reward_and_risk_points_buy():
    assert reward_points("BUY", 100.0, 110.0) == 10.0
    assert risk_points("BUY", 100.0, 95.0) == 5.0


def test_reject_starts_monitoring(temp_db):
    record = _create_pending()
    signal_service.reject_signal(record["id"])
    updated = signal_service.get_signal(record["id"])
    assert updated["status"] == "REJECTED"
    assert updated["missed_monitoring"] is True
    assert updated["monitoring_started_at"]


def test_missed_winner_on_tp_hit(temp_db):
    record = _create_pending(entry=100.0, hh50=110.0, ll50=95.0)
    signal_service.reject_signal(record["id"])

    service = MissedOpportunityService()
    resolved = service.monitor_signals({"ETHUSDT": 110.0})

    assert len(resolved) == 1
    assert resolved[0]["status"] == "MISSED_WINNER"
    assert resolved[0]["points_captured"] == 10.0
    assert resolved[0]["max_favorable_excursion"] == 10.0


def test_missed_loser_on_sl_hit(temp_db):
    record = _create_pending(entry=100.0, hh50=110.0, ll50=95.0)
    signal_service.reject_signal(record["id"])

    service = MissedOpportunityService()
    resolved = service.monitor_signals({"ETHUSDT": 94.0})

    assert len(resolved) == 1
    assert resolved[0]["status"] == "MISSED_LOSER"
    assert resolved[0]["points_captured"] == -5.0
    assert resolved[0]["max_adverse_excursion"] == 6.0


def test_sell_missed_winner(temp_db):
    record = _create_pending(
        side="SELL",
        entry=200.0,
        hh50=210.0,
        ll50=180.0,
    )
    signal_service.reject_signal(record["id"])

    service = MissedOpportunityService()
    resolved = service.monitor_signals({"ETHUSDT": 180.0})

    assert resolved[0]["status"] == "MISSED_WINNER"
    assert resolved[0]["points_captured"] == 20.0


def test_missed_summary_endpoint(temp_db):
    record = _create_pending()
    signal_service.reject_signal(record["id"])
    MissedOpportunityService().monitor_signals({"ETHUSDT": 110.0})

    resp = client.get("/missed-opportunities/summary")
    assert resp.status_code == 200
    body = resp.json()
    assert body["missed_winners"] == 1
    assert body["potential_missed_profit"] == 10.0


def test_missed_analytics_endpoint(temp_db):
    record = _create_pending()
    signal_service.reject_signal(record["id"])
    MissedOpportunityService().monitor_signals({"ETHUSDT": 110.0})

    resp = client.get("/missed-opportunities/analytics?period=today")
    assert resp.status_code == 200
    body = resp.json()
    assert body["signals_generated"] >= 1
    assert body["missed_winners"] == 1
    assert body["potential_profit_missed"] == 10.0


def test_signal_statistics_includes_missed(temp_db):
    record = _create_pending()
    signal_service.reject_signal(record["id"])
    MissedOpportunityService().monitor_signals({"ETHUSDT": 110.0})

    resp = client.get("/signal-statistics")
    assert resp.status_code == 200
    body = resp.json()
    assert body["missed_winners"] == 1
    assert body["potential_missed_profit"] == 10.0


def test_history_includes_missed_fields(temp_db):
    record = _create_pending()
    signal_service.reject_signal(record["id"])
    MissedOpportunityService().monitor_signals({"ETHUSDT": 110.0})

    resp = client.get("/signal-history?status=MISSED_WINNER")
    assert resp.status_code == 200
    signals = resp.json()["signals"]
    assert len(signals) == 1
    assert signals[0]["points_captured"] == 10.0
    assert signals[0]["max_favorable_excursion"] == 10.0


def test_monitoring_timeout_stops_without_resolution(temp_db):
    record = _create_pending()
    signal_service.reject_signal(record["id"])

    started = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    with get_connection() as conn:
        conn.execute(
            "UPDATE signals SET monitoring_started_at = ? WHERE id = ?",
            (started, record["id"]),
        )
        conn.commit()

    service = MissedOpportunityService()
    resolved = service.monitor_signals({"ETHUSDT": 101.0})
    assert resolved == []
    updated = signal_service.get_signal(record["id"])
    assert updated["status"] == "REJECTED"
    assert updated["missed_monitoring"] is False


def test_backfill_unmonitored_rejected(temp_db):
    record = _create_pending()
    signal_service.reject_signal(record["id"])

    with get_connection() as conn:
        conn.execute(
            "UPDATE signals SET missed_monitoring = 0 WHERE id = ?",
            (record["id"],),
        )
        conn.commit()

    service = MissedOpportunityService()
    queued = service.ensure_monitoring_queue()
    assert queued == 1
    resolved = service.monitor_signals({"ETHUSDT": 110.0})
    assert resolved[0]["status"] == "MISSED_WINNER"
