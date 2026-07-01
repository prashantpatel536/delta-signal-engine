"""SOL Reversal optimizer + validation API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.strategies.sol_reversal.engine_validation import validate_engine_parity
from app.strategies.sol_reversal.optimizer_service import sol_optimizer_service

router = APIRouter(prefix="/sol/api/optimizer", tags=["sol-optimizer"])


class ParamRange(BaseModel):
    start: float
    end: float
    step: float


class OptimizerStartRequest(BaseModel):
    start_date: str
    end_date: str
    symbol: str = "SOLUSDT"
    timeframe: str = "5m"
    initial_capital: float = Field(default=1000.0, gt=0)
    commission_pct: float = Field(default=0.05, ge=0)
    slippage_pct: float = Field(default=0.02, ge=0)
    workers: int = Field(default=2, ge=1, le=8)
    base_settings: dict[str, Any] | None = None
    ranges: dict[str, ParamRange]


class ValidationRequest(BaseModel):
    start_date: str
    end_date: str
    symbol: str = "SOLUSDT"
    timeframe: str = "5m"
    initial_capital: float = Field(default=1000.0, gt=0)
    commission_pct: float = Field(default=0.05, ge=0)
    slippage_pct: float = Field(default=0.02, ge=0)
    use_current_settings: bool = True
    settings: dict[str, Any] | None = None


def _optimizer_request(body: OptimizerStartRequest) -> dict[str, Any]:
    return {
        **body.model_dump(),
        "ranges": {k: v.model_dump() for k, v in body.ranges.items()},
    }


@router.post("/preview")
def preview_grid(body: OptimizerStartRequest) -> dict[str, Any]:
    return sol_optimizer_service.preview(_optimizer_request(body))


@router.post("/start")
def start_optimization(body: OptimizerStartRequest) -> dict[str, Any]:
    req = _optimizer_request(body)
    plan = sol_optimizer_service.preview(req)
    if not plan.get("combinations"):
        raise HTTPException(status_code=400, detail="No parameter combinations in ranges")
    return sol_optimizer_service.start(req)


@router.post("/stop/{job_id}")
def stop_optimization(job_id: str) -> dict[str, Any]:
    if not sol_optimizer_service.stop(job_id):
        raise HTTPException(status_code=404, detail="Job not found")
    return {"stopped": True, "job_id": job_id}


@router.get("/progress/{job_id}")
def optimization_progress(job_id: str) -> dict[str, Any]:
    progress = sol_optimizer_service.get_progress(job_id)
    if not progress:
        raise HTTPException(status_code=404, detail="Job not found")
    return progress


@router.get("/results/{job_id}")
def optimization_results(job_id: str, include_trades: bool = False) -> dict[str, Any]:
    payload = sol_optimizer_service.get_results(job_id, include_trades=include_trades)
    if not payload:
        raise HTTPException(status_code=404, detail="Job not found")
    return payload


@router.get("/results/{job_id}/trades/{result_index}")
def optimization_trades(job_id: str, result_index: int) -> dict[str, Any]:
    payload = sol_optimizer_service.get_trades(job_id, result_index)
    if not payload:
        raise HTTPException(status_code=404, detail="Result not found")
    return payload


@router.post("/validate")
def validate_engines(body: ValidationRequest) -> dict[str, Any]:
    """
    Validation Mode: run one parameter set through Paper Strategy Engine
    and Optimizer Engine, then compare trades/equity/PnL.
    """
    result = validate_engine_parity(body.model_dump())
    if not result["ok"]:
        print(result["report"])
    return result
