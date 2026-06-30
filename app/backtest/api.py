"""Backtest REST API — strategy-agnostic."""

from __future__ import annotations

import csv
import io
import json
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from app.backtest.candle_store import SUPPORTED_RESOLUTIONS, get_candles
from app.backtest.exports import build_excel_bytes, build_pdf_bytes
from app.backtest.registry import ensure_registry, get, list_strategies
from app.backtest.repository import get_run, list_runs, save_run

router = APIRouter(prefix="/backtest/api", tags=["backtest"])


class CompareRequest(BaseModel):
    run_ids: list[int] = Field(..., min_length=2, max_length=10)


@router.get("/candles")
def api_candles(
    symbol: str,
    timeframe: str = "5m",
    start_ts: int = Query(..., description="Unix start (seconds)"),
    end_ts: int = Query(..., description="Unix end (seconds)"),
) -> dict[str, Any]:
    if timeframe not in SUPPORTED_RESOLUTIONS:
        raise HTTPException(400, f"Unsupported timeframe '{timeframe}'")
    from datetime import datetime, timezone

    start_date = datetime.fromtimestamp(start_ts, tz=timezone.utc).strftime("%Y-%m-%d")
    end_date = datetime.fromtimestamp(end_ts, tz=timezone.utc).strftime("%Y-%m-%d")
    df = get_candles(symbol, timeframe, start_date, end_date)
    if df.empty:
        return {"candles": []}
    mask = (df["time"] >= start_ts) & (df["time"] <= end_ts)
    subset = df.loc[mask]
    candles = [
        {
            "time": int(r.time),
            "open": float(r.open),
            "high": float(r.high),
            "low": float(r.low),
            "close": float(r.close),
            "volume": float(r.volume),
        }
        for r in subset.itertuples(index=False)
    ]
    return {"candles": candles}


@router.post("/compare")
def api_compare_runs(body: CompareRequest) -> dict[str, Any]:
    runs = []
    for rid in body.run_ids:
        row = get_run(rid)
        if not row:
            raise HTTPException(404, f"Run {rid} not found")
        runs.append({
            "id": row["id"],
            "name": row.get("name"),
            "strategy_id": row.get("strategy_id"),
            "symbol": row.get("symbol"),
            "timeframe": row.get("timeframe"),
            "start_date": row.get("start_date"),
            "end_date": row.get("end_date"),
            "created_at": row.get("created_at"),
            "statistics": row.get("statistics"),
            "params": row.get("params"),
        })
    return {"runs": runs}


class BacktestRequest(BaseModel):
    strategy_id: str
    symbol: str | None = None
    timeframe: str = "5m"
    start_date: str
    end_date: str
    initial_capital: float = Field(default=1000.0, gt=0)
    leverage: float = Field(default=25.0, gt=0)
    position_size_pct: float = Field(default=50.0, ge=1, le=100)
    commission_pct: float = Field(default=0.05, ge=0)
    slippage_pct: float = Field(default=0.02, ge=0)
    use_current_settings: bool = True
    settings: dict[str, Any] | None = None
    save: bool = False
    name: str | None = None


@router.get("/strategies")
def api_list_strategies() -> dict[str, Any]:
    ensure_registry()
    return {"strategies": list_strategies()}


@router.get("/timeframes")
def api_timeframes() -> dict[str, Any]:
    return {"timeframes": list(SUPPORTED_RESOLUTIONS)}


@router.get("/settings/{strategy_id}")
def api_strategy_settings(strategy_id: str) -> dict[str, Any]:
    ensure_registry()
    try:
        strat = get(strategy_id)
    except KeyError:
        raise HTTPException(404, f"Unknown strategy '{strategy_id}'")
    return {"strategy_id": strategy_id, "settings": strat.get_settings()}


@router.post("/run")
def api_run_backtest(body: BacktestRequest) -> dict[str, Any]:
    ensure_registry()
    try:
        strat = get(body.strategy_id)
    except KeyError:
        raise HTTPException(404, f"Unknown strategy '{body.strategy_id}'")

    config = body.model_dump()
    config["symbol"] = body.symbol or strat.default_symbol
    try:
        result = strat.run_backtest(config)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(500, f"Backtest failed: {exc}") from exc

    run_id = None
    if body.save:
        run_id = save_run(result, name=body.name)
    return {"run_id": run_id, "result": result}


@router.get("/runs")
def api_list_runs(strategy_id: str | None = None, limit: int = 50) -> dict[str, Any]:
    return {"runs": list_runs(strategy_id, limit)}


@router.get("/runs/{run_id}")
def api_get_run(run_id: int) -> dict[str, Any]:
    row = get_run(run_id)
    if not row:
        raise HTTPException(404, "Run not found")
    return row


@router.get("/runs/{run_id}/export.csv")
def export_csv(run_id: int) -> StreamingResponse:
    row = get_run(run_id)
    if not row:
        raise HTTPException(404, "Run not found")
    fields = [
        "trade_num", "side", "entry_time", "exit_time", "entry_price", "exit_price",
        "price_move_pct", "pnl_usd", "bars_held", "exit_reason", "mfe_pct", "mae_pct",
    ]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
    w.writeheader()
    for tr in row.get("trades", []):
        w.writerow(tr)
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="backtest-{run_id}.csv"'},
    )


@router.get("/runs/{run_id}/export.json")
def export_json(run_id: int) -> Response:
    row = get_run(run_id)
    if not row:
        raise HTTPException(404, "Run not found")
    return Response(
        content=json.dumps(row, indent=2, default=str),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="backtest-{run_id}.json"'},
    )


@router.get("/runs/{run_id}/export.xlsx")
def export_xlsx(run_id: int) -> Response:
    row = get_run(run_id)
    if not row:
        raise HTTPException(404, "Run not found")
    data = build_excel_bytes(row)
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="backtest-{run_id}.xlsx"'},
    )


@router.get("/runs/{run_id}/export.pdf")
def export_pdf(run_id: int) -> Response:
    row = get_run(run_id)
    if not row:
        raise HTTPException(404, "Run not found")
    return Response(
        content=build_pdf_bytes(row),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="backtest-{run_id}.pdf"'},
    )
