"""Pure functions for virtual position PnL, margin, and exit checks."""

from __future__ import annotations

from typing import Literal

Side = Literal["BUY", "SELL"]
ExitReason = Literal["TP", "SL", "MANUAL"]


def position_value(entry: float, quantity: float) -> float:
    return round(float(entry) * float(quantity), 2)


def required_margin(position_value_usd: float, leverage: float) -> float:
    lev = max(float(leverage), 1.0)
    return round(float(position_value_usd) / lev, 2)


def calculate_from_margin_allocation(
    available_margin: float,
    margin_percent: float,
    leverage: float,
    entry_price: float,
) -> tuple[float, float, float]:
    """Delta model: margin % of available → position value → quantity."""
    pct = max(0.0, min(float(margin_percent), 100.0))
    avail = max(float(available_margin), 0.0)
    lev = max(float(leverage), 1.0)
    entry = float(entry_price)

    margin_used = round(avail * pct / 100.0, 2)
    position_value = round(margin_used * lev, 2)
    quantity = round(position_value / entry, 6) if entry > 0 else 0.0
    return margin_used, position_value, quantity


def calculate_pnl(side: str, entry: float, exit_price: float, quantity: float = 1.0) -> float:
    entry = float(entry)
    exit_price = float(exit_price)
    qty = float(quantity)
    if side == "BUY":
        return round((exit_price - entry) * qty, 2)
    return round((entry - exit_price) * qty, 2)


def calculate_roe(pnl: float, margin_used: float) -> float:
    margin = float(margin_used)
    if margin <= 0:
        return 0.0
    return round(float(pnl) / margin * 100, 2)


def validate_position_levels(
    side: str,
    entry: float,
    stop_loss: float,
    take_profit: float,
) -> None:
    """Ensure SL/TP are on the correct side of entry for LONG/SHORT."""
    entry = float(entry)
    sl = float(stop_loss)
    tp = float(take_profit)
    if entry <= 0 or sl <= 0 or tp <= 0:
        raise ValueError("Entry, stop loss, and take profit must be positive")
    if side == "BUY":
        if not (sl <= entry < tp):
            raise ValueError(
                "LONG: stop loss must be at or below entry and take profit above entry"
            )
    else:
        if not (tp < entry <= sl):
            raise ValueError(
                "SHORT: take profit must be below entry and stop loss at or above entry"
            )


def risk_reward_usd(
    side: str,
    entry: float,
    stop_loss: float,
    take_profit: float,
    quantity: float,
) -> tuple[float, float, float]:
    entry = float(entry)
    qty = float(quantity)
    if side == "BUY":
        risk = (entry - float(stop_loss)) * qty
        reward = (float(take_profit) - entry) * qty
    else:
        risk = (float(stop_loss) - entry) * qty
        reward = (entry - float(take_profit)) * qty
    risk = round(abs(risk), 2)
    reward = round(abs(reward), 2)
    rr = round(reward / risk, 2) if risk > 0 else 0.0
    return risk, reward, rr


def excursion_points(side: str, entry: float, price: float) -> tuple[float, float]:
    """Return (favorable, adverse) price excursion from entry in points."""
    entry = float(entry)
    price = float(price)
    if side == "BUY":
        favorable = max(price - entry, 0.0)
        adverse = max(entry - price, 0.0)
    else:
        favorable = max(entry - price, 0.0)
        adverse = max(price - entry, 0.0)
    return round(favorable, 4), round(adverse, 4)


def reward_points(side: str, entry: float, take_profit: float) -> float:
    """Hypothetical reward in price points if TP is hit."""
    entry = float(entry)
    tp = float(take_profit)
    if side == "BUY":
        return round(max(tp - entry, 0.0), 4)
    return round(max(entry - tp, 0.0), 4)


def risk_points(side: str, entry: float, stop_loss: float) -> float:
    """Hypothetical risk in price points if SL is hit."""
    entry = float(entry)
    sl = float(stop_loss)
    if side == "BUY":
        return round(max(entry - sl, 0.0), 4)
    return round(max(sl - entry, 0.0), 4)


def realized_points(side: str, entry: float, exit_price: float) -> float:
    """Signed P/L in price points for a closed hypothetical trade."""
    entry = float(entry)
    exit_price = float(exit_price)
    if side == "BUY":
        return round(exit_price - entry, 4)
    return round(entry - exit_price, 4)


def check_exit_reason(
    side: str,
    price: float,
    stop_loss: float,
    take_profit: float,
) -> ExitReason | None:
    """Return TP or SL when price hits target; None if still open."""
    price = float(price)
    if side == "BUY":
        if price >= take_profit:
            return "TP"
        if price <= stop_loss:
            return "SL"
    else:
        if price <= take_profit:
            return "TP"
        if price >= stop_loss:
            return "SL"
    return None


def check_candle_exit(
    side: str,
    *,
    high: float,
    low: float,
    stop_loss: float,
    take_profit: float,
) -> tuple[ExitReason | None, float | None]:
    """Return TP/SL if a candle's range touched a level (SL checked before TP)."""
    high = float(high)
    low = float(low)
    sl = float(stop_loss)
    tp = float(take_profit)
    if side == "BUY":
        if low <= sl:
            return "SL", sl
        if high >= tp:
            return "TP", tp
    else:
        if high >= sl:
            return "SL", sl
        if low <= tp:
            return "TP", tp
    return None, None


def exit_status_label(exit_reason: str | None) -> str | None:
    if exit_reason == "TP":
        return "TP HIT"
    if exit_reason == "SL":
        return "SL HIT"
    if exit_reason == "MANUAL":
        return "CLOSED"
    return None


def trade_result(pnl: float) -> str:
    return "WIN" if pnl > 0 else "LOSS"


def format_duration_seconds(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    return f"{hours}h {minutes}m"
