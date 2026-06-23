"""Delta-style risk matrix, liquidation, and account-impact calculations."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any, Literal

from app.config import settings
from app.paper_trader import (
    calculate_from_margin_allocation,
    calculate_pnl,
    calculate_roe,
    risk_points,
    reward_points,
)

LiqStatus = Literal["SAFE", "CAUTION", "DANGER"]

DEFAULT_LEVERAGE = 25
DEFAULT_MARGIN_PERCENT = 50
APPLIED_RISK_ACCOUNT_PCT = 20.0
APPLIED_REWARD_ACCOUNT_PCT = 50.0
RISK_MATRIX_LOSS_PCTS = (10.0, 20.0, 30.0)
RISK_MATRIX_GAIN_PCTS = (25.0, 50.0, 100.0)
LIQ_BUFFER_SAFE = 2.0
LIQ_BUFFER_CAUTION = 1.2


def trading_leverage() -> float:
    return float(settings.default_leverage)


def trading_margin_percent() -> float:
    return float(settings.default_margin_percent)


def point_distance_for_account_impact(
    entry: float,
    account_impact_pct: float,
    *,
    margin_percent: float | None = None,
    leverage: float | None = None,
) -> float:
    """Price points move that produce `account_impact_pct` gain/loss on the account."""
    entry = float(entry)
    margin_pct = float(margin_percent if margin_percent is not None else trading_margin_percent())
    lev = float(leverage if leverage is not None else trading_leverage())
    if entry <= 0 or margin_pct <= 0 or lev <= 0:
        return 0.0
    return round(entry * float(account_impact_pct) / (margin_pct * lev), 4)


def price_level_for_account_impact(
    side: str,
    entry: float,
    account_impact_pct: float,
    *,
    gain: bool,
    margin_percent: float | None = None,
    leverage: float | None = None,
) -> float:
    dist = point_distance_for_account_impact(
        entry,
        account_impact_pct,
        margin_percent=margin_percent,
        leverage=leverage,
    )
    entry = float(entry)
    if side == "BUY":
        return round(entry + dist if gain else entry - dist, 2)
    return round(entry - dist if gain else entry + dist, 2)


def standard_sizing(
    balance: float,
    entry: float,
    *,
    margin_percent: float | None = None,
    leverage: float | None = None,
) -> dict[str, float]:
    margin_pct = float(margin_percent if margin_percent is not None else trading_margin_percent())
    lev = float(leverage if leverage is not None else trading_leverage())
    margin_used, position_value, quantity = calculate_from_margin_allocation(
        balance,
        margin_pct,
        lev,
        entry,
    )
    return {
        "balance": round(float(balance), 2),
        "margin_percent": margin_pct,
        "leverage": lev,
        "margin_used": margin_used,
        "position_value": position_value,
        "quantity": quantity,
    }


def liquidation_price(side: str, entry: float, leverage: float | None = None) -> float:
    """Approximate liquidation price for isolated margin (maintenance ignored)."""
    entry = float(entry)
    lev = max(float(leverage if leverage is not None else trading_leverage()), 1.0)
    if side == "BUY":
        return round(entry * (1.0 - 1.0 / lev), 2)
    return round(entry * (1.0 + 1.0 / lev), 2)


def distance_to_liquidation(side: str, entry: float, leverage: float | None = None) -> float:
    entry = float(entry)
    liq = liquidation_price(side, entry, leverage)
    if side == "BUY":
        return round(max(entry - liq, 0.0), 4)
    return round(max(liq - entry, 0.0), 4)


def liquidation_pct(leverage: float | None = None) -> float:
    lev = max(float(leverage if leverage is not None else trading_leverage()), 1.0)
    return round(100.0 / lev, 2)


def sl_distance(side: str, entry: float, stop_loss: float) -> float:
    return risk_points(side, entry, stop_loss)


def liq_buffer_ratio(
    side: str,
    entry: float,
    applied_sl: float,
    leverage: float | None = None,
) -> float:
    sl_dist = sl_distance(side, entry, applied_sl)
    liq_dist = distance_to_liquidation(side, entry, leverage)
    if sl_dist <= 0:
        return 0.0
    return round(liq_dist / sl_dist, 2)


def liq_status_from_buffer(buffer: float) -> LiqStatus:
    if buffer >= LIQ_BUFFER_SAFE:
        return "SAFE"
    if buffer >= LIQ_BUFFER_CAUTION:
        return "CAUTION"
    return "DANGER"


def account_impact_pct(pnl_usd: float, balance: float) -> float:
    bal = float(balance)
    if bal <= 0:
        return 0.0
    return round(float(pnl_usd) / bal * 100.0, 2)


def pnl_for_point_move(
    side: str,
    entry: float,
    point_move: float,
    balance: float,
    *,
    margin_percent: float | None = None,
    leverage: float | None = None,
) -> dict[str, float]:
    sizing = standard_sizing(balance, entry, margin_percent=margin_percent, leverage=leverage)
    qty = sizing["quantity"]
    exit_price = float(entry) + float(point_move) if side == "BUY" else float(entry) - float(point_move)
    pnl = calculate_pnl(side, entry, exit_price, qty)
    roe = calculate_roe(pnl, sizing["margin_used"])
    impact = account_impact_pct(pnl, balance)
    return {
        "pnl_usd": pnl,
        "roe_pct": roe,
        "account_impact_pct": impact,
        "quantity": qty,
        "margin_used": sizing["margin_used"],
    }


def build_risk_matrix_row(
    symbol: str,
    price: float,
    balance: float,
) -> dict[str, Any]:
    price = float(price)
    row: dict[str, Any] = {
        "symbol": symbol,
        "current_price": round(price, 2),
        "balance": round(float(balance), 2),
        "margin_percent": trading_margin_percent(),
        "leverage": trading_leverage(),
    }
    for pct in RISK_MATRIX_LOSS_PCTS:
        key = f"risk_{int(pct)}pct_distance"
        row[key] = point_distance_for_account_impact(price, pct)
    for pct in RISK_MATRIX_GAIN_PCTS:
        key = f"reward_{int(pct)}pct_distance"
        row[key] = point_distance_for_account_impact(price, pct)
    return row


@dataclass
class SignalRiskProfile:
    leverage: float
    margin_percent: float
    balance: float
    structure_stop_loss: float
    structure_take_profit: float
    applied_stop_loss: float
    applied_take_profit: float
    structure_risk_points: float
    structure_reward_points: float
    risk_points: float
    risk_pct: float
    reward_points: float
    reward_pct: float
    risk_reward: float
    liquidation_price: float
    distance_to_liquidation: float
    liquidation_pct: float
    liq_buffer: float
    liq_status: LiqStatus
    margin_used: float
    quantity: float
    risk_usd: float
    reward_usd: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict())


def build_signal_risk_profile(
    *,
    side: str,
    entry: float,
    structure_stop_loss: float,
    structure_take_profit: float,
    balance: float,
    margin_percent: float | None = None,
    leverage: float | None = None,
    applied_risk_pct: float = APPLIED_RISK_ACCOUNT_PCT,
    applied_reward_pct: float = APPLIED_REWARD_ACCOUNT_PCT,
) -> SignalRiskProfile:
    margin_pct = float(margin_percent if margin_percent is not None else trading_margin_percent())
    lev = float(leverage if leverage is not None else trading_leverage())
    entry = float(entry)

    applied_sl = price_level_for_account_impact(
        side, entry, applied_risk_pct, gain=False, margin_percent=margin_pct, leverage=lev
    )
    applied_tp = price_level_for_account_impact(
        side, entry, applied_reward_pct, gain=True, margin_percent=margin_pct, leverage=lev
    )

    struct_risk_pts = risk_points(side, entry, structure_stop_loss)
    struct_reward_pts = reward_points(side, entry, structure_take_profit)
    applied_risk_pts = risk_points(side, entry, applied_sl)
    applied_reward_pts = reward_points(side, entry, applied_tp)

    sizing = standard_sizing(balance, entry, margin_percent=margin_pct, leverage=lev)
    qty = sizing["quantity"]
    margin_used = sizing["margin_used"]

    risk_usd = abs(calculate_pnl(side, entry, applied_sl, qty))
    reward_usd = abs(calculate_pnl(side, entry, applied_tp, qty))
    rr = round(applied_reward_pts / applied_risk_pts, 2) if applied_risk_pts > 0 else 0.0

    liq = liquidation_price(side, entry, lev)
    liq_dist = distance_to_liquidation(side, entry, lev)
    buffer = liq_buffer_ratio(side, entry, applied_sl, lev)

    return SignalRiskProfile(
        leverage=lev,
        margin_percent=margin_pct,
        balance=round(float(balance), 2),
        structure_stop_loss=float(structure_stop_loss),
        structure_take_profit=float(structure_take_profit),
        applied_stop_loss=applied_sl,
        applied_take_profit=applied_tp,
        structure_risk_points=struct_risk_pts,
        structure_reward_points=struct_reward_pts,
        risk_points=applied_risk_pts,
        risk_pct=applied_risk_pct,
        reward_points=applied_reward_pts,
        reward_pct=applied_reward_pct,
        risk_reward=rr,
        liquidation_price=liq,
        distance_to_liquidation=liq_dist,
        liquidation_pct=liquidation_pct(lev),
        liq_buffer=buffer,
        liq_status=liq_status_from_buffer(buffer),
        margin_used=margin_used,
        quantity=qty,
        risk_usd=risk_usd,
        reward_usd=reward_usd,
    )


def missed_opportunity_metrics(
    side: str,
    entry: float,
    exit_price: float,
    balance: float,
    *,
    margin_percent: float | None = None,
    leverage: float | None = None,
) -> dict[str, float]:
    from app.paper_trader import realized_points

    pts = realized_points(side, entry, exit_price)
    sizing = standard_sizing(balance, entry, margin_percent=margin_percent, leverage=leverage)
    pnl = calculate_pnl(side, entry, float(exit_price), sizing["quantity"])
    roe = calculate_roe(pnl, sizing["margin_used"])
    impact = account_impact_pct(pnl, balance)
    return {
        "points": pts,
        "pnl_usd": pnl,
        "roe_pct": roe,
        "account_impact_pct": impact,
        "quantity": sizing["quantity"],
        "margin_used": sizing["margin_used"],
    }


def enforce_trade_params(
    leverage: float | None,
    margin_percent: float | None,
) -> tuple[float, float]:
    lev = float(leverage if leverage is not None else trading_leverage())
    pct = float(margin_percent if margin_percent is not None else trading_margin_percent())
    return lev, pct
