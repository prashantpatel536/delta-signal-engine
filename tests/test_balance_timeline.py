"""Tests for balance timeline reconstruction."""

from app.balance_timeline import BalanceTimeline


def test_balance_before_first_trade():
    timeline = BalanceTimeline(
        [
            {"id": 1, "closed_at": "2026-01-02T00:00:00+00:00", "pnl": 100.0},
        ]
    )
    assert timeline.balance_before("2026-01-01T00:00:00+00:00") == 1000.0
    assert timeline.balance_before("2026-01-02T00:00:00+00:00") == 1000.0
    assert timeline.balance_before("2026-01-03T00:00:00+00:00") == 1100.0


def test_balance_compounds_multiple_trades():
    timeline = BalanceTimeline(
        [
            {"id": 1, "closed_at": "2026-01-02T00:00:00+00:00", "pnl": 100.0},
            {"id": 2, "closed_at": "2026-01-03T00:00:00+00:00", "pnl": -50.0},
        ]
    )
    assert timeline.balance_before("2026-01-03T00:00:00+00:00") == 1100.0
    assert timeline.balance_before("2026-01-04T00:00:00+00:00") == 1050.0
