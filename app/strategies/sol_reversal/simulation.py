"""Stateless bar simulation — Pine Script exit logic (long-only)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.contract_specs import contracts_from_notional, sizing_from_contracts
from app.strategies.sol_reversal.strategy import (
    detect_buy_condition_at_index,
    levels_for_side,
    price_move_pct,
    scan_buy_conditions,
)


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
        "stop_loss": sl if sl is not None else 0.0,
        "take_profit": tp if tp is not None else round(entry * 10.0, 4),
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
    base_tp, base_sl = levels_for_side("BUY", entry, settings)
    tp = base_tp
    sl = base_sl

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
            if sl is None:
                sl = lock_stop
            else:
                sl = max(sl, lock_stop)
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
        "stop_loss": sl if sl is not None else 0.0,
        "take_profit": tp if tp is not None else round(entry * 10.0, 4),
        "bars_held": int(position.get("bars_held") or 0) + 1,
    }

    exit_price = None
    reason = None
    if sl is not None and low <= sl:
        exit_price, reason = sl, "LOCK" if lock_active else "SL"
    elif tp is not None and high >= tp:
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
        "stop_loss": sl if sl is not None else 0.0,
        "take_profit": tp if tp is not None else round(entry * 10.0, 4),
        "initial_stop": base_sl if base_sl is not None else 0.0,
        "quantity": position["quantity"],
        "leverage": position["leverage"],
        "margin_used": position["margin_used"],
    }
    return None, closed


def _exit_marker_status(reason: str) -> str:
    if reason == "TP":
        return "TP_HIT"
    if reason == "SL":
        return "SL_HIT"
    return "LOCK_HIT"


def _append_exit(
    exits: list[dict[str, Any]],
    trades: list[dict[str, Any]],
    closed: dict[str, Any],
    *,
    trade_num: int,
) -> float:
    reason = closed["exit_reason"]
    exits.append({
        "candle_time": int(closed["exit_time"]),
        "signal": "BUY",
        "status": _exit_marker_status(reason),
        "exit_reason": reason,
        "pnl_pct": closed["price_move_pct"],
        "trade_num": trade_num,
    })
    trades.append({**closed, "trade_num": trade_num})
    return float(closed["pnl_usd"])


def replay_strategy(
    candles: Any,
    settings: dict[str, Any],
    *,
    atr: Any | None = None,
    initial_equity: float = 100_000.0,
    entry_price_at: Callable[[int, float], float] | None = None,
    on_entry: Callable[[dict[str, Any]], None] | None = None,
    on_open: Callable[[dict[str, Any]], None] | None = None,
    on_close: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """
    Bar-by-bar strategy replay (TradingView pyramiding=0).

    - ``raw_conditions``: every bar where the HA BUY condition is true
    - ``entries``: executable entries only when flat (one per trade)
    - ``exits`` / ``trades``: closed positions
    """
    import pandas as pd

    from app.strategies.sol_reversal.indicators import compute_atr

    if candles.empty or len(candles) < 2:
        return {"entries": [], "exits": [], "raw_conditions": [], "trades": []}

    if atr is None:
        atr = compute_atr(candles, int(settings.get("atr_period", 14)))

    raw = scan_buy_conditions(candles, settings, atr=atr)
    entries: list[dict[str, Any]] = []
    exits: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    position: dict[str, Any] | None = None
    equity = initial_equity
    trade_num = 0
    pending_signal = False
    on_close_entry = bool(settings.get("process_orders_on_close", False))

    def _close_position(closed: dict[str, Any]) -> None:
        nonlocal trade_num, equity, position
        trade_num += 1
        equity += _append_exit(exits, trades, closed, trade_num=trade_num)
        if on_close:
            on_close(closed)
        position = None

    def _open_at(
        idx: int,
        bar_time: int,
        entry_px: float,
        *,
        high: float,
        low: float,
        close: float,
        signal_bar: int,
    ) -> None:
        nonlocal position, equity, pending_signal
        entry = entry_px if entry_price_at is None else entry_price_at(idx, entry_px)
        position = open_position("BUY", entry, bar_time, settings, equity)
        if not position:
            pending_signal = False
            return
        if on_open:
            delta = on_open(position)
            if delta:
                equity += float(delta)
        entry_rec = {
            "candle_time": bar_time,
            "signal": "BUY",
            "status": "ENTRY",
            "entry_price": entry,
            "bar_index": idx,
            "signal_bar_index": signal_bar,
        }
        entries.append(entry_rec)
        if on_entry:
            on_entry(entry_rec)
        pending_signal = False
        position, closed = process_bar(
            position,
            bar_time=bar_time,
            high=high,
            low=low,
            close=close,
            settings=settings,
        )
        if closed:
            _close_position(closed)

    for idx in range(1, len(candles)):
        row = candles.iloc[idx]
        bar_time = int(row["time"])
        open_px = float(row["open"])
        high = float(row["high"])
        low = float(row["low"])
        close = float(row["close"])

        filled_this_bar = False
        if position is None and pending_signal:
            _open_at(
                idx,
                bar_time,
                open_px,
                high=high,
                low=low,
                close=close,
                signal_bar=idx - 1,
            )
            filled_this_bar = position is not None or not pending_signal

        if position and not filled_this_bar:
            position, closed = process_bar(
                position,
                bar_time=bar_time,
                high=high,
                low=low,
                close=close,
                settings=settings,
            )
            if closed:
                _close_position(closed)

        if position is None and not pending_signal and detect_buy_condition_at_index(
            candles, settings, idx, atr=atr
        ):
            if on_close_entry:
                _open_at(
                    idx,
                    bar_time,
                    close,
                    high=high,
                    low=low,
                    close=close,
                    signal_bar=idx,
                )
            else:
                pending_signal = True

    return {
        "entries": entries,
        "exits": exits,
        "raw_conditions": raw,
        "trades": trades,
        "final_equity": equity,
    }
