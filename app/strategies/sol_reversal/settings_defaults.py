"""Default strategy settings — aligned to CE jumbo Pine Script inputs."""

from __future__ import annotations

import json
from typing import Any

DEFAULT_SETTINGS: dict[str, Any] = {
    "symbol": "SOLUSDT",
    "timeframe": "5m",
    "min_red_candles": 7,
    "max_green_candles": 3,
    "strong_candle_enabled": True,
    "strong_candle_atr_mult": 0.5,
    "atr_filter_enabled": True,
    "atr_minimum": 1.0,
    "atr_period": 14,
    "take_profit_pct": 40.0,
    "stop_loss_pct": 25.0,
    "enable_take_profit": True,
    "enable_stop_loss": True,
    "process_orders_on_close": False,
    "lock_profit_enabled": True,
    "lock_trigger_pct": 20.0,
    "lock_distance_pct": 5.0,
    "initial_capital": 100000.0,
    "leverage": 25.0,
    "position_size_pct": 2.0,
    "ambiguous_bar_rule": "STOP_FIRST",
    "debug_mode": False,
    "debug_log_bar_evals": False,
    "show_raw_ha_conditions": False,
}


def settings_json(settings: dict[str, Any] | None = None) -> str:
    return json.dumps(settings or DEFAULT_SETTINGS)
