"""Telegram notification API routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.models import TelegramStatusResponse, TelegramTestResponse
from app.services.telegram_service import telegram_service

router = APIRouter(tags=["telegram"])


@router.get("/telegram/status", response_model=TelegramStatusResponse)
def get_telegram_status() -> TelegramStatusResponse:
    return TelegramStatusResponse(**telegram_service.status())


@router.post("/telegram/test", response_model=TelegramTestResponse)
def send_telegram_test() -> TelegramTestResponse:
    if not telegram_service.is_configured():
        raise HTTPException(
            status_code=503,
            detail="Telegram not configured — set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env",
        )
    result = telegram_service.send_test()
    if not result["ok"]:
        raise HTTPException(status_code=502, detail="Telegram test message failed — check server logs")
    return TelegramTestResponse(**result)
