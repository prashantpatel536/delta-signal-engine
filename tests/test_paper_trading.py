"""Tests for paper trading service and API."""

from fastapi.testclient import TestClient

from app.main import app
from app.paper_api import paper_service

client = TestClient(app)


def _open_eth_trade(margin_percent=25, leverage=10):
    return client.post(
        "/paper/open",
        json={
            "symbol": "ETHUSDT",
            "side": "BUY",
            "entry": 100.0,
            "margin_percent": margin_percent,
            "leverage": leverage,
            "stop_loss": 95.0,
            "take_profit": 110.0,
        },
    )


def test_paper_account_starts_at_1000(temp_db):
    resp = client.get("/paper/account")
    assert resp.status_code == 200
    body = resp.json()
    assert body["balance"] == 1000.0
    assert body["available_margin"] == 1000.0
    assert body["used_margin"] == 0.0


def test_open_paper_trade_margin_allocation(temp_db):
    resp = _open_eth_trade(margin_percent=25, leverage=10)
    assert resp.status_code == 200
    body = resp.json()
    assert body["margin_used"] == 500.0
    assert body["leverage"] == 25
    assert body["position_value"] == 12500.0
    assert body["quantity"] == 125.0

    account = client.get("/paper/account").json()
    assert account["used_margin"] == 500.0
    assert account["available_margin"] == 500.0


def test_preview_margin_allocation(temp_db):
    resp = client.post(
        "/paper/preview",
        json={
            "symbol": "ETHUSDT",
            "side": "BUY",
            "entry": 1750.0,
            "margin_percent": 25,
            "leverage": 50,
            "stop_loss": 1723.0,
            "take_profit": 1808.0,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["margin_used"] == 500.0
    assert body["position_value"] == 12500.0
    assert body["quantity"] == 714.0


def test_insufficient_margin_when_no_available(temp_db):
    _open_eth_trade(margin_percent=50, leverage=25)
    resp = client.post(
        "/paper/open",
        json={
            "symbol": "ETHUSDT",
            "side": "BUY",
            "entry": 100.0,
            "margin_percent": 50,
            "leverage": 25,
            "stop_loss": 95.0,
            "take_profit": 110.0,
        },
    )
    assert resp.status_code == 409
    assert "Open position already exists" in resp.json()["detail"]


def test_monitor_closes_on_tp_with_quantity(temp_db):
    _open_eth_trade(margin_percent=25, leverage=10)
    closed = paper_service.monitor_positions({"ETHUSDT": 120.0})
    assert len(closed) == 1
    assert closed[0]["exit_reason"] == "TP"
    assert closed[0]["pnl"] == 1250.0  # (110-100)*125 ETH contracts qty

    account = client.get("/paper/account").json()
    assert account["balance"] == 2250.0
    assert account["realized_pnl"] == 1250.0


def test_monitor_closes_on_sl(temp_db):
    client.post(
        "/paper/open",
        json={
            "symbol": "BTCUSDT",
            "side": "SELL",
            "entry": 100.0,
            "margin_percent": 10,
            "leverage": 5,
            "stop_loss": 110.0,
            "take_profit": 85.0,
        },
    )
    closed = paper_service.monitor_positions({"BTCUSDT": 120.0})
    assert len(closed) == 1
    assert closed[0]["exit_reason"] == "SL"
    assert closed[0]["pnl"] == -1250.0


def test_manual_close_and_statistics(temp_db, monkeypatch):
    open_resp = _open_eth_trade()
    position_id = open_resp.json()["id"]

    from app.market_data import store

    monkeypatch.setattr(store, "get_latest_prices", lambda: {"ETHUSDT": 105.0})

    close_resp = client.post(f"/position/{position_id}/close")
    assert close_resp.status_code == 200
    assert close_resp.json()["exit_reason"] == "MANUAL"
    assert close_resp.json()["pnl"] == 625.0  # (105-100)*125

    stats = client.get("/paper-statistics")
    assert stats.status_code == 200
    assert stats.json()["total_trades"] == 1
    assert stats.json()["net_pnl"] == 625.0

    perf = client.get("/paper/performance")
    assert perf.status_code == 200
    body = perf.json()
    assert body["total_trades"] == 1
    assert body["winning_trades"] == 1
    assert body["largest_win"] == 625.0
    assert body["starting_balance"] == 1000.0
    assert body["current_balance"] == 1625.0
    assert body["net_pnl"] == 625.0
    assert len(body["daily_equity_curve"]) >= 1


def test_auto_execute_opens_position(temp_db):
    from app.approval_api import signal_service

    signal = signal_service.persist_detected_signal(
        symbol="ETHUSDT",
        timeframe="5m",
        side="BUY",
        entry=100.0,
        hh50=110.0,
        ll50=95.0,
        created_at="2026-06-16T12:00:00+00:00",
    )
    assert signal is not None
    assert signal["status"] == "APPROVED"

    open_resp = client.get("/open-positions")
    assert open_resp.json()["count"] == 1


def test_trades_page():
    assert client.get("/history/trades").status_code == 200


def test_update_stop_loss_recalculates_rr(temp_db):
    open_resp = _open_eth_trade()
    position_id = open_resp.json()["id"]

    resp = client.patch(
        f"/position/{position_id}/levels",
        json={"stop_loss": 98.0},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["stop_loss"] == 98.0
    assert body["original_stop_loss"] == 95.0
    assert body["take_profit"] == 110.0
    assert body["risk_reward"] == 5.0

    events = client.get(f"/position/{position_id}/events")
    assert events.status_code == 200
    assert events.json()["count"] >= 1
    assert events.json()["events"][0]["event_type"] == "SL_MODIFIED"


def test_update_take_profit(temp_db):
    open_resp = _open_eth_trade()
    position_id = open_resp.json()["id"]

    resp = client.patch(
        f"/position/{position_id}/levels",
        json={"take_profit": 115.0},
    )
    assert resp.status_code == 200
    assert resp.json()["take_profit"] == 115.0
    assert resp.json()["original_take_profit"] == 110.0


def test_invalid_sl_rejected_for_long(temp_db):
    open_resp = _open_eth_trade()
    position_id = open_resp.json()["id"]

    resp = client.patch(
        f"/position/{position_id}/levels",
        json={"stop_loss": 105.0},
    )
    assert resp.status_code == 400
    assert "LONG" in resp.json()["detail"]


def test_move_stop_to_breakeven(temp_db):
    open_resp = _open_eth_trade()
    position_id = open_resp.json()["id"]

    resp = client.post(f"/position/{position_id}/breakeven")
    assert resp.status_code == 200
    assert resp.json()["stop_loss"] == 100.0


def test_manual_close_logs_event(temp_db, monkeypatch):
    open_resp = _open_eth_trade()
    position_id = open_resp.json()["id"]

    from app.market_data import store

    monkeypatch.setattr(store, "get_latest_prices", lambda: {"ETHUSDT": 105.0})

    close_resp = client.post(f"/position/{position_id}/close")
    assert close_resp.status_code == 200

    events = client.get(f"/position/{position_id}/events")
    assert events.status_code == 200
    types = {e["event_type"] for e in events.json()["events"]}
    assert "POSITION_CLOSED_MANUALLY" in types


def test_closed_trade_shows_original_and_current_levels(temp_db, monkeypatch):
    open_resp = _open_eth_trade()
    position_id = open_resp.json()["id"]

    client.patch(f"/position/{position_id}/levels", json={"stop_loss": 97.0, "take_profit": 112.0})

    from app.market_data import store

    monkeypatch.setattr(store, "get_latest_prices", lambda: {"ETHUSDT": 105.0})
    client.post(f"/position/{position_id}/close")

    trades = client.get("/trade-history").json()["trades"]
    assert len(trades) == 1
    trade = trades[0]
    assert trade["original_stop_loss"] == 95.0
    assert trade["stop_loss"] == 97.0
    assert trade["original_take_profit"] == 110.0
    assert trade["take_profit"] == 112.0


def test_trade_history_includes_opposite_signal_exit(temp_db, monkeypatch):
    open_resp = _open_eth_trade()
    position_id = open_resp.json()["id"]

    from app.market_data import store

    monkeypatch.setattr(store, "get_latest_prices", lambda: {"ETHUSDT": 102.0})

    closed = paper_service.close_on_opposite_signal(
        symbol="ETHUSDT",
        timeframe="5m",
        new_side="SELL",
        exit_price=102.0,
    )
    assert closed is not None
    assert closed["id"] == position_id
    assert closed["exit_reason"] == "Opposite Signal"

    resp = client.get("/trade-history")
    assert resp.status_code == 200
    trades = resp.json()["trades"]
    assert len(trades) == 1
    assert trades[0]["exit_reason"] == "Opposite Signal"
    assert trades[0]["exit_status"] == "OPPOSITE SIGNAL"
