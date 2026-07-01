"""SOL Reversal signal detection — Pine parity on Heikin Ashi (TV HA chart)."""

from __future__ import annotations

from typing import Any, Literal

import pandas as pd

from app.strategies.sol_reversal.indicators import compute_atr

Side = Literal["BUY"]


def _streak_color(colors: list[str], end_idx: int, color: str) -> int:
    count = 0
    i = end_idx
    while i >= 0 and colors[i] == color:
        count += 1
        i -= 1
    return count


def _passes_strong_candle(row: pd.Series, atr_val: float, settings: dict[str, Any]) -> bool:
    """Pine: (close - open) > strongCandleATRmult * atr"""
    if not settings.get("strong_candle_enabled", True):
        return True
    body = float(row["close"]) - float(row["open"])
    mult = float(settings.get("strong_candle_atr_mult", 0.5))
    return body > mult * atr_val


def _passes_atr(atr_val: float, settings: dict[str, Any]) -> bool:
    """Pine: atr > atrMin"""
    if not settings.get("atr_filter_enabled", True):
        return True
    if pd.isna(atr_val):
        return False
    return float(atr_val) > float(settings.get("atr_minimum", 1.0))


def detect_buy_condition_at_index(
    candles: pd.DataFrame,
    settings: dict[str, Any],
    idx: int,
    *,
    atr: pd.Series | None = None,
) -> Side | None:
    """
    Raw strategy condition (Pine longSignal) — ignores open position.
    Fires on every bar where HA reversal filters pass; use replay/execution for entries.
    """
    if idx < 1 or idx >= len(candles):
        return None

    if atr is None:
        atr = compute_atr(candles, int(settings.get("atr_period", 14)))

    colors = candles["color"].tolist()
    row = candles.iloc[idx]
    atr_val = float(atr.iloc[idx]) if not pd.isna(atr.iloc[idx]) else float("nan")

    min_red = int(settings.get("min_red_candles", 7))
    max_green = int(settings.get("max_green_candles", 3))

    if colors[idx] != "green":
        return None

    red_before = _streak_color(colors, idx - 1, "red")
    greens = _streak_color(colors, idx, "green")
    if red_before < min_red:
        return None
    if not (1 <= greens <= max_green):
        return None
    if not _passes_strong_candle(row, atr_val, settings):
        return None
    if not _passes_atr(atr_val, settings):
        return None
    return "BUY"


def scan_buy_conditions(
    candles: pd.DataFrame,
    settings: dict[str, Any],
    *,
    atr: pd.Series | None = None,
) -> list[dict[str, Any]]:
    """Every bar where the raw BUY condition is true (not executable entries)."""
    if candles.empty:
        return []
    if atr is None:
        atr = compute_atr(candles, int(settings.get("atr_period", 14)))
    out: list[dict[str, Any]] = []
    for idx in range(1, len(candles)):
        if detect_buy_condition_at_index(candles, settings, idx, atr=atr):
            row = candles.iloc[idx]
            out.append({
                "idx": idx,
                "time": int(row["time"]),
                "open": float(row["open"]),
                "close": float(row["close"]),
            })
    return out


# Backward-compatible aliases
detect_signal_at_index = detect_buy_condition_at_index
scan_signals = scan_buy_conditions


def levels_for_side(
    side: Side,
    entry: float,
    settings: dict[str, Any],
) -> tuple[float | None, float | None]:
    """TP/SL from % move in price (Pine tpPerc / slPerc). None when toggle disabled."""
    entry = float(entry)
    tp: float | None = None
    sl: float | None = None
    if settings.get("enable_take_profit", True):
        tp_pct = float(settings.get("take_profit_pct", 40.0)) / 100.0
        tp = round(entry * (1 + tp_pct), 4)
    if settings.get("enable_stop_loss", True):
        sl_pct = float(settings.get("stop_loss_pct", 25.0)) / 100.0
        sl = round(entry * (1 - sl_pct), 4)
    return tp, sl


def price_move_pct(side: str, entry: float, price: float) -> float:
    """Signed % change from entry (long/BUY: up = positive)."""
    entry = float(entry)
    price = float(price)
    if entry <= 0:
        return 0.0
    return round((price - entry) / entry * 100.0, 4)


def target_price_pcts(side: str, entry: float, tp: float | None, sl: float | None) -> tuple[float, float]:
    """TP and SL distances as positive % price move from entry."""
    entry = float(entry)
    if entry <= 0:
        return 0.0, 0.0
    tp_pct = round((float(tp) - entry) / entry * 100.0, 2) if tp is not None else 0.0
    sl_pct = round((entry - float(sl)) / entry * 100.0, 2) if sl is not None else 0.0
    return tp_pct, sl_pct
