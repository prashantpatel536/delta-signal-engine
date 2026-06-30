"""Default strategy settings for SOL Reversal Engine."""

from __future__ import annotations

import json
from typing import Any

DEFAULT_SETTINGS: dict[str, Any] = {
    "symbol": "SOLUSDT",
    "timeframe": "5m",
    "min_red_candles": 4,
    "max_green_candles": 2,
    "strong_candle_enabled": True,
    "strong_candle_body_pct": 0.15,
    "atr_filter_enabled": True,
    "atr_multiplier": 0.2,
    "atr_minimum": 0.1,
    "atr_period": 14,
    "take_profit_pct": 7.0,
    "stop_loss_pct": 1.0,
    "lock_profit_enabled": True,
    "lock_trigger_pct": 3.0,
    "lock_distance_pct": 3.0,
    "initial_capital": 1000.0,
    "leverage": 25.0,
    "position_size_pct": 50.0,
    "ambiguous_bar_rule": "STOP_FIRST",
}


def settings_json(settings: dict[str, Any] | None = None) -> str:
    return json.dumps(settings or DEFAULT_SETTINGS)
