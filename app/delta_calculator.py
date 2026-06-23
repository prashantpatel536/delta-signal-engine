"""
Canonical Delta Exchange USDT-margined perpetual calculations.

All portal PnL, margin, ROE, and missed-opportunity math should flow through this module.
"""

from __future__ import annotations

from typing import Any

from app.contract_specs import (
    DELTA_CONTRACT_SIZES,
    contracts_from_notional,
    get_contract_spec,
    sizing_from_contracts,
)
from app.config import settings
from app.paper_trader import (
    calculate_pnl,
    calculate_roe,
    realized_points,
)

FORMULAS: dict[str, str] = {
    "margin_budget": "margin_budget = balance × (margin_percent / 100)",
    "target_notional": "target_notional = margin_budget × leverage",
    "contracts": "contracts = floor(target_notional / (contract_size × entry_price))",
    "quantity": "quantity = contracts × contract_size",
    "position_value": "position_value = quantity × entry_price",
    "margin_used": "margin_used = position_value / leverage",
    "pnl_long": "PnL (BUY) = (exit_price − entry_price) × quantity",
    "pnl_short": "PnL (SELL) = (entry_price − exit_price) × quantity",
    "roe": "ROE % = (PnL / margin_used) × 100",
    "account_impact": "Account Impact % = (PnL / balance) × 100",
    "missed_profit": "Missed Profit $ = max(PnL, 0) when signal was not traded",
    "missed_loss": "Missed Loss $ = abs(min(PnL, 0)) when signal was not traded",
}


def _trading_leverage() -> float:
    return float(settings.default_leverage)


def _trading_margin_percent() -> float:
    return float(settings.default_margin_percent)


def _account_impact_pct(pnl_usd: float, balance: float) -> float:
    bal = float(balance)
    if bal <= 0:
        return 0.0
    return round(float(pnl_usd) / bal * 100.0, 2)


def contract_specifications() -> dict[str, dict[str, float]]:
    """Delta contract sizes used for all symbols."""
    specs: dict[str, dict[str, float]] = {}
    for symbol, size in DELTA_CONTRACT_SIZES.items():
        spec = get_contract_spec(symbol)
        specs[symbol] = {
            "contract_size": size,
            "min_sl_points": spec.min_sl_points,
            "max_sl_points": spec.max_sl_points,
        }
    return specs


def size_position(
    balance: float,
    entry: float,
    symbol: str,
    *,
    stop_loss: float | None = None,
    side: str = "BUY",
    margin_percent: float | None = None,
    leverage: float | None = None,
) -> dict[str, float]:
    """
    Delta-style position sizing: 50% capital (default) at 25× (default), whole contracts.

    When stop_loss is provided, applies liquidation-safe margin reduction (resolve_safe_sizing).
    """
    margin_pct = float(margin_percent if margin_percent is not None else _trading_margin_percent())
    lev = float(leverage if leverage is not None else _trading_leverage())
    entry = float(entry)
    balance = float(balance)

    if stop_loss is not None and stop_loss > 0:
        from app.risk_engine import resolve_safe_sizing

        sized = resolve_safe_sizing(
            side,
            entry,
            float(stop_loss),
            balance,
            symbol,
            margin_percent=margin_pct,
            leverage=lev,
        )
    else:
        margin_budget = round(balance * margin_pct / 100.0, 2)
        target_notional = round(margin_budget * lev, 2)
        contract_count = contracts_from_notional(target_notional, entry, symbol)
        sized = sizing_from_contracts(contract_count, entry, symbol, lev)
        sized = {
            "balance": round(balance, 2),
            "margin_percent": margin_pct,
            "leverage": lev,
            **sized,
        }

    return {
        "balance": round(balance, 2),
        "margin_percent": float(sized.get("margin_percent", margin_pct)),
        "leverage": float(sized.get("leverage", lev)),
        "contracts": float(sized.get("contracts", 0)),
        "contract_size": float(sized.get("contract_size", get_contract_spec(symbol).contract_size)),
        "quantity": float(sized["quantity"]),
        "position_value": float(sized["position_value"]),
        "margin_used": float(sized["margin_used"]),
    }


def compute_trade_metrics(
    *,
    side: str,
    entry: float,
    exit_price: float,
    balance: float,
    symbol: str,
    stop_loss: float | None = None,
    margin_percent: float | None = None,
    leverage: float | None = None,
) -> dict[str, float]:
    """Full trade metrics as Delta Exchange would calculate them."""
    sized = size_position(
        balance,
        entry,
        symbol,
        stop_loss=stop_loss,
        side=side,
        margin_percent=margin_percent,
        leverage=leverage,
    )
    qty = sized["quantity"]
    margin = sized["margin_used"]
    pnl = calculate_pnl(side, entry, exit_price, qty)
    pts = realized_points(side, entry, exit_price)
    roe = calculate_roe(pnl, margin)
    impact = _account_impact_pct(pnl, balance)
    return {
        "points": pts,
        "quantity": qty,
        "contracts": sized["contracts"],
        "contract_size": sized["contract_size"],
        "position_value": sized["position_value"],
        "margin_used": margin,
        "pnl_usd": pnl,
        "roe_pct": roe,
        "account_impact_pct": impact,
        "missed_profit_usd": round(max(pnl, 0.0), 2),
        "missed_loss_usd": round(abs(min(pnl, 0.0)), 2),
    }


def validate_stored_trade(
    *,
    side: str,
    entry: float,
    exit_price: float,
    quantity: float,
    margin_used: float,
    pnl: float,
    balance_at_open: float,
    symbol: str,
    stop_loss: float | None = None,
) -> dict[str, Any]:
    """Compare stored trade values against Delta calculator expectations."""
    expected = compute_trade_metrics(
        side=side,
        entry=entry,
        exit_price=exit_price,
        balance=balance_at_open,
        symbol=symbol,
        stop_loss=stop_loss,
    )
    expected_pnl_from_qty = calculate_pnl(side, entry, exit_price, quantity)
    actual_pnl = float(pnl)
    ref_pnl = expected_pnl_from_qty
    diff = abs(actual_pnl - ref_pnl)
    diff_pct = round(diff / abs(ref_pnl) * 100, 4) if ref_pnl != 0 else (0.0 if diff == 0 else 100.0)
    qty_diff_pct = 0.0
    if expected["quantity"] > 0:
        qty_diff_pct = round(
            abs(float(quantity) - expected["quantity"]) / expected["quantity"] * 100, 4
        )
    return {
        "expected_pnl": expected_pnl_from_qty,
        "expected_pnl_resized": expected["pnl_usd"],
        "actual_pnl": actual_pnl,
        "difference_usd": round(diff, 2),
        "difference_pct": diff_pct,
        "within_1pct": diff_pct < 1.0,
        "expected_quantity": expected["quantity"],
        "actual_quantity": float(quantity),
        "quantity_diff_pct": qty_diff_pct,
        "expected_margin_used": expected["margin_used"],
        "actual_margin_used": float(margin_used),
        "expected_roe_pct": expected["roe_pct"],
        "actual_roe_pct": calculate_roe(actual_pnl, float(margin_used)) if margin_used else 0.0,
    }


def sample_calculation(
    symbol: str,
    entry: float,
    exit_price: float,
    *,
    side: str = "BUY",
    balance: float = 1000.0,
    stop_loss: float | None = None,
) -> dict[str, Any]:
    """Worked example for audit documentation."""
    if stop_loss is None:
        spec = get_contract_spec(symbol)
        stop_loss = entry - spec.min_sl_points if side == "BUY" else entry + spec.min_sl_points
    metrics = compute_trade_metrics(
        side=side,
        entry=entry,
        exit_price=exit_price,
        balance=balance,
        symbol=symbol,
        stop_loss=stop_loss,
    )
    sized = size_position(balance, entry, symbol, stop_loss=stop_loss, side=side)
    return {
        "symbol": symbol,
        "side": side,
        "entry": entry,
        "exit": exit_price,
        "stop_loss": stop_loss,
        "balance": balance,
        "contract_size": sized["contract_size"],
        "contracts": sized["contracts"],
        **metrics,
    }
