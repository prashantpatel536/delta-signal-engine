"""Risk matrix and trading assumptions API."""

from __future__ import annotations

from fastapi import APIRouter

from app.market_data import store
from app.models import RiskMatrixResponse, RiskSettingsResponse
from app.repositories.account_repository import AccountRepository
from app.risk_engine import (
    DEFAULT_LEVERAGE,
    DEFAULT_MARGIN_PERCENT,
    build_risk_matrix_row,
    trading_leverage,
    trading_margin_percent,
)

router = APIRouter(tags=["risk"])


@router.get("/risk/settings", response_model=RiskSettingsResponse)
def get_risk_settings() -> RiskSettingsResponse:
    return RiskSettingsResponse(
        leverage=trading_leverage(),
        margin_percent=trading_margin_percent(),
        default_leverage=DEFAULT_LEVERAGE,
        default_margin_percent=DEFAULT_MARGIN_PERCENT,
    )


@router.get("/risk/matrix", response_model=RiskMatrixResponse)
def get_risk_matrix() -> RiskMatrixResponse:
    account = AccountRepository().get_account()
    balance = float(account.get("balance") or 1000.0)
    prices = store.get_latest_prices()
    rows = []
    for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        price = prices.get(symbol)
        if price is None:
            continue
        rows.append(build_risk_matrix_row(symbol, price, balance))
    return RiskMatrixResponse(
        balance=round(balance, 2),
        leverage=trading_leverage(),
        margin_percent=trading_margin_percent(),
        rows=rows,
    )
