"""API routes for BTC Strategy Optimizer (research only)."""

from __future__ import annotations

import csv
import io
import json
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from app.research.btc_optimizer_service import btc_optimizer_service

router = APIRouter(prefix="/research/btc-optimizer", tags=["research"])


class RangeInput(BaseModel):
    start: float
    end: float
    step: float


class OptimizerStartRequest(BaseModel):
    start_date: str = Field(description="YYYY-MM-DD")
    end_date: str = Field(description="YYYY-MM-DD")
    gap: RangeInput
    min_sl: RangeInput
    max_sl: RangeInput
    initial_capital: float = 1000.0
    commission_pct: float = 0.0
    leverage: float = 25.0
    margin_percent: float = 50.0
    timeframe: str = "5m"


def _request_dict(body: OptimizerStartRequest) -> dict[str, Any]:
    return {
        "start_date": body.start_date,
        "end_date": body.end_date,
        "gap_start": body.gap.start,
        "gap_end": body.gap.end,
        "gap_step": body.gap.step,
        "min_sl_start": body.min_sl.start,
        "min_sl_end": body.min_sl.end,
        "min_sl_step": body.min_sl.step,
        "max_sl_start": body.max_sl.start,
        "max_sl_end": body.max_sl.end,
        "max_sl_step": body.max_sl.step,
        "initial_capital": body.initial_capital,
        "commission_pct": body.commission_pct,
        "leverage": body.leverage,
        "margin_percent": body.margin_percent,
        "timeframe": body.timeframe,
    }


@router.post("/start")
def start_optimization(body: OptimizerStartRequest) -> dict[str, Any]:
    req = _request_dict(body)
    from app.research.btc_optimizer_service import build_param_combinations

    total = len(build_param_combinations(req))
    if total <= 0:
        raise HTTPException(status_code=400, detail="No parameter combinations in ranges")
    if total > 50_000:
        raise HTTPException(status_code=400, detail=f"Too many combinations ({total}). Narrow ranges.")
    job_id = btc_optimizer_service.start(req)
    return {"job_id": job_id, "total_combinations": total}


@router.post("/stop/{job_id}")
def stop_optimization(job_id: str) -> dict[str, Any]:
    if not btc_optimizer_service.stop(job_id):
        raise HTTPException(status_code=404, detail="Job not found")
    return {"job_id": job_id, "status": "stopped"}


@router.get("/progress/{job_id}")
def optimization_progress(job_id: str) -> dict[str, Any]:
    progress = btc_optimizer_service.get_progress(job_id)
    if not progress:
        raise HTTPException(status_code=404, detail="Job not found")
    return progress


@router.get("/results/{job_id}")
def optimization_results(
    job_id: str,
    include_trades: bool = Query(default=False),
) -> dict[str, Any]:
    payload = btc_optimizer_service.get_results(job_id, include_trades=include_trades)
    if not payload:
        raise HTTPException(status_code=404, detail="Job not found")
    return payload


@router.get("/results/{job_id}/trades/{result_index}")
def optimization_trades(job_id: str, result_index: int) -> dict[str, Any]:
    trades = btc_optimizer_service.get_trades(job_id, result_index)
    if trades is None:
        raise HTTPException(status_code=404, detail="Job or result index not found")
    return {"job_id": job_id, "result_index": result_index, "trades": trades}


@router.get("/heatmap/{job_id}")
def optimization_heatmap(
    job_id: str,
    gap: float = Query(..., description="Gap filter % to slice"),
    metric: str = Query(default="profit_factor"),
) -> dict[str, Any]:
    data = btc_optimizer_service.heatmap(job_id, gap_filter_pct=gap, metric=metric)
    if not data:
        raise HTTPException(status_code=404, detail="Job not found or no data for gap")
    return data


@router.get("/export/{job_id}/csv")
def export_csv(job_id: str) -> StreamingResponse:
    payload = btc_optimizer_service.get_results(job_id, include_trades=False)
    if not payload:
        raise HTTPException(status_code=404, detail="Job not found")
    rows = payload.get("results") or []
    if not rows:
        raise HTTPException(status_code=400, detail="No results to export")

    buffer = io.StringIO()
    fields = [
        "gap_filter_pct", "min_sl_points", "max_sl_points",
        "profit_factor", "return_pct", "max_drawdown_pct", "win_rate",
        "trade_count", "avg_winner", "avg_loser", "score",
    ]
    writer = csv.DictWriter(buffer, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="btc-optimizer-{job_id}.csv"'},
    )


@router.get("/export/{job_id}/json")
def export_json(job_id: str) -> Response:
    payload = btc_optimizer_service.get_results(job_id, include_trades=True)
    if not payload:
        raise HTTPException(status_code=404, detail="Job not found")
    return Response(
        content=json.dumps(payload, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="btc-optimizer-{job_id}.json"'},
    )
