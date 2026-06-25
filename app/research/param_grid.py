"""Parameter grid generation and combination accounting for BTC optimizer."""

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


def _int_range(start: float, end: float, step: float) -> list[int]:
    return [int(v) for v in _frange(start, end, step)]


def analyze_param_grid(request: dict[str, Any]) -> dict[str, Any]:
    """
    Build every parameter value, count expected combinations, and explain skips.
    Expected = Gap count × MinSL count × MaxSL count.
    """
    gap_values = _frange(request["gap_start"], request["gap_end"], request["gap_step"])
    min_sl_values = _int_range(request["min_sl_start"], request["min_sl_end"], request["min_sl_step"])
    max_sl_values = _int_range(request["max_sl_start"], request["max_sl_end"], request["max_sl_step"])

    gap_count = len(gap_values)
    min_sl_count = len(min_sl_values)
    max_sl_count = len(max_sl_values)
    expected = gap_count * min_sl_count * max_sl_count

    combinations: list[dict[str, float]] = []
    skipped: list[dict[str, Any]] = []

    for gap in gap_values:
        for min_sl in min_sl_values:
            for max_sl in max_sl_values:
                if min_sl > max_sl:
                    skipped.append({
                        "gap_filter_pct": gap,
                        "min_sl_points": float(min_sl),
                        "max_sl_points": float(max_sl),
                        "reason": "MinSL > MaxSL",
                    })
                else:
                    combinations.append({
                        "gap_filter_pct": gap,
                        "min_sl_points": float(min_sl),
                        "max_sl_points": float(max_sl),
                    })

    skipped_count = len(skipped)
    final_count = len(combinations)
    mismatch_reason = None
    if expected != skipped_count + final_count:
        mismatch_reason = (
            f"Arithmetic mismatch: expected {expected} != skipped {skipped_count} + final {final_count}"
        )

    skip_reasons: dict[str, int] = {}
    for item in skipped:
        reason = str(item.get("reason") or "Unknown")
        skip_reasons[reason] = skip_reasons.get(reason, 0) + 1

    formula = f"{gap_count} × {min_sl_count} × {max_sl_count} = {expected}"

    return {
        "gap_values": gap_values,
        "gap_count": gap_count,
        "min_sl_values": min_sl_values,
        "min_sl_count": min_sl_count,
        "max_sl_values": max_sl_values,
        "max_sl_count": max_sl_count,
        "expected_combinations": expected,
        "skipped_combinations": skipped_count,
        "skip_reasons": skip_reasons,
        "skipped_details": skipped,
        "final_tested_combinations": final_count,
        "actual_generated_combinations": final_count,
        "combination_formula": formula,
        "mismatch_reason": mismatch_reason,
        "combinations": combinations,
    }


def build_param_combinations(request: dict[str, Any]) -> list[dict[str, float]]:
    return analyze_param_grid(request)["combinations"]
