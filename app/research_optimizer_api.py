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
    debug: bool = False


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
        "debug": body.debug,
    }


@router.post("/preview")
def preview_combinations(body: OptimizerStartRequest) -> dict[str, Any]:
    req = _request_dict(body)
    return btc_optimizer_service.preview_grid(req)


@router.post("/start")
def start_optimization(body: OptimizerStartRequest) -> dict[str, Any]:
    req = _request_dict(body)
    plan = btc_optimizer_service.preview_grid(req)
    total = plan["final_tested_combinations"]
    if total <= 0:
        raise HTTPException(status_code=400, detail="No parameter combinations in ranges")
    if total > 50_000:
        raise HTTPException(status_code=400, detail=f"Too many combinations ({total}). Narrow ranges.")
    started = btc_optimizer_service.start(req)
    return {**started, "grid_plan": plan}


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
    include_curves: bool = Query(default=False),
) -> dict[str, Any]:
    payload = btc_optimizer_service.get_results(
        job_id,
        include_trades=include_trades,
        include_curves=include_curves,
    )
    if not payload:
        raise HTTPException(status_code=404, detail="Job not found")
    return payload


@router.get("/results/{job_id}/detail/{result_index}")
def optimization_result_detail(job_id: str, result_index: int) -> dict[str, Any]:
    detail = btc_optimizer_service.get_result_detail(job_id, result_index)
    if not detail:
        raise HTTPException(status_code=404, detail="Job or result index not found")
    return detail


@router.get("/results/{job_id}/trades/{result_index}")
def optimization_trades(job_id: str, result_index: int) -> dict[str, Any]:
    payload = btc_optimizer_service.get_trades(job_id, result_index)
    if payload is None:
        raise HTTPException(status_code=404, detail="Job or result index not found")
    return payload


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


_TOP_FIELDS = [
    "rank", "gap_filter_pct", "min_sl_points", "max_sl_points",
    "profit_factor", "return_pct", "max_drawdown_pct", "win_rate",
    "trade_count", "score",
]

_RESULT_FIELDS = [
    "gap_filter_pct", "min_sl_points", "max_sl_points",
    "profit_factor", "return_pct", "max_drawdown_pct", "win_rate",
    "trade_count", "total_trades", "winning_trades", "losing_trades",
    "loss_rate", "net_profit_usd", "avg_winner", "avg_loser",
    "avg_r_multiple", "expectancy", "avg_trade", "avg_duration_seconds",
    "largest_winner", "largest_loser", "longest_winning_streak",
    "longest_losing_streak", "score", "rankable", "rank_disqualify_reason",
]


@router.get("/export/{job_id}/csv")
def export_csv(job_id: str) -> StreamingResponse:
    payload = btc_optimizer_service.get_results(job_id, include_trades=False)
    if not payload:
        raise HTTPException(status_code=404, detail="Job not found")
    rows = payload.get("results") or []
    if not rows:
        raise HTTPException(status_code=400, detail="No results to export")

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=_RESULT_FIELDS, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="btc-optimizer-{job_id}.csv"'},
    )


@router.get("/export/{job_id}/top-csv")
def export_top_csv(job_id: str) -> StreamingResponse:
    payload = btc_optimizer_service.get_results(job_id, include_trades=False)
    if not payload:
        raise HTTPException(status_code=404, detail="Job not found")
    rows = payload.get("top_results") or []
    if not rows:
        raise HTTPException(status_code=400, detail="No rankable results to export")

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=_TOP_FIELDS, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="btc-optimizer-top20-{job_id}.csv"'},
    )


@router.get("/export/{job_id}/trades-csv")
def export_trades_csv(job_id: str) -> StreamingResponse:
    job = btc_optimizer_service.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    buffer = io.StringIO()
    fields = [
        "gap_filter_pct", "min_sl_points", "max_sl_points", "trade_num",
        "entry_time", "exit_time", "side", "entry", "exit_price",
        "stop_loss", "take_profit", "exit_reason", "profit_usd",
        "r_multiple", "duration_seconds",
    ]
    writer = csv.DictWriter(buffer, fieldnames=fields)
    writer.writeheader()

    for row in sorted(job.results, key=lambda r: float(r.get("score") or 0), reverse=True):
        base = {
            "gap_filter_pct": row.get("gap_filter_pct"),
            "min_sl_points": row.get("min_sl_points"),
            "max_sl_points": row.get("max_sl_points"),
        }
        for trade in row.get("trades") or []:
            writer.writerow({**base, **trade})

    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="btc-optimizer-trades-{job_id}.csv"'},
    )


@router.get("/export/{job_id}/json")
def export_json(job_id: str) -> Response:
    payload = btc_optimizer_service.get_results(job_id, include_trades=True, include_curves=True)
    if not payload:
        raise HTTPException(status_code=404, detail="Job not found")
    return Response(
        content=json.dumps(payload, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="btc-optimizer-{job_id}.json"'},
    )
