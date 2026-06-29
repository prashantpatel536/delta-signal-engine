"""API routes for Signal Probability Optimizer (research only)."""

from __future__ import annotations

import time
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.research.candle_cache import fetch_candles_range, months_back_range
from app.research.signal_probability import SignalProbabilityParams, analyze_signal_probability

router = APIRouter(prefix="/research/signal-probability", tags=["research"])


class SignalProbabilityRequest(BaseModel):
    symbol: str = "SOLUSDT"
    timeframe: str = "5m"
    months_back: int = Field(default=6, ge=1, le=36)
    sma_length: int = Field(default=84, ge=5, le=500)
    target_points: float = Field(default=3.0, gt=0)
    stop_loss_points: float = Field(default=1.0, gt=0)
    direction: Literal["BUY", "SELL", "BOTH"] = "BOTH"


@router.post("/analyze")
def analyze(body: SignalProbabilityRequest) -> dict[str, Any]:
    """Run SMA crossover probability analysis. Candles are cached server-side."""
    params = SignalProbabilityParams(
        symbol=body.symbol.upper(),
        timeframe=body.timeframe,
        months_back=body.months_back,
        sma_length=body.sma_length,
        target_points=body.target_points,
        stop_loss_points=body.stop_loss_points,
        direction=body.direction,
    )
    start_date, end_date = months_back_range(params.months_back)

    t0 = time.perf_counter()
    try:
        candles = fetch_candles_range(
            params.symbol,
            start_date,
            end_date,
            resolution=params.timeframe,
            use_cache=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    report = analyze_signal_probability(candles, params)
    elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
    report["meta"]["analysis_ms"] = elapsed_ms
    report["meta"]["cached_window"] = {"start_date": start_date, "end_date": end_date}
    return report
