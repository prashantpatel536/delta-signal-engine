"""Validation report API."""

from __future__ import annotations

from fastapi import APIRouter

from app.models import ValidationReportResponse
from app.services.validation_service import validation_service

router = APIRouter(tags=["validation"])


@router.get("/validation/report", response_model=ValidationReportResponse)
def get_validation_report() -> ValidationReportResponse:
    return ValidationReportResponse(**validation_service.build_report())
