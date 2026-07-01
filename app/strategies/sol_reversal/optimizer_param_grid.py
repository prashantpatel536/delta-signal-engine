"""SOL Reversal parameter grid for optimizer (research only)."""

from __future__ import annotations

from itertools import product
from typing import Any

OPTIMIZABLE_KEYS = (
    "min_red_candles",
    "stop_loss_pct",
    "take_profit_pct",
    "lock_trigger_pct",
    "lock_distance_pct",
    "atr_minimum",
    "atr_period",
    "max_green_candles",
    "strong_candle_atr_mult",
    "leverage",
    "position_size_pct",
)


def _frange(start: float, end: float, step: float) -> list[float]:
    if step <= 0:
        raise ValueError("step must be positive")
    values: list[float] = []
    current = float(start)
    end_f = float(end)
    while current <= end_f + 1e-9:
        values.append(round(current, 6))
        current += step
    return values


def _values_for_range(spec: dict[str, Any]) -> list[Any]:
    start = spec["start"]
    end = spec["end"]
    step = spec["step"]
    if isinstance(start, int) and isinstance(end, int) and float(step).is_integer():
        return [int(v) for v in _frange(float(start), float(end), float(step))]
    return _frange(float(start), float(end), float(step))


def analyze_sol_param_grid(request: dict[str, Any]) -> dict[str, Any]:
    """
    Build parameter combinations from ``ranges`` dict.

    Each range: ``{"start": x, "end": y, "step": z}``.
    Keys must be subset of OPTIMIZABLE_KEYS.
    """
    ranges = request.get("ranges") or {}
    if not ranges:
        raise ValueError("At least one parameter range is required")

    axis_names: list[str] = []
    axis_values: list[list[Any]] = []
    for key, spec in ranges.items():
        if key not in OPTIMIZABLE_KEYS:
            raise ValueError(f"Unknown optimizable key: {key}")
        vals = _values_for_range(spec)
        if not vals:
            raise ValueError(f"Empty range for {key}")
        axis_names.append(key)
        axis_values.append(vals)

    combinations: list[dict[str, Any]] = []
    for combo in product(*axis_values):
        combinations.append(dict(zip(axis_names, combo)))

    expected = 1
    for vals in axis_values:
        expected *= len(vals)

    return {
        "axis_names": axis_names,
        "axis_values": {name: vals for name, vals in zip(axis_names, axis_values)},
        "expected_combinations": expected,
        "combinations": combinations,
        "final_tested_combinations": len(combinations),
    }
