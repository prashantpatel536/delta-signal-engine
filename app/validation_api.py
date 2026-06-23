"""Validation report API."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

from app.models import ValidationReportResponse
from app.services.audit_service import audit_service
from app.services.validation_service import validation_service

router = APIRouter(tags=["validation"])


@router.get("/validation/report", response_model=ValidationReportResponse)
def get_validation_report() -> ValidationReportResponse:
    return ValidationReportResponse(**validation_service.build_report())


@router.get("/validation/trade-audit")
def get_trade_audit() -> dict:
    return audit_service.validate_trades()


@router.get("/validation/strategy-simulation")
def get_strategy_simulation() -> dict:
    return audit_service.strategy_account_simulation()


@router.get("/validation/missed-simulation")
def get_missed_simulation() -> dict:
    return audit_service.missed_opportunity_simulation()


@router.get("/validation/full-audit")
def get_full_audit() -> dict:
    return audit_service.build_full_audit_report()


@router.get("/validation/full-audit.md", response_class=PlainTextResponse)
def get_full_audit_markdown() -> str:
    return audit_service.render_audit_markdown()
