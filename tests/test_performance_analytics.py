"""Tests for performance analytics calculations."""

from app.performance_analytics import (
    build_daily_equity_curve,
    build_performance_payload,
    compute_max_drawdown,
    equity_series_from_trades,
)


def test_equity_series_and_drawdown():
    trades = [
        {"id": 1, "pnl": 100.0, "closed_at": "2026-06-01T12:00:00+00:00", "opened_at": "2026-06-01T11:00:00+00:00"},
        {"id": 2, "pnl": -50.0, "closed_at": "2026-06-02T12:00:00+00:00", "opened_at": "2026-06-02T11:00:00+00:00"},
        {"id": 3, "pnl": 25.0, "closed_at": "2026-06-03T12:00:00+00:00", "opened_at": "2026-06-03T11:00:00+00:00"},
    ]
    series = equity_series_from_trades(trades, 1000.0)
    assert series == [1000.0, 1100.0, 1050.0, 1075.0]

    dd_usd, dd_pct = compute_max_drawdown(series)
    assert dd_usd == 50.0
    assert dd_pct == round(50 / 1100 * 100, 2)


def test_daily_equity_curve_groups_by_day():
    trades = [
        {"id": 1, "pnl": 10.0, "closed_at": "2026-06-01T10:00:00+00:00"},
        {"id": 2, "pnl": 5.0, "closed_at": "2026-06-01T18:00:00+00:00"},
        {"id": 3, "pnl": -3.0, "closed_at": "2026-06-02T09:00:00+00:00"},
    ]
    curve = build_daily_equity_curve(trades, 1000.0, fallback_date="2026-06-01")
    assert len(curve) == 2
    assert curve[0] == {"date": "2026-06-01", "equity": 1015.0, "daily_pnl": 15.0}
    assert curve[1] == {"date": "2026-06-02", "equity": 1012.0, "daily_pnl": -3.0}


def test_build_performance_payload():
    trades = [
        {
            "id": 1,
            "pnl": 125.0,
            "closed_at": "2026-06-01T12:00:00+00:00",
            "opened_at": "2026-06-01T11:00:00+00:00",
        },
        {
            "id": 2,
            "pnl": -25.0,
            "closed_at": "2026-06-02T12:00:00+00:00",
            "opened_at": "2026-06-02T10:00:00+00:00",
        },
    ]
    payload = build_performance_payload(
        starting_balance=1000.0,
        current_balance=1100.0,
        closed_trades=trades,
        open_positions=0,
        fallback_date="2026-06-01",
    )
    assert payload["starting_balance"] == 1000.0
    assert payload["current_balance"] == 1100.0
    assert payload["net_pnl"] == 100.0
    assert payload["total_trades"] == 2
    assert payload["winning_trades"] == 1
    assert payload["losing_trades"] == 1
    assert payload["largest_win"] == 125.0
    assert payload["largest_loss"] == -25.0
    assert payload["profit_factor"] == 5.0
    assert payload["edge_status"] == "insufficient_data"
    assert len(payload["daily_equity_curve"]) == 2
