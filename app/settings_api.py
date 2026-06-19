"""Settings API — signal timeframe and notification tests."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.models import (
    EmailStatusResponse,
    EmailTestResponse,
    SignalTimeframeResponse,
    SignalTimeframeUpdate,
)
from app.services.email_service import email_service
from app.services.runtime_settings import get_signal_timeframe, set_signal_timeframe

router = APIRouter(tags=["settings"])


@router.get("/settings/signal-timeframe", response_model=SignalTimeframeResponse)
def read_signal_timeframe() -> SignalTimeframeResponse:
    tf = get_signal_timeframe()
    return SignalTimeframeResponse(signal_timeframe=tf)


@router.put("/settings/signal-timeframe", response_model=SignalTimeframeResponse)
def update_signal_timeframe(body: SignalTimeframeUpdate) -> SignalTimeframeResponse:
    try:
        tf = set_signal_timeframe(body.signal_timeframe)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SignalTimeframeResponse(signal_timeframe=tf)


@router.get("/email/status", response_model=EmailStatusResponse)
def get_email_status() -> EmailStatusResponse:
    return EmailStatusResponse(**email_service.status())


def _send_email_test() -> EmailTestResponse:
    if not email_service.is_configured():
        raise HTTPException(
            status_code=503,
            detail=(
                "Email not configured — set SMTP_SERVER, SMTP_PORT, SMTP_USERNAME, "
                "SMTP_PASSWORD, ALERT_EMAIL_TO in .env"
            ),
        )
    result = email_service.send_test()
    if not result["ok"]:
        raise HTTPException(status_code=502, detail="Email test failed — check server logs")
    return EmailTestResponse(**result)


@router.post("/test-email", response_model=EmailTestResponse)
def send_test_email() -> EmailTestResponse:
    return _send_email_test()


@router.post("/email/test", response_model=EmailTestResponse, include_in_schema=False)
def send_email_test_legacy() -> EmailTestResponse:
    return _send_email_test()
