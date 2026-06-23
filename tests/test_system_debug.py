"""Tests for system debug diagnostics API."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_system_debug_endpoint(temp_db):
    resp = client.get("/api/debug/system")
    assert resp.status_code == 200
    body = resp.json()
    assert "git_commit" in body
    assert "database_path" in body
    assert "database_size" in body
    assert "signal_count" in body
    assert "trade_count" in body
    assert "approved_count" in body
    assert "latest_signal_time" in body
    assert "latest_trade_time" in body


def test_system_debug_full_endpoint(temp_db):
    resp = client.get("/api/debug/system/full")
    assert resp.status_code == 200
    body = resp.json()
    assert body["signal_engine_version"]
    assert "table_row_counts" in body
    assert "latest_signals" in body
    assert "latest_trades" in body
    assert "database_info" in body


def test_system_compare_identical(temp_db):
    full = client.get("/api/debug/system/full").json()
    resp = client.post("/api/debug/system/compare", json=full)
    assert resp.status_code == 200
    body = resp.json()
    assert body["identical"] is True
    assert body["table_differences"] == []


def test_system_compare_detects_diff(temp_db):
    local = client.get("/api/debug/system/full").json()
    remote = {**local, "signal_count": local["signal_count"] + 5}
    remote["table_row_counts"] = {
        **local["table_row_counts"],
        "signals": local["table_row_counts"]["signals"] + 5,
    }
    resp = client.post("/api/debug/system/compare", json=remote)
    body = resp.json()
    assert body["identical"] is False
    assert any(d["table"] == "signals" for d in body["table_differences"])


def test_debug_system_page():
    resp = client.get("/debug/system")
    assert resp.status_code == 200
    assert "System Diagnostics" in resp.text
