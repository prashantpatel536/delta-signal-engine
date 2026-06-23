"""System diagnostics API for localhost vs VPS parity verification."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body

from app.models import SystemDebugCompareResponse, SystemDebugFullResponse, SystemDebugResponse
from app.services.system_debug_service import system_debug_service

router = APIRouter(prefix="/api/debug", tags=["debug"])


@router.get("/system", response_model=SystemDebugResponse)
def get_system_debug() -> SystemDebugResponse:
    return SystemDebugResponse(**system_debug_service.core_system_payload())


@router.get("/system/full", response_model=SystemDebugFullResponse)
def get_system_debug_full() -> SystemDebugFullResponse:
    return SystemDebugFullResponse(**system_debug_service.full_diagnostics())


@router.post("/system/compare", response_model=SystemDebugCompareResponse)
def compare_system_debug(
    remote: dict[str, Any] = Body(
        ...,
        description="JSON from remote GET /api/debug/system/full or /api/debug/system",
    ),
) -> SystemDebugCompareResponse:
    return SystemDebugCompareResponse(**system_debug_service.compare_with_remote(remote))
