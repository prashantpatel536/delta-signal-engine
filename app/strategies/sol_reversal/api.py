"""HTTP API for SOL Reversal Engine (isolated from BTC routes)."""

from __future__ import annotations

import csv
import io
import json
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from app.strategies.sol_reversal.debug import (
    MAX_DEBUG_TRADES,
    clear_debug_events,
    debug_summary,
    explain_signal_at_index,
    list_debug_events,
    log_debug_event,
)
from app.strategies.sol_reversal.engine import sol_engine
from app.strategies.sol_reversal.market import sol_market
from app.strategies.sol_reversal.repositories import SolEngineRepository, SolSettingsRepository

router = APIRouter(prefix="/sol/api", tags=["sol-reversal"])


class SettingsUpdate(BaseModel):
    min_red_candles: int | None = None
    max_green_candles: int | None = None
    strong_candle_enabled: bool | None = None
    strong_candle_atr_mult: float | None = None
    atr_filter_enabled: bool | None = None
    atr_minimum: float | None = None
    atr_period: int | None = None
    take_profit_pct: float | None = None
    stop_loss_pct: float | None = None
    lock_profit_enabled: bool | None = None
    lock_trigger_pct: float | None = None
    lock_distance_pct: float | None = None
    leverage: float | None = None
    position_size_pct: float | None = Field(default=None, ge=1, le=100)
    debug_mode: bool | None = None
    debug_log_bar_evals: bool | None = None
    show_raw_ha_conditions: bool | None = None


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


@router.get("/debug/summary")
def get_debug_summary() -> dict[str, Any]:
    return {
        "summary": debug_summary(),
        "settings": {
            "debug_mode": bool(sol_engine.settings().get("debug_mode")),
            "debug_log_bar_evals": bool(sol_engine.settings().get("debug_log_bar_evals")),
        },
    }


@router.get("/debug/events")
def get_debug_events(
    event_type: str | None = None,
    limit: int = 500,
) -> dict[str, Any]:
    return {
        "events": list_debug_events(event_type=event_type, limit=min(limit, 2000)),
        "summary": debug_summary(),
    }


@router.get("/debug/trades")
def get_debug_trades() -> dict[str, Any]:
    """First 20 closed trades with paired open/signal context for TV comparison."""
    opens = {e["payload"].get("position_id"): e for e in list_debug_events(event_type="TRADE_OPEN", limit=50)}
    signals = list_debug_events(event_type="SIGNAL", limit=50)
    closes = list_debug_events(event_type="TRADE_CLOSE", limit=MAX_DEBUG_TRADES)

    paired = []
    for close_evt in reversed(closes):
        p = close_evt["payload"]
        pid = p.get("position_id")
        paired.append({
            "trade_num": p.get("trade_num"),
            "close": p,
            "open": opens.get(pid, {}).get("payload") if pid else None,
            "signal_eval": p.get("signal_eval"),
        })
    return {
        "max_trades": MAX_DEBUG_TRADES,
        "trades": paired,
        "recent_signals": signals[:20],
        "summary": debug_summary(),
    }


@router.delete("/debug/events")
def delete_debug_events() -> dict[str, Any]:
    deleted = clear_debug_events()
    return {"deleted": deleted}
