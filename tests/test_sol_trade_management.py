"""Pine Script trade management parity — TP/SL toggles, fill timing, lock profit."""

import pandas as pd

from app.strategies.sol_reversal.settings_defaults import DEFAULT_SETTINGS
from app.strategies.sol_reversal.simulation import (
    compute_lock_state,
    open_position,
    process_bar,
    replay_strategy,
)
from app.strategies.sol_reversal.strategy import levels_for_side


def _bars(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def test_lock_stop_ratchet_matches_user_example():
    """Lock stop trails peak upward only; never decreases on pullback."""
    entry = 72.28
    settings = {
        **DEFAULT_SETTINGS,
        "enable_stop_loss": True,
        "stop_loss_pct": 25.0,
        "lock_profit_enabled": True,
        "lock_trigger_pct": 3.0,
        "lock_distance_pct": 3.0,
    }
    pos = {
        "entry": entry,
        "quantity": 1.0,
        "lock_active": True,
        "lock_high": 74.50,
        "lock_stop": round(74.50 * 0.97, 4),
    }
    state = compute_lock_state(pos, high=75.20, close=75.00, settings=settings)
    assert state["lock_active"] is True
    assert state["highest_price_since_lock"] == 75.20
    assert state["lock_stop"] == round(75.20 * 0.97, 4)

    pullback = compute_lock_state(
        {**pos, "lock_high": 75.80, "lock_stop": round(75.80 * 0.97, 4)},
        high=75.00,
        close=75.00,
        settings=settings,
    )
    assert pullback["highest_price_since_lock"] == 75.80
    assert pullback["lock_stop"] == round(75.80 * 0.97, 4)


def test_lock_stays_active_after_pullback_below_trigger():
    entry = 100.0
    settings = {
        **DEFAULT_SETTINGS,
        "lock_profit_enabled": True,
        "lock_trigger_pct": 3.0,
        "lock_distance_pct": 3.0,
        "stop_loss_pct": 25.0,
    }
    pos = open_position("BUY", entry, 1, settings, 10_000.0)
    assert pos is not None
    pos, _ = process_bar(pos, bar_time=2, high=104.0, low=103.0, close=103.5, settings=settings)
    assert pos["lock_active"] is True
    pos, closed = process_bar(pos, bar_time=3, high=103.0, low=102.5, close=102.8, settings=settings)
    assert closed is None
    assert pos["lock_active"] is True
    assert pos["lock_stop"] == round(104.0 * 0.97, 4)


def test_levels_respect_enable_toggles():
    settings = {
        **DEFAULT_SETTINGS,
        "enable_take_profit": False,
        "enable_stop_loss": False,
    }
    tp, sl = levels_for_side("BUY", 100.0, settings)
    assert tp is None
    assert sl is None


def test_stop_loss_disabled_lock_can_still_exit():
    settings = {
        **DEFAULT_SETTINGS,
        "enable_take_profit": False,
        "enable_stop_loss": False,
        "lock_profit_enabled": True,
        "lock_trigger_pct": 1.0,
        "lock_distance_pct": 1.0,
    }
    pos = open_position("BUY", 100.0, 1, settings, 10_000.0)
    assert pos is not None
    pos, closed = process_bar(
        pos,
        bar_time=2,
        high=102.0,
        low=101.5,
        close=101.5,
        settings=settings,
    )
    assert closed is None
    assert pos["lock_active"] is True
    pos, closed = process_bar(
        pos,
        bar_time=3,
        high=101.2,
        low=100.5,
        close=101.0,
        settings=settings,
    )
    assert closed is not None
    assert closed["exit_reason"] == "LOCK"


def test_next_bar_open_fill_matches_pine_default():
    settings = {
        **DEFAULT_SETTINGS,
        "process_orders_on_close": False,
        "min_red_candles": 1,
        "max_green_candles": 5,
        "atr_filter_enabled": False,
        "strong_candle_enabled": False,
        "lock_profit_enabled": False,
        "take_profit_pct": 99.0,
        "stop_loss_pct": 99.0,
    }
    ha = _bars([
        {"time": 100, "open": 100.0, "high": 100.5, "low": 99.5, "close": 99.0, "volume": 1, "color": "red"},
        {"time": 200, "open": 99.0, "high": 101.0, "low": 98.5, "close": 100.5, "volume": 1, "color": "green"},
        {"time": 300, "open": 100.5, "high": 101.5, "low": 100.0, "close": 101.0, "volume": 1, "color": "green"},
    ])
    result = replay_strategy(ha, settings)
    assert len(result["entries"]) == 1
    assert result["entries"][0]["candle_time"] == 300
    assert result["entries"][0]["entry_price"] == 100.5
    assert result["entries"][0]["signal_bar_index"] == 1


def test_bar_close_fill_when_process_orders_on_close():
    settings = {
        **DEFAULT_SETTINGS,
        "process_orders_on_close": True,
        "min_red_candles": 1,
        "max_green_candles": 5,
        "atr_filter_enabled": False,
        "strong_candle_enabled": False,
        "lock_profit_enabled": False,
        "take_profit_pct": 99.0,
        "stop_loss_pct": 99.0,
    }
    ha = _bars([
        {"time": 100, "open": 100.0, "high": 100.5, "low": 99.5, "close": 99.0, "volume": 1, "color": "red"},
        {"time": 200, "open": 99.0, "high": 101.0, "low": 98.5, "close": 100.5, "volume": 1, "color": "green"},
        {"time": 300, "open": 100.5, "high": 101.5, "low": 100.0, "close": 101.0, "volume": 1, "color": "green"},
    ])
    result = replay_strategy(ha, settings)
    assert len(result["entries"]) == 1
    assert result["entries"][0]["candle_time"] == 200
    assert result["entries"][0]["entry_price"] == 100.5
