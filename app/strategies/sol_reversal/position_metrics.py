"""Single source of truth for open-position peak / lock / stop calculations."""

from __future__ import annotations

from typing import Any

from app.strategies.sol_reversal.strategy import levels_for_side, price_move_pct

CALC_TOLERANCE = 0.001


def peak_move_pct(entry_price: float, highest_since_entry: float) -> float:
    """Peak price move % — always from highest since entry, never current price."""
    entry_price = float(entry_price)
    if entry_price <= 0:
        return 0.0
    return round((float(highest_since_entry) - entry_price) / entry_price * 100.0, 4)


def lock_stop_price(highest_since_lock: float, lock_distance_pct: float) -> float:
    """lockStop = highestSinceLock × (1 − lockDistance%)."""
    return round(float(highest_since_lock) * (1.0 - float(lock_distance_pct) / 100.0), 4)


def _stored_highest_since_entry(position: dict[str, Any], entry: float) -> float:
    raw = position.get("highest_since_entry")
    if raw is not None and float(raw) > 0:
        return float(raw)
    legacy_peak = position.get("highest_profit_pct")
    if legacy_peak and float(legacy_peak) > 0:
        return entry * (1.0 + float(legacy_peak) / 100.0)
    return float(entry)


def _stored_highest_since_lock(position: dict[str, Any]) -> float | None:
    raw = position.get("highest_since_lock")
    if raw is not None and float(raw) > 0:
        return float(raw)
    legacy = position.get("lock_high") or position.get("highest_price")
    if legacy is not None and float(legacy) > 0:
        return float(legacy)
    return None


def compute_position_metrics(
    position: dict[str, Any],
    *,
    bar_high: float,
    bar_low: float,
    bar_close: float,
    settings: dict[str, Any],
    current_price: float | None = None,
    update_peaks: bool = True,
) -> dict[str, Any]:
    """
    Derive every displayed/stored price metric from one internal state.

    Stored variables:
      - entry_price
      - highest_since_entry  (max bar high since open)
      - highest_since_lock   (max bar high since lock activated)
    """
    entry = float(position["entry"])
    high = float(bar_high)
    close = float(bar_close)
    current = float(current_price if current_price is not None else close)

    if update_peaks:
        highest_since_entry = max(_stored_highest_since_entry(position, entry), high)
    else:
        highest_since_entry = _stored_highest_since_entry(position, entry)

    _, original_sl = levels_for_side("BUY", entry, settings)
    stored_initial = position.get("initial_stop_loss")
    if stored_initial is not None and float(stored_initial) > 0:
        original_sl = float(stored_initial)

    peak_pct = peak_move_pct(entry, highest_since_entry)
    current_move_pct = price_move_pct("BUY", entry, current)

    lock_active = bool(position.get("lock_active"))
    highest_since_lock = _stored_highest_since_lock(position)

    trigger_pct = float(settings.get("lock_trigger_pct", 20.0))
    lock_distance_pct = float(settings.get("lock_distance_pct", 5.0))
    trigger_price = round(entry * (1.0 + trigger_pct / 100.0), 4)
    profit_close_pct = price_move_pct("BUY", entry, close)

    lock_stop: float | None = None
    lock_enabled = bool(settings.get("lock_profit_enabled"))

    if lock_enabled and update_peaks:
        should_activate = (
            lock_active
            or high >= trigger_price
            or profit_close_pct >= trigger_pct
        )
        if should_activate:
            lock_active = True
            if highest_since_lock is None:
                highest_since_lock = high
            else:
                highest_since_lock = max(highest_since_lock, high)
            lock_stop = lock_stop_price(highest_since_lock, lock_distance_pct)
    elif lock_enabled and lock_active and highest_since_lock is not None:
        lock_stop = lock_stop_price(highest_since_lock, lock_distance_pct)

    effective_stop = original_sl
    if lock_active and lock_stop is not None:
        effective_stop = (
            lock_stop if original_sl is None else max(float(original_sl), lock_stop)
        )

    expected_peak_pct = peak_move_pct(entry, highest_since_entry)
    expected_lock_stop = (
        lock_stop_price(highest_since_lock, lock_distance_pct)
        if lock_active and highest_since_lock is not None
        else None
    )

    validation_errors: list[str] = []
    if abs(peak_pct - expected_peak_pct) > CALC_TOLERANCE:
        validation_errors.append(
            f"peak_price_move_pct {peak_pct} != expected {expected_peak_pct}"
        )
    if lock_active and expected_lock_stop is not None and lock_stop is not None:
        if abs(lock_stop - expected_lock_stop) > CALC_TOLERANCE:
            validation_errors.append(
                f"lock_stop {lock_stop} != expected {expected_lock_stop}"
            )

    return {
        "entry_price": entry,
        "current_price": current,
        "bar_high": high,
        "bar_low": float(bar_low),
        "bar_close": close,
        "highest_since_entry": round(highest_since_entry, 8),
        "highest_since_lock": round(highest_since_lock, 8) if highest_since_lock is not None else None,
        "peak_price_move_pct": peak_pct,
        "highest_profit_pct": peak_pct,
        "current_price_move_pct": current_move_pct,
        "original_stop_loss": original_sl,
        "lock_stop": lock_stop,
        "effective_stop": effective_stop,
        "lock_active": lock_active,
        "lock_profit_enabled": lock_enabled,
        "trigger_price": trigger_price,
        "lock_trigger_pct": trigger_pct,
        "lock_distance_pct": lock_distance_pct,
        "profit_close_pct": profit_close_pct,
        "validation": {
            "expected_peak_pct": expected_peak_pct,
            "expected_lock_stop": expected_lock_stop,
            "peak_ok": abs(peak_pct - expected_peak_pct) <= CALC_TOLERANCE,
            "lock_stop_ok": (
                not lock_active
                or (
                    expected_lock_stop is not None
                    and lock_stop is not None
                    and abs(lock_stop - expected_lock_stop) <= CALC_TOLERANCE
                )
            ),
            "errors": validation_errors,
            "ok": len(validation_errors) == 0,
        },
        "lock_high": highest_since_lock,
    }


def metrics_debug_payload(metrics: dict[str, Any]) -> dict[str, Any]:
    """Debug / validation panel fields."""
    v = metrics["validation"]
    return {
        "entry": metrics["entry_price"],
        "current_price": metrics["current_price"],
        "highest_since_entry": metrics["highest_since_entry"],
        "highest_since_lock": metrics["highest_since_lock"],
        "peak_price_move_pct": metrics["peak_price_move_pct"],
        "expected_peak_pct": v["expected_peak_pct"],
        "original_stop_loss": metrics["original_stop_loss"],
        "lock_stop": metrics["lock_stop"],
        "expected_lock_stop": v["expected_lock_stop"],
        "effective_stop": metrics["effective_stop"],
        "trigger_price": metrics["trigger_price"],
        "lock_active": metrics["lock_active"],
        "lock_distance_pct": metrics["lock_distance_pct"],
        "validation_ok": v["ok"],
        "validation_errors": v["errors"],
    }
