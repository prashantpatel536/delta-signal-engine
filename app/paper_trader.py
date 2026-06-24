"""Pure functions for virtual position PnL, margin, and exit checks."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from app.contract_specs import contracts_from_notional, sizing_from_contracts

Side = Literal["BUY", "SELL"]
ExitReason = Literal["TP", "SL", "MANUAL", "Opposite Signal"]


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
    symbol: str = "BTCUSDT",
) -> tuple[float, float, float, int]:
    """
    Delta contract model: margin % of available → target notional → whole contracts.

    Returns (margin_used, position_value, base_quantity, contracts).
    """
    pct = max(0.0, min(float(margin_percent), 100.0))
    avail = max(float(available_margin), 0.0)
    lev = max(float(leverage), 1.0)
    entry = float(entry_price)

    margin_used = round(avail * pct / 100.0, 2)
    target_notional = round(margin_used * lev, 2)
    contract_count = contracts_from_notional(target_notional, entry, symbol)
    sized = sizing_from_contracts(contract_count, entry, symbol, lev)
    return (
        sized["margin_used"],
        sized["position_value"],
        sized["quantity"],
        int(sized["contracts"]),
    )


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
    if exit_reason == "Opposite Signal":
        return "OPPOSITE SIGNAL"
    if exit_reason:
        return str(exit_reason).strip().upper()
    return None


def safe_duration_seconds(opened_at: str | None, closed_at: str | None) -> float:
    if not opened_at or not closed_at:
        return 0.0
    try:
        opened = datetime.fromisoformat(str(opened_at).replace("Z", "+00:00"))
        closed = datetime.fromisoformat(str(closed_at).replace("Z", "+00:00"))
        return max(0.0, (closed - opened).total_seconds())
    except (ValueError, TypeError, AttributeError):
        return 0.0


def normalize_side(side: str | None) -> Side:
    value = str(side or "").upper()
    return "SELL" if value == "SELL" else "BUY"


def normalize_exit_reason(exit_reason: str | None) -> str | None:
    if exit_reason is None:
        return None
    value = str(exit_reason).strip()
    if not value:
        return None
    upper = value.upper()
    if upper == "TP":
        return "TP"
    if upper == "SL":
        return "SL"
    if upper == "MANUAL":
        return "MANUAL"
    if upper in {"OPPOSITE SIGNAL", "OPPOSITE"} or "OPPOSITE" in upper:
        return "Opposite Signal"
    return value


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        number = float(value)
        if number != number or number in (float("inf"), float("-inf")):
            return default
        return number
    except (TypeError, ValueError):
        return default


def safe_optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
        if number != number or number in (float("inf"), float("-inf")):
            return None
        return number
    except (TypeError, ValueError):
        return None


def safe_iso_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def build_closed_trade_payload(position: dict[str, Any]) -> dict[str, Any]:
    """Normalize a closed position row for /trade-history responses."""
    entry = safe_float(position.get("entry"))
    exit_price = safe_optional_float(position.get("exit_price"))
    stop_loss_raw = position.get("stop_loss")
    take_profit_raw = position.get("take_profit")
    stop_loss = safe_float(stop_loss_raw, entry) if stop_loss_raw is not None else entry
    take_profit = safe_float(take_profit_raw, entry) if take_profit_raw is not None else entry
    side = normalize_side(position.get("side"))
    pnl = safe_float(position.get("pnl"), 0.0)
    margin = safe_float(position.get("margin_used"), 0.0)
    exit_reason = normalize_exit_reason(position.get("exit_reason"))

    price_points = safe_optional_float(position.get("price_points"))
    if price_points is None and exit_price is not None:
        price_points = realized_points(side, entry, exit_price)

    opened_at = safe_iso_text(position.get("opened_at")) or ""
    closed_at = safe_iso_text(position.get("closed_at"))
    duration = safe_duration_seconds(opened_at, closed_at)
    roe = calculate_roe(pnl, margin) if margin > 0 else None

    signal_id_raw = position.get("signal_id")
    signal_id = int(signal_id_raw) if signal_id_raw is not None else None

    position_id = position.get("id")
    if position_id is None:
        raise ValueError("closed position missing id")

    return {
        "id": int(position_id),
        "signal_id": signal_id,
        "symbol": str(position.get("symbol") or "UNKNOWN"),
        "side": side,
        "entry": entry,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "original_stop_loss": safe_optional_float(position.get("original_stop_loss")),
        "original_take_profit": safe_optional_float(position.get("original_take_profit")),
        "risk_reward": safe_float(position.get("risk_reward"), 0.0),
        "quantity": safe_float(position.get("quantity"), 1.0),
        "leverage": safe_float(position.get("leverage"), 1.0),
        "margin_used": margin,
        "position_value": safe_float(position.get("position_value"), 0.0),
        "status": "CLOSED",
        "opened_at": opened_at,
        "closed_at": closed_at,
        "exit_price": exit_price,
        "exit_reason": exit_reason,
        "pnl": pnl,
        "price_points": price_points,
        "account_impact_pct": safe_optional_float(position.get("account_impact_pct")),
        "roe": roe,
        "result": trade_result(pnl),
        "duration_seconds": duration,
        "duration": format_duration_seconds(duration),
        "exit_status": exit_status_label(exit_reason),
    }


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
