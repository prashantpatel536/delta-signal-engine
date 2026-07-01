"""Tests for unified position peak / lock metrics."""

from app.strategies.sol_reversal.position_metrics import (
    compute_position_metrics,
    lock_stop_price,
    peak_move_pct,
)
from app.strategies.sol_reversal.settings_defaults import DEFAULT_SETTINGS


def test_peak_from_highest_since_entry_only():
    entry = 72.2836223725
    highest_entry = entry * 1.049012
    assert abs(peak_move_pct(entry, highest_entry) - 4.9012) < 0.01


def test_user_reported_numbers_are_consistent_when_split():
    """Peak uses highestSinceEntry; lock stop uses highestSinceLock."""
    entry = 72.2836223725
    highest_since_entry = entry * 1.049012
    highest_since_lock = 75.03902126
    lock_distance = 3.0

    peak = peak_move_pct(entry, highest_since_entry)
    lock_stop = lock_stop_price(highest_since_lock, lock_distance)

    assert abs(peak - 4.9012) < 0.01
    assert abs(lock_stop - 72.7879) < 0.01
    assert highest_since_entry > highest_since_lock


def test_lock_stop_formula_always():
    settings = {
        **DEFAULT_SETTINGS,
        "lock_profit_enabled": True,
        "lock_trigger_pct": 3.0,
        "lock_distance_pct": 3.0,
        "stop_loss_pct": 1.0,
    }
    entry = 72.28
    pos = {
        "entry": entry,
        "lock_active": True,
        "highest_since_entry": 75.8278,
        "highest_since_lock": 75.80,
        "initial_stop_loss": round(entry * 0.99, 4),
    }
    metrics = compute_position_metrics(
        pos,
        bar_high=75.0,
        bar_low=74.5,
        bar_close=75.0,
        settings=settings,
        update_peaks=True,
    )
    assert metrics["validation"]["ok"] is True
    assert metrics["peak_price_move_pct"] == metrics["validation"]["expected_peak_pct"]
    assert metrics["lock_stop"] == metrics["validation"]["expected_lock_stop"]


def test_highest_since_entry_updates_each_bar():
    settings = {**DEFAULT_SETTINGS, "lock_profit_enabled": False}
    entry = 100.0
    pos = {"entry": entry, "highest_since_entry": entry, "lock_active": False}
    m1 = compute_position_metrics(pos, bar_high=101.0, bar_low=99.0, bar_close=100.5, settings=settings)
    assert m1["highest_since_entry"] == 101.0
    pos2 = {**pos, "highest_since_entry": m1["highest_since_entry"]}
    m2 = compute_position_metrics(pos2, bar_high=100.5, bar_low=99.5, bar_close=100.0, settings=settings)
    assert m2["highest_since_entry"] == 101.0


def test_lock_stop_never_decreases_on_pullback():
    settings = {
        **DEFAULT_SETTINGS,
        "lock_profit_enabled": True,
        "lock_trigger_pct": 3.0,
        "lock_distance_pct": 3.0,
    }
    entry = 72.28
    pos = {
        "entry": entry,
        "lock_active": True,
        "highest_since_entry": 75.8278,
        "highest_since_lock": 75.80,
        "initial_stop_loss": round(entry * 0.99, 4),
    }
    metrics = compute_position_metrics(
        pos,
        bar_high=75.0,
        bar_low=74.8,
        bar_close=75.0,
        settings=settings,
    )
    assert metrics["highest_since_lock"] == 75.80
    assert metrics["lock_stop"] == lock_stop_price(75.80, 3.0)
