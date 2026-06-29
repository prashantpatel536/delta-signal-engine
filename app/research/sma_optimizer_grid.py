"""SMA parameter grid builder for SMA Signal Optimizer."""

from __future__ import annotations

from typing import Any


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


def _irange(start: int, end: int, step: int) -> list[int]:
    if step <= 0:
        raise ValueError("step must be positive")
    return list(range(int(start), int(end) + 1, int(step)))


def build_sma_grid(request: dict[str, Any]) -> dict[str, Any]:
    sma_values = _irange(request["sma_start"], request["sma_end"], request["sma_step"])
    stop_values = _frange(request["stop_start"], request["stop_end"], request["stop_step"])
    target_values = _frange(request["target_start"], request["target_end"], request["target_step"])

    combos: list[dict[str, float | int]] = []
    for sma in sma_values:
        for stop in stop_values:
            for target in target_values:
                combos.append({
                    "sma_length": int(sma),
                    "stop_points": float(stop),
                    "target_points": float(target),
                })

    expected = len(sma_values) * len(stop_values) * len(target_values)
    return {
        "sma_values": sma_values,
        "sma_count": len(sma_values),
        "stop_values": stop_values,
        "stop_count": len(stop_values),
        "target_values": target_values,
        "target_count": len(target_values),
        "expected_combinations": expected,
        "final_combinations": len(combos),
        "combination_formula": f"{len(sma_values)} × {len(stop_values)} × {len(target_values)} = {expected}",
        "combinations": combos,
    }
