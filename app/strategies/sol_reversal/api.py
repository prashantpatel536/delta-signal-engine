"""HTTP API for SOL Reversal Engine (isolated from BTC routes)."""

from __future__ import annotations

import csv
import io
import json
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from app.strategies.sol_reversal.engine import sol_engine
from app.strategies.sol_reversal.market import sol_market
from app.strategies.sol_reversal.repositories import SolEngineRepository, SolSettingsRepository

router = APIRouter(prefix="/sol/api", tags=["sol-reversal"])


class SettingsUpdate(BaseModel):
    min_red_candles: int | None = None
    max_green_candles: int | None = None
    strong_candle_enabled: bool | None = None
    strong_candle_body_pct: float | None = None
    atr_filter_enabled: bool | None = None
    atr_multiplier: float | None = None
    atr_minimum: float | None = None
    take_profit_pct: float | None = None
    stop_loss_pct: float | None = None
    lock_profit_enabled: bool | None = None
    lock_trigger_pct: float | None = None
    lock_distance_pct: float | None = None
    leverage: float | None = None
    position_size_pct: float | None = Field(default=None, ge=1, le=100)


@router.get("/status")
def get_status() -> dict[str, Any]:
    return sol_engine.dashboard_state()


@router.get("/chart")
def get_chart(bars: int = 200) -> dict[str, Any]:
    return sol_market.chart_payload(bars=min(bars, 500))


@router.get("/settings")
def get_settings() -> dict[str, Any]:
    return SolSettingsRepository().get_all()


@router.patch("/settings")
def patch_settings(body: SettingsUpdate) -> dict[str, Any]:
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No settings provided")
    return SolSettingsRepository().update(updates)


@router.get("/trades")
def trade_history(limit: int = 500) -> dict[str, Any]:
    rows = sol_engine.paper.positions.list_closed(limit)
    return {"trades": rows}


@router.get("/logs")
def engine_logs(limit: int = 100) -> dict[str, Any]:
    return {"logs": SolEngineRepository().recent_logs(limit)}


@router.get("/research/equity")
def equity_curve() -> dict[str, Any]:
    settings = sol_engine.settings()
    initial = float(settings.get("initial_capital", 1000))
    rows = sol_engine.paper.positions.list_closed(5000)
    curve = [{"time": None, "equity": initial}]
    equity = initial
    for r in reversed(rows):
        equity += float(r.get("pnl_usd") or 0)
        curve.append({"time": r.get("closed_at"), "equity": round(equity, 2)})
    return {"equity_curve": curve}


@router.get("/export/trades.csv")
def export_trades_csv() -> StreamingResponse:
    rows = sol_engine.paper.positions.list_closed(10000)
    fields = [
        "opened_at", "closed_at", "side", "entry", "exit_price",
        "pnl_pct", "pnl_usd", "bars_held", "exit_reason", "mfe_pct", "mae_pct",
    ]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow(r)
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="sol-reversal-trades.csv"'},
    )


@router.get("/export/data.json")
def export_json() -> Response:
    payload = {
        "status": sol_engine.dashboard_state(),
        "trades": sol_engine.paper.positions.list_closed(10000),
        "settings": sol_engine.settings(),
    }
    return Response(
        content=json.dumps(payload, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="sol-reversal-export.json"'},
    )
