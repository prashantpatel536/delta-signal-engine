"""Stateless bar simulation — shared by SOL paper trading and backtesting."""

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
    margin_pct = float(settings.get("position_size_pct", 50.0)) / 100.0
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
    tp, sl = levels_for_side(side, entry, settings)
    return {
        "symbol": symbol,
        "side": side,
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
        "highest_profit_pct": 0.0,
        "mfe_pct": 0.0,
        "mae_pct": 0.0,
        "bars_held": 0,
    }


def pnl_at_price(position: dict[str, Any], price: float) -> tuple[float, float]:
    entry = float(position["entry"])
    qty = float(position["quantity"])
    side = position["side"]
    move_pct = price_move_pct(side, entry, price)
    if side == "BUY":
        pnl = (price - entry) * qty
    else:
        pnl = (entry - price) * qty
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
    Process one closed bar on an open position.
    Returns (updated_position, closed_trade). closed_trade set when exited.
    """
    side = position["side"]
    entry = float(position["entry"])
    sl = float(position["stop_loss"])
    tp = float(position["take_profit"])

    _, pnl_pct_high = pnl_at_price(position, high if side == "BUY" else low)
    _, pnl_pct_low = pnl_at_price(position, low if side == "BUY" else high)
    mfe = max(float(position.get("mfe_pct") or 0), pnl_pct_high)
    mae = min(float(position.get("mae_pct") or 0), pnl_pct_low)

    lock_active = bool(position.get("lock_active"))
    lock_stop = position.get("lock_stop")
    highest_profit = max(float(position.get("highest_profit_pct") or 0), pnl_pct_high)

    if settings.get("lock_profit_enabled") and highest_profit >= float(settings.get("lock_trigger_pct", 3.0)):
        lock_active = True
        dist = float(settings.get("lock_distance_pct", 3.0)) / 100.0
        if side == "BUY":
            lock_stop = round(high * (1 - dist), 4)
            sl = max(sl, lock_stop)
        else:
            lock_stop = round(low * (1 + dist), 4)
            sl = min(sl, lock_stop)

    position = {
        **position,
        "lock_active": lock_active,
        "lock_stop": lock_stop,
        "highest_profit_pct": highest_profit,
        "mfe_pct": mfe,
        "mae_pct": mae,
        "stop_loss": sl,
        "bars_held": int(position.get("bars_held") or 0) + 1,
    }

    exit_price = None
    reason = None
    if side == "BUY":
        if low <= sl:
            exit_price, reason = sl, "LOCK" if lock_active else "SL"
        elif high >= tp:
            exit_price, reason = tp, "TP"
    else:
        if high >= sl:
            exit_price, reason = sl, "LOCK" if lock_active else "SL"
        elif low <= tp:
            exit_price, reason = tp, "TP"

    if exit_price is None:
        return position, None

    pnl_usd, price_move = pnl_at_price(position, exit_price)
    closed = {
        "side": side,
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
        "initial_stop": float(levels_for_side(side, entry, settings)[1]),
        "quantity": position["quantity"],
        "leverage": position["leverage"],
        "margin_used": position["margin_used"],
    }
    return None, closed
