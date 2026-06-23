"""Admin maintenance endpoints."""

from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.models import MissedOpportunitySummary, RecalculateMissedResponse
from app.services.missed_opportunity_recalc_service import missed_opportunity_recalc_service

router = APIRouter(prefix="/admin", tags=["admin"])


def _summary_model(raw: dict[str, Any]) -> MissedOpportunitySummary:
    from app.approval_api import _symbol_net_models

    return MissedOpportunitySummary(
        missed_opportunities=int(raw["missed_opportunities"]),
        missed_winners=int(raw["missed_winners"]),
        missed_losers=int(raw["missed_losers"]),
        gross_missed_profit=float(raw["gross_missed_profit"]),
        gross_missed_loss=float(raw["gross_missed_loss"]),
        net_missed_profit=float(raw["net_missed_profit"]),
        monitoring=int(raw["monitoring"]),
        totals_valid=bool(raw["totals_valid"]),
        by_symbol=_symbol_net_models(raw.get("by_symbol", [])),
    )


@router.post("/recalculate-missed-opportunities")
async def recalculate_missed_opportunities() -> StreamingResponse:
    """Replay missed-opportunity exits and stream progress as NDJSON."""

    async def stream() -> AsyncIterator[bytes]:
        loop = asyncio.get_running_loop()
        progress_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

        def progress(current: int, total: int, signal_id: int) -> None:
            loop.call_soon_threadsafe(
                progress_queue.put_nowait,
                {
                    "type": "progress",
                    "current": current,
                    "total": total,
                    "signal_id": signal_id,
                },
            )

        task = asyncio.create_task(
            asyncio.to_thread(
                missed_opportunity_recalc_service.recalculate_all,
                progress,
            )
        )

        while True:
            if task.done() and progress_queue.empty():
                break
            try:
                item = await asyncio.wait_for(progress_queue.get(), timeout=0.2)
                yield (json.dumps(item) + "\n").encode("utf-8")
            except asyncio.TimeoutError:
                continue

        payload = await task
        summary = _summary_model(payload["summary"])
        response = RecalculateMissedResponse(
            ok=True,
            recalculated=payload["recalculated"],
            changed=payload["changed"],
            unchanged=payload["unchanged"],
            summary=summary,
        )
        yield (json.dumps({"type": "complete", **response.model_dump()}) + "\n").encode(
            "utf-8"
        )

    return StreamingResponse(stream(), media_type="application/x-ndjson")
