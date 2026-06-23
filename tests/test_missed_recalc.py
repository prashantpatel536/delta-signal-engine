"""Tests for historical missed-opportunity recalculation."""

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.approval_api import signal_service
from app.main import app
from app.missed_recalc import RecalcOutcome, evaluate_missed_record
from app.services.missed_opportunity_recalc_service import MissedOpportunityRecalcService
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


def _bar(time_unix: int, high: float, low: float) -> dict:
    return {"time": time_unix, "open": low, "high": high, "low": low, "close": high}


def test_evaluate_recalc_tp_from_candles():
    start = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    record = {
        "id": 1,
        "symbol": "ETHUSDT",
        "timeframe": "5m",
        "side": "BUY",
        "entry": 100.0,
        "stop_loss": 95.0,
        "take_profit": 110.0,
        "monitoring_started_at": start.isoformat(),
        "created_at": start.isoformat(),
    }
    candles = [_bar(int(start.timestamp()) + 300, high=111.0, low=99.0)]
    outcome = evaluate_missed_record(record, all_signals=[], candles=candles, monitor_hours=24)
    assert outcome.status == "MISSED_WINNER"
    assert outcome.exit_reason == "TP"
    assert outcome.points_captured == 10.0


def test_evaluate_recalc_opposite_before_tp():
    start = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    record = {
        "id": 1,
        "symbol": "ETHUSDT",
        "timeframe": "5m",
        "side": "BUY",
        "entry": 100.0,
        "stop_loss": 95.0,
        "take_profit": 110.0,
        "monitoring_started_at": start.isoformat(),
        "created_at": start.isoformat(),
    }
    opposite = {
        "id": 2,
        "symbol": "ETHUSDT",
        "timeframe": "5m",
        "side": "SELL",
        "entry": 103.0,
        "created_at": start.replace(minute=5).isoformat(),
    }
    candles = [_bar(int(start.timestamp()) + 300, high=111.0, low=99.0)]
    outcome = evaluate_missed_record(
        record,
        all_signals=[opposite],
        candles=candles,
        monitor_hours=24,
    )
    assert outcome.status == "MISSED_WINNER"
    assert outcome.exit_reason == "Opposite Signal"
    assert outcome.points_captured == 3.0
    assert outcome.exit_price == 103.0


def test_recalculate_all_updates_old_tp_only_records(temp_db):
    buy = _create_pending(entry=100.0, hh50=110.0, ll50=95.0)
    signal_service.reject_signal(buy["id"])
    _create_pending(side="SELL", entry=103.0, hh50=110.0, ll50=90.0)

    from app.repositories.signal_repository import SignalRepository

    repo = SignalRepository()
    repo.apply_recalculated_missed(
        buy["id"],
        RecalcOutcome(
            resolved=True,
            status="MISSED_WINNER",
            points_captured=10.0,
            exit_reason="TP",
            exit_price=110.0,
            max_favorable_excursion=10.0,
            max_adverse_excursion=0.0,
            missed_resolved_at=utc_now_iso(),
        ),
    )

    start_ts = int(datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc).timestamp())
    fake_candles = [
        _bar(start_ts + 300, high=104.0, low=99.0),
    ]

    def fake_fetch(symbol, timeframe, limit=None):
        import pandas as pd

        return pd.DataFrame(fake_candles)

    service = MissedOpportunityRecalcService(candle_fetcher=fake_fetch)
    result = service.recalculate_all()

    assert result["recalculated"] >= 1
    updated = signal_service.get_signal(buy["id"])
    assert updated["missed_exit_reason"] == "Opposite Signal"
    assert updated["points_captured"] == 3.0


def test_recalculate_endpoint_streams_progress(temp_db):
    buy = _create_pending()
    signal_service.reject_signal(buy["id"])
    _create_pending(side="SELL", entry=103.0, hh50=110.0, ll50=90.0)

    with client.stream("POST", "/admin/recalculate-missed-opportunities") as response:
        assert response.status_code == 200
        body = "".join(response.iter_text())
    assert "complete" in body
    assert "recalculated" in body
