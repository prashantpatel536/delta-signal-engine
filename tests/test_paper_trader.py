"""Tests for paper trading PnL and exit logic."""

from app.paper_trader import (
    build_closed_trade_payload,
    calculate_pnl,
    check_exit_reason,
    safe_duration_seconds,
    trade_result,
)


def test_buy_pnl():
    assert calculate_pnl("BUY", 100.0, 110.0) == 10.0
    assert calculate_pnl("BUY", 100.0, 90.0) == -10.0
    assert calculate_pnl("BUY", 100.0, 110.0, 0.5) == 5.0


def test_sell_pnl():
    assert calculate_pnl("SELL", 100.0, 90.0) == 10.0
    assert calculate_pnl("SELL", 100.0, 110.0) == -10.0


def test_margin_calculations():
    from app.paper_trader import (
        calculate_from_margin_allocation,
        calculate_roe,
        position_value,
        required_margin,
    )

    margin, pos_val, qty, contracts = calculate_from_margin_allocation(1000, 50, 25, 100_000, "BTCUSDT")
    assert margin == 500.0
    assert contracts == 125
    assert qty == 0.125
    assert pos_val == 12500.0

    pv = position_value(1751.45, 0.5)
    assert pv == 875.73
    margin = required_margin(pv, 10)
    assert margin == 87.57
    assert calculate_roe(-4.37, 87.57) == -4.99


def test_buy_tp_sl_checks():
    assert check_exit_reason("BUY", 120.0, 95.0, 115.0) == "TP"
    assert check_exit_reason("BUY", 90.0, 95.0, 115.0) == "SL"
    assert check_exit_reason("BUY", 100.0, 95.0, 115.0) is None


def test_sell_tp_sl_checks():
    assert check_exit_reason("SELL", 80.0, 110.0, 85.0) == "TP"
    assert check_exit_reason("SELL", 120.0, 110.0, 85.0) == "SL"
    assert check_exit_reason("SELL", 100.0, 110.0, 85.0) is None


def test_trade_result():
    assert trade_result(5.0) == "WIN"
    assert trade_result(-1.0) == "LOSS"


def test_safe_duration_seconds_invalid_dates():
    assert safe_duration_seconds("bad", "2026-01-01T00:00:00+00:00") == 0.0
    assert safe_duration_seconds(None, None) == 0.0


def test_build_closed_trade_payload_normalizes_reason_and_duration():
    payload = build_closed_trade_payload(
        {
            "id": 1,
            "signal_id": 2,
            "symbol": "SOLUSDT",
            "side": "sell",
            "entry": 70.0,
            "stop_loss": 72.0,
            "take_profit": 68.0,
            "original_stop_loss": 72.0,
            "original_take_profit": 68.0,
            "risk_reward": 1.5,
            "quantity": 10.0,
            "leverage": 25.0,
            "margin_used": 28.0,
            "position_value": 700.0,
            "status": "CLOSED",
            "opened_at": "2026-06-01T10:00:00+00:00",
            "closed_at": "2026-06-01T11:00:00+00:00",
            "exit_price": 69.0,
            "exit_reason": "Opposite Signal",
            "pnl": 10.0,
            "price_points": 1.0,
            "account_impact_pct": 1.2,
        }
    )
    assert payload["side"] == "SELL"
    assert payload["exit_reason"] == "Opposite Signal"
    assert payload["duration_seconds"] == 3600.0
