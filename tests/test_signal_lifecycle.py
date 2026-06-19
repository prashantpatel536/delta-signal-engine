"""Tests for signal lifecycle and chart/store sync."""

from fastapi.testclient import TestClient

from app.approval_api import signal_service
from app.main import app
from app.services.paper_trading_service import PaperTradingService
from tests.conftest import utc_now_iso

client = TestClient(app)


def test_resolve_runtime_signal_creates_pending(temp_db):
    runtime = {
        "symbol": "ETHUSDT",
        "timeframe": "5m",
        "signal": "BUY",
        "price": 1800.0,
        "timestamp": utc_now_iso(),
        "candle_time": 1718534400,
    }
    stored = signal_service.resolve_runtime_signal(runtime, 1850.0, 1750.0)
    assert stored is not None
    assert stored["status"] == "PENDING"
    assert stored["side"] == "BUY"

    again = signal_service.resolve_runtime_signal(runtime, 1850.0, 1750.0)
    assert again["id"] == stored["id"]


def test_tp_hit_updates_signal_status(temp_db):
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
    position_id = resp.json()["position"]["id"]
    position = resp.json()["position"]

    paper = PaperTradingService()
    paper._close_position(position_id, position["take_profit"], "TP")

    record = signal_service.get_signal(created["id"])
    assert record["status"] == "TP_HIT"


def test_sl_hit_updates_signal_status(temp_db):
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
    position_id = resp.json()["position"]["id"]
    position = resp.json()["position"]

    paper = PaperTradingService()
    paper._close_position(position_id, position["stop_loss"], "SL")

    record = signal_service.get_signal(created["id"])
    assert record["status"] == "SL_HIT"


def test_enrich_chart_signals_with_status(temp_db):
    ts = utc_now_iso()
    record = signal_service.persist_detected_signal(
        symbol="ETHUSDT",
        timeframe="5m",
        side="SELL",
        entry=1800.0,
        hh50=1850.0,
        ll50=1750.0,
        created_at=ts,
    )
    chart_signals = [
        {
            "symbol": "ETHUSDT",
            "signal": "SELL",
            "price": 1800.0,
            "timeframe": "5m",
            "timestamp": ts,
            "candle_time": 1718534400,
        }
    ]
    enriched = signal_service.enrich_chart_signals(chart_signals, "ETHUSDT", "5m")
    assert enriched[0]["status"] == "PENDING"
    assert enriched[0]["signal_id"] == record["id"]
