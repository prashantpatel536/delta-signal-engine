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
        "initial_stop_loss": sl if sl is not None else 0.0,
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


def compute_lock_state(
    position: dict[str, Any],
    *,
    high: float,
    close: float,
    settings: dict[str, Any],
) -> dict[str, Any]:
    """
  Trailing lock profit — once activated, lock stop ratchets up only (never decreases).

    - Activate when high >= entry * (1 + trigger%) or close profit >= trigger%.
    - After activation: highestPriceSinceLock = max(prev, high); lockStop trails peak.
    - effectiveStop = max(originalStopLoss, lockStop).
    """
    entry = float(position["entry"])
    _, original_sl = levels_for_side("BUY", entry, settings)

    lock_active = bool(position.get("lock_active"))
    highest_since_lock = position.get("lock_high")
    prev_lock_stop = position.get("lock_stop")
    lock_stop: float | None = float(prev_lock_stop) if prev_lock_stop is not None else None

    trigger_pct = float(settings.get("lock_trigger_pct", 20.0))
    lock_dist = float(settings.get("lock_distance_pct", 5.0)) / 100.0
    trigger_price = round(entry * (1 + trigger_pct / 100.0), 4)
    profit_close_pct = price_move_pct("BUY", entry, close)

    if settings.get("lock_profit_enabled"):
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
                highest_since_lock = max(float(highest_since_lock), high)
            calculated = round(float(highest_since_lock) * (1 - lock_dist), 4)
            lock_stop = calculated if lock_stop is None else max(lock_stop, calculated)

    effective_stop = original_sl
    if lock_active and lock_stop is not None:
        effective_stop = lock_stop if original_sl is None else max(original_sl, lock_stop)

    return {
        "entry": entry,
        "current_price": close,
        "high": high,
        "lock_active": lock_active,
        "lock_high": highest_since_lock,
        "highest_price_since_lock": highest_since_lock,
        "lock_stop": lock_stop,
        "original_stop_loss": original_sl,
        "effective_stop": effective_stop,
        "trigger_price": trigger_price,
        "trigger_pct": trigger_pct,
        "lock_distance_pct": float(settings.get("lock_distance_pct", 5.0)),
        "profit_close_pct": profit_close_pct,
    }


def lock_debug_payload(
    position: dict[str, Any],
    *,
    high: float,
    close: float,
    settings: dict[str, Any],
) -> dict[str, Any]:
    """Debug fields printed every candle while a position is open."""
    state = compute_lock_state(position, high=high, close=close, settings=settings)
    return {
        "entry": state["entry"],
        "current_price": state["current_price"],
        "bar_high": high,
        "highest_price_since_lock": state["highest_price_since_lock"],
        "original_stop_loss": state["original_stop_loss"],
        "calculated_lock_stop": state["lock_stop"],
        "effective_stop": state["effective_stop"],
        "trigger_price": state["trigger_price"],
        "lock_active": state["lock_active"],
        "lock_trigger_pct": state["trigger_pct"],
        "lock_distance_pct": state["lock_distance_pct"],
        "profit_close_pct": state["profit_close_pct"],
    }


def preview_open_position(
    position: dict[str, Any],
    *,
    live_price: float,
    settings: dict[str, Any],
    bar_high: float | None = None,
) -> dict[str, Any]:
    """Live lock preview between closed HA bars (dashboard display)."""
    entry = float(position["entry"])
    close = float(live_price)
    high = float(bar_high if bar_high is not None else max(live_price, float(position.get("highest_price") or live_price)))
    sim_pos = {
        "entry": entry,
        "lock_active": bool(position.get("lock_active")),
        "lock_high": position.get("highest_price"),
        "lock_stop": position.get("lock_stop"),
        "quantity": position.get("quantity", 1),
    }
    state = compute_lock_state(sim_pos, high=high, close=close, settings=settings)
    _, move_high = pnl_at_price(
        {"entry": entry, "quantity": float(position.get("quantity") or 1), "side": "BUY"},
        high,
    )
    profit_now = price_move_pct("BUY", entry, close)
    peak = max(float(position.get("highest_profit_pct") or 0), profit_now, move_high)

    return {
        "highest_profit_pct": round(peak, 4),
        "price_move_pct": profit_now,
        "lock_active": state["lock_active"],
        "lock_stop": state["lock_stop"],
        "highest_price_since_lock": state["highest_price_since_lock"],
        "original_stop_loss": state["original_stop_loss"],
        "effective_stop": state["effective_stop"],
        "trigger_price": state["trigger_price"],
        "lock_trigger_pct": state["trigger_pct"],
        "lock_profit_enabled": bool(settings.get("lock_profit_enabled")),
    }


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
    original_sl = position.get("initial_stop_loss")
    if original_sl is None:
        original_sl = base_sl
    else:
        original_sl = float(original_sl) if float(original_sl) > 0 else base_sl

    _, pnl_pct_high = pnl_at_price(position, high)
    _, pnl_pct_low = pnl_at_price(position, low)
    mfe = max(float(position.get("mfe_pct") or 0), pnl_pct_high)
    mae = min(float(position.get("mae_pct") or 0), pnl_pct_low)

    lock_state = compute_lock_state(position, high=high, close=close, settings=settings)
    lock_active = lock_state["lock_active"]
    lock_stop = lock_state["lock_stop"]
    lock_high = lock_state["lock_high"]
    effective_stop = lock_state["effective_stop"]

    profit_pct_now = price_move_pct("BUY", entry, close)
    highest_profit = max(float(position.get("highest_profit_pct") or 0), profit_pct_now, pnl_pct_high)

    position = {
        **position,
        "lock_active": lock_active,
        "lock_stop": lock_stop,
        "lock_high": lock_high,
        "initial_stop_loss": original_sl if original_sl is not None else 0.0,
        "effective_stop": effective_stop if effective_stop is not None else 0.0,
        "highest_profit_pct": highest_profit,
        "mfe_pct": mfe,
        "mae_pct": mae,
        "stop_loss": original_sl if original_sl is not None else 0.0,
        "take_profit": tp if tp is not None else round(entry * 10.0, 4),
        "bars_held": int(position.get("bars_held") or 0) + 1,
    }

    exit_price = None
    reason = None
    sl_hit = effective_stop is not None and low <= float(effective_stop)
    if sl_hit:
        exit_price = float(effective_stop)
        reason = "LOCK" if lock_active and lock_stop is not None and exit_price >= float(lock_stop) - 1e-9 else "SL"
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
        "lock_stop": lock_stop,
        "lock_high": lock_high,
        "effective_stop": effective_stop,
        "original_stop_loss": original_sl,
        "stop_loss": original_sl if original_sl is not None else 0.0,
        "take_profit": tp if tp is not None else round(entry * 10.0, 4),
        "initial_stop": original_sl if original_sl is not None else 0.0,
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
