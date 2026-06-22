"""Pushover notification API routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.models import PushoverStatusResponse, PushoverTestResponse
from app.services.pushover_service import pushover_service

router = APIRouter(tags=["pushover"])


@router.get("/pushover/status", response_model=PushoverStatusResponse)
def get_pushover_status() -> PushoverStatusResponse:
    return PushoverStatusResponse(**pushover_service.status())


@router.post("/pushover/test", response_model=PushoverTestResponse)
def send_pushover_test() -> PushoverTestResponse:
    if not pushover_service.is_configured():
        raise HTTPException(
            status_code=503,
            detail=(
                "Pushover not configured — set PUSHOVER_ENABLED=true, "
                "PUSHOVER_USER_KEY, and PUSHOVER_APP_TOKEN in .env"
            ),
        )
    result = pushover_service.send_test()
    if not result["ok"]:
        raise HTTPException(
            status_code=502,
            detail=result["message"],
        )
    return PushoverTestResponse(**result)
