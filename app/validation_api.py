"""Validation report API."""

from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi.responses import PlainTextResponse

from app.models import ValidationReportResponse
from app.services.audit_service import audit_service
from app.services.validation_service import validation_service
from app.delta_contract_verification import verify_all_contract_specs

router = APIRouter(tags=["validation"])


@router.get("/validation/report", response_model=ValidationReportResponse)
def get_validation_report() -> ValidationReportResponse:
    return ValidationReportResponse(**validation_service.build_report())


@router.get("/validation/trade-audit")
def get_trade_audit() -> dict:
    return audit_service.validate_trades()


@router.get("/validation/trade-replay")
def get_trade_replay(limit: int = Query(default=20, ge=1, le=100)) -> dict:
    return audit_service.trade_replay_validation(limit=limit)


@router.get("/validation/contract-specs")
def get_contract_specs() -> dict:
    return verify_all_contract_specs()


@router.get("/validation/missed-by-symbol")
def get_missed_by_symbol() -> dict:
    return audit_service.missed_profit_by_symbol()


@router.get("/validation/strategy-reality")
def get_strategy_reality() -> dict:
    return audit_service.strategy_reality_check()


@router.get("/validation/portfolio-simulator")
def get_portfolio_simulator(
    starting_capital: float = Query(default=1000.0, gt=0),
) -> dict:
    return audit_service.portfolio_simulator(starting_capital=starting_capital)


@router.get("/validation/strategy-simulation")
def get_strategy_simulation() -> dict:
    return audit_service.strategy_account_simulation()


@router.get("/validation/missed-simulation")
def get_missed_simulation() -> dict:
    return audit_service.missed_opportunity_simulation()


@router.get("/validation/full-audit")
def get_full_audit() -> dict:
    return audit_service.build_full_audit_report()


@router.get("/validation/round2-audit")
def get_round2_audit() -> dict:
    return audit_service.build_round2_audit_report()


@router.get("/validation/full-audit.md", response_class=PlainTextResponse)
def get_full_audit_markdown() -> str:
    return audit_service.render_audit_markdown()


@router.get("/validation/round2-audit.md", response_class=PlainTextResponse)
def get_round2_audit_markdown() -> str:
    return audit_service.render_round2_markdown()
