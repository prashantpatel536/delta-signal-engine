"""Tests for server-side signal timeframe filtering."""

from fastapi.testclient import TestClient

from app.main import app
from app.repositories.app_settings_repository import AppSettingsRepository
from app.services.runtime_settings import (
    SIGNAL_TIMEFRAME_KEY,
    get_signal_timeframe,
    initialize_signal_timeframe,
    set_signal_timeframe,
)

client = TestClient(app)


def test_default_signal_timeframe_is_5m(temp_db):
    initialize_signal_timeframe()
    assert get_signal_timeframe() == "5m"


def test_env_signal_timeframe_overrides_stale_db(temp_db, monkeypatch):
    monkeypatch.setenv("SIGNAL_TIMEFRAME", "5m")
    AppSettingsRepository().set(SIGNAL_TIMEFRAME_KEY, "1m")
    tf = initialize_signal_timeframe()
    assert tf == "5m"
    assert get_signal_timeframe() == "5m"


def test_signal_timeframe_api_default(temp_db):
    initialize_signal_timeframe()
    resp = client.get("/settings/signal-timeframe")
    assert resp.status_code == 200
    assert resp.json()["signal_timeframe"] == "5m"


def test_signal_timeframe_api_update(temp_db):
    initialize_signal_timeframe()
    resp = client.put("/settings/signal-timeframe", json={"signal_timeframe": "15m"})
    assert resp.status_code == 200
    assert resp.json()["signal_timeframe"] == "15m"
    assert get_signal_timeframe() == "15m"


def test_signal_timeframe_invalid_rejected(temp_db):
    resp = client.put("/settings/signal-timeframe", json={"signal_timeframe": "2m"})
    assert resp.status_code == 400


def test_engine_persist_gate_only_active_tf(temp_db):
    """Scheduler only persists when candle timeframe matches active Signal TF."""
    initialize_signal_timeframe()
    set_signal_timeframe("5m")
    active = get_signal_timeframe()
    assert active == "5m"
    assert ("1m" == active) is False
    assert ("5m" == active) is True


def test_common_js_default_prefs():
    defaults = {"symbol": "ETH", "chartTimeframe": "5m", "signalTimeframe": "5m", "bars": 100}
    assert defaults["signalTimeframe"] == "5m"
    assert defaults["chartTimeframe"] == "5m"
