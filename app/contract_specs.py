"""Delta Exchange USDT-margined perpetual contract specifications."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Live values from GET https://api.delta.exchange/v2/products (contract_value field)
DELTA_CONTRACT_SIZES: dict[str, float] = {
    "BTCUSDT": 0.001,  # 1 contract = 0.001 BTC
    "ETHUSDT": 0.01,   # 1 contract = 0.01 ETH
    "SOLUSDT": 1.0,    # 1 contract = 1 SOL
}

# Stop-loss distance limits in price points (after HH50/LL50 structure)
SL_DISTANCE_LIMITS: dict[str, tuple[float, float]] = {
    "BTCUSDT": (300.0, 700.0),
    "ETHUSDT": (15.0, 45.0),
    "SOLUSDT": (0.8, 3.0),
}

MIN_TARGET_ROE_PCT = 50.0
MIN_RISK_REWARD = 2.0


@dataclass(frozen=True)
class ContractSpec:
    symbol: str
    contract_size: float
    min_sl_points: float
    max_sl_points: float

    @property
    def contract_notional(self) -> str:
        return f"{self.contract_size} base asset per contract"


def get_contract_spec(symbol: str) -> ContractSpec:
    size = DELTA_CONTRACT_SIZES.get(symbol, 0.001)
    min_sl, max_sl = SL_DISTANCE_LIMITS.get(symbol, (0.0, float("inf")))
    return ContractSpec(
        symbol=symbol,
        contract_size=float(size),
        min_sl_points=float(min_sl),
        max_sl_points=float(max_sl),
    )


def contracts_from_notional(
    target_notional: float,
    entry: float,
    symbol: str,
) -> int:
    """Whole contracts for a target notional (floored)."""
    spec = get_contract_spec(symbol)
    entry = float(entry)
    if entry <= 0 or target_notional <= 0:
        return 0
    unit_notional = spec.contract_size * entry
    if unit_notional <= 0:
        return 0
    return int(target_notional // unit_notional)


def sizing_from_contracts(
    contracts: int,
    entry: float,
    symbol: str,
    leverage: float,
) -> dict[str, float]:
    """Position metrics from a contract count."""
    spec = get_contract_spec(symbol)
    entry = float(entry)
    lev = max(float(leverage), 1.0)
    contracts = max(int(contracts), 0)
    base_qty = round(contracts * spec.contract_size, 8)
    position_value = round(base_qty * entry, 2)
    margin_used = round(position_value / lev, 2)
    return {
        "contracts": float(contracts),
        "contract_size": spec.contract_size,
        "quantity": base_qty,
        "position_value": position_value,
        "margin_used": margin_used,
    }


def contract_sizing_summary(symbol: str) -> dict[str, Any]:
    spec = get_contract_spec(symbol)
    return {
        "symbol": symbol,
        "contract_size": spec.contract_size,
        "min_sl_points": spec.min_sl_points,
        "max_sl_points": spec.max_sl_points,
    }
