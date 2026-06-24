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


@router.get("/trade-history")
def debug_trade_history() -> dict[str, Any]:
    """Diagnose /trade-history failures row-by-row (safe on VPS)."""
    from app.models import ClosedTrade
    from app.paper_trader import build_closed_trade_payload
    from app.services.paper_trading_service import PaperTradingService

    service = PaperTradingService()
    rows: list[dict[str, Any]] = []
    for raw in service.repository.list_closed():
        row: dict[str, Any] = {
            "id": raw.get("id"),
            "symbol": raw.get("symbol"),
            "exit_reason": raw.get("exit_reason"),
            "opened_at": raw.get("opened_at"),
            "closed_at": raw.get("closed_at"),
        }
        try:
            payload = build_closed_trade_payload(raw)
            row["payload_ok"] = True
        except Exception as exc:
            row["payload_ok"] = False
            row["model_ok"] = False
            row["error"] = f"payload: {type(exc).__name__}: {exc}"
            rows.append(row)
            continue
        try:
            ClosedTrade(**payload)
            row["model_ok"] = True
        except Exception as exc:
            row["model_ok"] = False
            row["error"] = f"model: {type(exc).__name__}: {exc}"
        rows.append(row)
    return {
        "closed_count": len(rows),
        "payload_ok_count": sum(1 for r in rows if r.get("payload_ok")),
        "model_ok_count": sum(1 for r in rows if r.get("model_ok")),
        "rows": rows,
    }
