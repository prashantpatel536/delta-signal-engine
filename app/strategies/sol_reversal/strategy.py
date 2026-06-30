"""SOL Reversal signal detection — Pine Script parity (long-only, HA chart series)."""

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


def detect_signal_at_index(
    ha: pd.DataFrame,
    settings: dict[str, Any],
    idx: int,
    *,
    atr: pd.Series | None = None,
) -> Side | None:
    """Evaluate long entry on closed HA candle — mirrors Pine longSignal."""
    if idx < 1 or idx >= len(ha):
        return None

    if atr is None:
        atr = compute_atr(ha, int(settings.get("atr_period", 14)))

    colors = ha["color"].tolist()
    row = ha.iloc[idx]
    atr_val = float(atr.iloc[idx]) if not pd.isna(atr.iloc[idx]) else 0.0

    min_red = int(settings.get("min_red_candles", 7))
    max_green = int(settings.get("max_green_candles", 3))

    # Pine: validGreenSeq and consecReds[1] >= minConsecReds on green bar
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


def levels_for_side(
    side: Side,
    entry: float,
    settings: dict[str, Any],
) -> tuple[float, float]:
    """TP/SL from % move in price (Pine tpPerc / slPerc)."""
    tp_pct = float(settings.get("take_profit_pct", 40.0)) / 100.0
    sl_pct = float(settings.get("stop_loss_pct", 25.0)) / 100.0
    return round(entry * (1 + tp_pct), 4), round(entry * (1 - sl_pct), 4)


def price_move_pct(side: str, entry: float, price: float) -> float:
    """Signed % change from entry (long/BUY: up = positive)."""
    entry = float(entry)
    price = float(price)
    if entry <= 0:
        return 0.0
    return round((price - entry) / entry * 100.0, 4)


def target_price_pcts(side: str, entry: float, tp: float, sl: float) -> tuple[float, float]:
    """TP and SL distances as positive % price move from entry."""
    entry = float(entry)
    if entry <= 0:
        return 0.0, 0.0
    tp_pct = round((float(tp) - entry) / entry * 100.0, 2)
    sl_pct = round((entry - float(sl)) / entry * 100.0, 2)
    return tp_pct, sl_pct
