"""Stateless bar simulation — Pine Script exit logic (long-only)."""

from __future__ import annotations

from typing import Any

from app.contract_specs import contracts_from_notional, sizing_from_contracts
from app.strategies.sol_reversal.strategy import levels_for_side, price_move_pct


def size_position(
    equity: float,
    entry: float,
    settings: dict[str, Any],
    symbol: str = "SOLUSDT",
) -> dict[str, Any] | None:
    margin_pct = float(settings.get("position_size_pct", 2.0)) / 100.0
    leverage = float(settings.get("leverage", 25.0))
    margin = equity * margin_pct
    notional = margin * leverage
    contracts = contracts_from_notional(notional, entry, symbol)
    if contracts <= 0:
        return None
    sized = sizing_from_contracts(contracts, entry, symbol, leverage)
    sized["margin_allocated"] = round(margin, 2)
    sized["equity"] = round(equity, 2)
    return sized


def open_position(
    side: str,
    entry: float,
    entry_time: int,
    settings: dict[str, Any],
    equity: float,
    symbol: str = "SOLUSDT",
) -> dict[str, Any] | None:
    sized = size_position(equity, entry, settings, symbol)
    if not sized:
        return None
    tp, sl = levels_for_side("BUY", entry, settings)
    return {
        "symbol": symbol,
        "side": "BUY",
        "entry": entry,
        "entry_time": entry_time,
        "stop_loss": sl,
        "take_profit": tp,
        "quantity": sized["quantity"],
        "leverage": float(settings.get("leverage", 25.0)),
        "margin_used": sized["margin_used"],
        "position_value": sized["position_value"],
        "lock_active": False,
        "lock_stop": None,
        "lock_high": None,
        "highest_profit_pct": 0.0,
        "mfe_pct": 0.0,
        "mae_pct": 0.0,
        "bars_held": 0,
    }


def pnl_at_price(position: dict[str, Any], price: float) -> tuple[float, float]:
    entry = float(position["entry"])
    qty = float(position["quantity"])
    pnl = (price - entry) * qty
    move_pct = price_move_pct("BUY", entry, price)
    return round(pnl, 4), move_pct


def process_bar(
    position: dict[str, Any],
    *,
    bar_time: int,
    high: float,
    low: float,
    close: float,
    settings: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """
    Process one bar on an open long — Pine TP/SL + continuous lock profit.
    Returns (updated_position, closed_trade).
    """
    entry = float(position["entry"])
    sl = float(position["stop_loss"])
    tp = float(position["take_profit"])
    base_sl = float(levels_for_side("BUY", entry, settings)[1])

    _, pnl_pct_high = pnl_at_price(position, high)
    _, pnl_pct_low = pnl_at_price(position, low)
    mfe = max(float(position.get("mfe_pct") or 0), pnl_pct_high)
    mae = min(float(position.get("mae_pct") or 0), pnl_pct_low)

    profit_pct_now = price_move_pct("BUY", entry, close)
    lock_high = position.get("lock_high")
    lock_active = False
    lock_stop = position.get("lock_stop")

    if settings.get("lock_profit_enabled"):
        trigger = float(settings.get("lock_trigger_pct", 20.0))
        lock_sl_pct = float(settings.get("lock_distance_pct", 5.0)) / 100.0
        if profit_pct_now >= trigger:
            lock_high = high if lock_high is None else max(float(lock_high), high)
            lock_stop = round(float(lock_high) * (1 - lock_sl_pct), 4)
            sl = max(base_sl, lock_stop)
            lock_active = True
        else:
            lock_high = None
            lock_stop = None
            sl = base_sl

    highest_profit = max(float(position.get("highest_profit_pct") or 0), profit_pct_now, pnl_pct_high)

    position = {
        **position,
        "lock_active": lock_active,
        "lock_stop": lock_stop,
        "lock_high": lock_high,
        "highest_profit_pct": highest_profit,
        "mfe_pct": mfe,
        "mae_pct": mae,
        "stop_loss": sl,
        "bars_held": int(position.get("bars_held") or 0) + 1,
    }

    exit_price = None
    reason = None
    if low <= sl:
        exit_price, reason = sl, "LOCK" if lock_active else "SL"
    elif high >= tp:
        exit_price, reason = tp, "TP"

    if exit_price is None:
        return position, None

    pnl_usd, price_move = pnl_at_price(position, exit_price)
    closed = {
        "side": "BUY",
        "entry_time": int(position["entry_time"]),
        "exit_time": bar_time,
        "entry_price": entry,
        "exit_price": exit_price,
        "price_move_pct": price_move,
        "pnl_usd": pnl_usd,
        "bars_held": position["bars_held"],
        "exit_reason": reason,
        "mfe_pct": mfe,
        "mae_pct": mae,
        "lock_active": lock_active,
        "highest_profit_pct": highest_profit,
        "stop_loss": sl,
        "take_profit": tp,
        "initial_stop": base_sl,
        "quantity": position["quantity"],
        "leverage": position["leverage"],
        "margin_used": position["margin_used"],
    }
    return None, closed
