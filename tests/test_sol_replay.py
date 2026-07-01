"""Tests for TV-style strategy replay markers."""

import pandas as pd

from app.strategies.sol_reversal.ha import to_heikin_ashi
from app.strategies.sol_reversal.replay import markers_for_chart, replay_markers
from app.strategies.sol_reversal.settings_defaults import DEFAULT_SETTINGS
from app.strategies.sol_reversal.simulation import replay_strategy


def _make_ha_bars():
    rows = []
    price = 100.0
    for i in range(30):
        if i < 8:
            o, c = price, price - 0.5
            price = c
        elif i == 8:
            o, c = price, price + 1.0
            price = c
        else:
            o, c = price, price + 0.1
            price = c
        rows.append({
            "time": 1_700_000_000 + i * 300,
            "open": o,
            "high": max(o, c) + 0.2,
            "low": min(o, c) - 0.2,
            "close": c,
            "volume": 1000,
        })
    return to_heikin_ashi(pd.DataFrame(rows))


def test_replay_skips_signals_while_in_position():
    settings = {
        **DEFAULT_SETTINGS,
        "min_red_candles": 7,
        "atr_filter_enabled": False,
        "strong_candle_enabled": False,
        "take_profit_pct": 50.0,
        "stop_loss_pct": 50.0,
        "lock_profit_enabled": False,
    }
    ha = _make_ha_bars()
    result = replay_markers(ha, settings)
    assert len(result["raw_conditions"]) >= 1
    assert len(result["entries"]) <= len(result["raw_conditions"])


def test_markers_include_entry_status():
    settings = {
        **DEFAULT_SETTINGS,
        "min_red_candles": 3,
        "atr_filter_enabled": False,
        "strong_candle_enabled": False,
        "lock_profit_enabled": False,
    }
    ha = _make_ha_bars()
    replay = replay_markers(ha, settings)
    markers = markers_for_chart(replay)
    if replay["entries"]:
        assert any(m["status"] == "ENTRY" for m in markers)
    buy_markers = [m for m in markers if m["signal"] == "BUY" and m["status"] == "ENTRY"]
    assert len(buy_markers) == len(replay["entries"])


def test_one_entry_per_trade_despite_repeated_conditions(monkeypatch):
    """Repeated BUY conditions on consecutive bars only produce one entry until flat again."""
    import pandas as pd

    from app.strategies.sol_reversal import simulation

    times = [1_700_000_000 + i * 300 for i in range(8)]
    ha = pd.DataFrame({
        "time": times,
        "open": [100.0] * 8,
        "high": [101.0] * 8,
        "low": [99.0] * 8,
        "close": [100.5] * 8,
        "volume": [1000] * 8,
        "color": ["red"] * 8,
    })

    condition_bars = {3, 4, 5, 6}

    def fake_condition(_candles, _settings, idx, *, atr=None):
        return "BUY" if idx in condition_bars else None

    monkeypatch.setattr(simulation, "detect_buy_condition_at_index", fake_condition)
    settings = {
        **DEFAULT_SETTINGS,
        "take_profit_pct": 99.0,
        "stop_loss_pct": 99.0,
        "lock_profit_enabled": False,
    }
    result = simulation.replay_strategy(ha, settings)
    assert len(result["entries"]) == 1
    assert len(result["raw_conditions"]) == 0
    markers = markers_for_chart(result)
    assert len([m for m in markers if m["status"] == "ENTRY"]) == 1
