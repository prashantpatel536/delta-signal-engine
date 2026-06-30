"""SOL Reversal signal detection on Heikin Ashi candles."""

from __future__ import annotations

from typing import Any, Literal

import pandas as pd

from app.strategies.sol_reversal.indicators import compute_atr

Side = Literal["BUY", "SELL"]


def _streak_color(colors: list[str], end_idx: int, color: str) -> int:
    count = 0
    i = end_idx
    while i >= 0 and colors[i] == color:
        count += 1
        i -= 1
    return count


def _passes_strong_candle(row: pd.Series, settings: dict[str, Any]) -> bool:
    if not settings.get("strong_candle_enabled", True):
        return True
    body = abs(float(row["close"]) - float(row["open"]))
    base = max(abs(float(row["open"])), 1e-9)
    min_body = base * float(settings.get("strong_candle_body_pct", 0.15)) / 100.0
    return body >= min_body


def _passes_atr(row: pd.Series, atr_val: float, settings: dict[str, Any]) -> bool:
    if not settings.get("atr_filter_enabled", True):
        return True
    if pd.isna(atr_val) or atr_val < float(settings.get("atr_minimum", 0.1)):
        return False
    body = abs(float(row["close"]) - float(row["open"]))
    return body >= atr_val * float(settings.get("atr_multiplier", 0.2))


def detect_signal_at_index(
    ha: pd.DataFrame,
    settings: dict[str, Any],
    idx: int,
    *,
    atr: pd.Series | None = None,
) -> Side | None:
    """Evaluate reversal signal on closed HA candle at index."""
    if idx < 1 or idx >= len(ha):
        return None

    if atr is None:
        atr = compute_atr(ha, int(settings.get("atr_period", 14)))

    colors = ha["color"].tolist()
    row = ha.iloc[idx]
    atr_val = float(atr.iloc[idx]) if not pd.isna(atr.iloc[idx]) else 0.0

    min_red = int(settings.get("min_red_candles", 4))
    max_green = int(settings.get("max_green_candles", 2))

    # BUY: red streak then green reversal
    if colors[idx] == "green":
        red_before = _streak_color(colors, idx - 1, "red")
        if red_before >= min_red:
            greens = _streak_color(colors, idx, "green")
            if 1 <= greens <= max_green:
                if _passes_strong_candle(row, settings) and _passes_atr(row, atr_val, settings):
                    return "BUY"

    # SELL: green streak then red reversal (symmetric)
    if colors[idx] == "red":
        green_before = _streak_color(colors, idx - 1, "green")
        if green_before >= min_red:
            reds = _streak_color(colors, idx, "red")
            if 1 <= reds <= max_green:
                if _passes_strong_candle(row, settings) and _passes_atr(row, atr_val, settings):
                    return "SELL"

    return None


def levels_for_side(
    side: Side,
    entry: float,
    settings: dict[str, Any],
) -> tuple[float, float]:
    tp_pct = float(settings.get("take_profit_pct", 7.0)) / 100.0
    sl_pct = float(settings.get("stop_loss_pct", 1.0)) / 100.0
    if side == "BUY":
        return round(entry * (1 + tp_pct), 4), round(entry * (1 - sl_pct), 4)
    return round(entry * (1 - tp_pct), 4), round(entry * (1 + sl_pct), 4)
