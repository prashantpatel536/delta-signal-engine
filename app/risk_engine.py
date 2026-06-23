"""Delta-style risk matrix, liquidation, and account-impact calculations."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any, Literal

from app.config import settings
from app.contract_specs import MIN_RISK_REWARD, MIN_TARGET_ROE_PCT
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
    entry = float(entry)
    margin_pct = float(margin_percent if margin_percent is not None else trading_margin_percent())
    lev = float(leverage if leverage is not None else trading_leverage())
    if entry <= 0 or margin_pct <= 0 or lev <= 0:
        return 0.0
    return round(entry * float(account_impact_pct) / (margin_pct * lev), 4)


def standard_sizing(
    balance: float,
    entry: float,
    symbol: str,
    *,
    margin_percent: float | None = None,
    leverage: float | None = None,
) -> dict[str, float]:
    margin_pct = float(margin_percent if margin_percent is not None else trading_margin_percent())
    lev = float(leverage if leverage is not None else trading_leverage())
    margin_used, position_value, quantity, contracts = calculate_from_margin_allocation(
        balance,
        margin_pct,
        lev,
        entry,
        symbol,
    )
    return {
        "balance": round(float(balance), 2),
        "margin_percent": margin_pct,
        "leverage": lev,
        "margin_used": margin_used,
        "position_value": position_value,
        "quantity": quantity,
        "contracts": float(contracts),
    }


def liquidation_price(side: str, entry: float, leverage: float | None = None) -> float:
    entry = float(entry)
    lev = max(float(leverage if leverage is not None else trading_leverage()), 1.0)
    if side == "BUY":
        return round(entry * (1.0 - 1.0 / lev), 4)
    return round(entry * (1.0 + 1.0 / lev), 4)


def distance_to_liquidation(side: str, entry: float, leverage: float | None = None) -> float:
    entry = float(entry)
    liq = liquidation_price(side, entry, leverage)
    if side == "BUY":
        return round(max(entry - liq, 0.0), 4)
    return round(max(liq - entry, 0.0), 4)


def liquidation_pct(leverage: float | None = None) -> float:
    lev = max(float(leverage if leverage is not None else trading_leverage()), 1.0)
    return round(100.0 / lev, 2)


def _liquidation_beyond_sl(side: str, entry: float, stop_loss: float, leverage: float) -> bool:
    liq = liquidation_price(side, entry, leverage)
    sl = float(stop_loss)
    if side == "BUY":
        return liq < sl
    return liq > sl


def resolve_safe_sizing(
    side: str,
    entry: float,
    stop_loss: float,
    balance: float,
    symbol: str,
    *,
    margin_percent: float | None = None,
    leverage: float | None = None,
) -> dict[str, float]:
    """
    Ensure liquidation is beyond stop loss by reducing margin allocation if needed.
    LONG: liq < SL required. SHORT: liq > SL required.
    """
    margin_pct = float(margin_percent if margin_percent is not None else trading_margin_percent())
    lev = float(leverage if leverage is not None else trading_leverage())

    for try_margin in (margin_pct, 40, 30, 25, 20, 15, 10, 5):
        if try_margin > margin_pct:
            continue
        for try_lev in (lev, 20, 15, 10, 5):
            if try_lev > lev:
                continue
            if _liquidation_beyond_sl(side, entry, stop_loss, try_lev):
                sized = standard_sizing(
                    balance,
                    entry,
                    symbol,
                    margin_percent=try_margin,
                    leverage=try_lev,
                )
                sized["margin_percent"] = try_margin
                sized["leverage"] = try_lev
                return sized

    sized = standard_sizing(balance, entry, symbol, margin_percent=5, leverage=5)
    sized["margin_percent"] = 5.0
    sized["leverage"] = 5.0
    return sized


def liq_buffer_ratio(
    side: str,
    entry: float,
    stop_loss: float,
    leverage: float | None = None,
) -> float:
    sl_dist = risk_points(side, entry, stop_loss)
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
        row[f"risk_{int(pct)}pct_distance"] = point_distance_for_account_impact(price, pct)
    for pct in RISK_MATRIX_GAIN_PCTS:
        row[f"reward_{int(pct)}pct_distance"] = point_distance_for_account_impact(price, pct)
    return row


@dataclass
class SignalRiskProfile:
    leverage: float
    margin_percent: float
    balance: float
    symbol: str
    contracts: float
    contract_size: float
    structure_stop_loss: float
    stop_loss: float
    take_profit: float
    sl_distance_points: float
    tp_distance_points: float
    risk_reward: float
    liquidation_price: float
    distance_to_liquidation: float
    liquidation_pct: float
    liq_buffer: float
    liq_status: LiqStatus
    liq_safe: bool
    margin_used: float
    position_value: float
    quantity: float
    expected_loss_usd: float
    expected_profit_usd: float
    expected_loss_pct: float
    expected_profit_pct: float
    expected_roe: float
    min_target_roe: float = MIN_TARGET_ROE_PCT
    min_risk_reward: float = MIN_RISK_REWARD

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict())


def build_signal_risk_profile(
    *,
    side: str,
    entry: float,
    stop_loss: float,
    take_profit: float,
    balance: float,
    symbol: str,
    structure_stop_loss: float | None = None,
    margin_percent: float | None = None,
    leverage: float | None = None,
) -> SignalRiskProfile:
    from app.contract_specs import get_contract_spec

    entry = float(entry)
    sl = float(stop_loss)
    tp = float(take_profit)
    struct_sl = float(structure_stop_loss if structure_stop_loss is not None else sl)

    sized = resolve_safe_sizing(
        side,
        entry,
        sl,
        balance,
        symbol,
        margin_percent=margin_percent,
        leverage=leverage,
    )
    margin_pct = sized["margin_percent"]
    lev = sized["leverage"]
    qty = sized["quantity"]
    margin_used = sized["margin_used"]
    position_value = sized["position_value"]
    contracts = sized.get("contracts", 0.0)
    spec = get_contract_spec(symbol)

    sl_dist = risk_points(side, entry, sl)
    tp_dist = reward_points(side, entry, tp)
    rr = round(tp_dist / sl_dist, 2) if sl_dist > 0 else 0.0

    loss_usd = abs(calculate_pnl(side, entry, sl, qty))
    profit_usd = abs(calculate_pnl(side, entry, tp, qty))
    roe = calculate_roe(profit_usd, margin_used) if margin_used > 0 else 0.0

    liq = liquidation_price(side, entry, lev)
    liq_dist = distance_to_liquidation(side, entry, lev)
    buffer = liq_buffer_ratio(side, entry, sl, lev)
    liq_safe = _liquidation_beyond_sl(side, entry, sl, lev)

    return SignalRiskProfile(
        leverage=lev,
        margin_percent=margin_pct,
        balance=round(float(balance), 2),
        symbol=symbol,
        contracts=contracts,
        contract_size=spec.contract_size,
        structure_stop_loss=struct_sl,
        stop_loss=sl,
        take_profit=tp,
        sl_distance_points=sl_dist,
        tp_distance_points=tp_dist,
        risk_reward=rr,
        liquidation_price=liq,
        distance_to_liquidation=liq_dist,
        liquidation_pct=liquidation_pct(lev),
        liq_buffer=buffer,
        liq_status=liq_status_from_buffer(buffer),
        liq_safe=liq_safe,
        margin_used=margin_used,
        position_value=position_value,
        quantity=qty,
        expected_loss_usd=loss_usd,
        expected_profit_usd=profit_usd,
        expected_loss_pct=account_impact_pct(-loss_usd, balance),
        expected_profit_pct=account_impact_pct(profit_usd, balance),
        expected_roe=roe,
    )


def missed_opportunity_metrics(
    side: str,
    entry: float,
    exit_price: float,
    balance: float,
    symbol: str,
    *,
    margin_percent: float | None = None,
    leverage: float | None = None,
) -> dict[str, float]:
    from app.paper_trader import realized_points

    pts = realized_points(side, entry, exit_price)
    sized = standard_sizing(
        balance,
        entry,
        symbol,
        margin_percent=margin_percent,
        leverage=leverage,
    )
    pnl = calculate_pnl(side, entry, float(exit_price), sized["quantity"])
    roe = calculate_roe(pnl, sized["margin_used"])
    impact = account_impact_pct(pnl, balance)
    return {
        "points": pts,
        "pnl_usd": pnl,
        "roe_pct": roe,
        "account_impact_pct": impact,
        "quantity": sized["quantity"],
        "contracts": sized.get("contracts", 0.0),
        "margin_used": sized["margin_used"],
        "position_value": sized["position_value"],
    }


def enforce_trade_params(
    leverage: float | None,
    margin_percent: float | None,
) -> tuple[float, float]:
    """Always apply global Delta-style assumptions (50% capital, 25× leverage)."""
    return trading_leverage(), trading_margin_percent()
