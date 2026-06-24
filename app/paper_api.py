"""API routes for paper trading (virtual positions)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException

from app.market_data import store
from app.models import (
    ClosedTrade,
    ClosedTradesResponse,
    OpenPaperTradeRequest,
    OpenPosition,
    OpenPositionsResponse,
    PaperAccount,
    PaperStatistics,
    PaperTradePreview,
    PerformanceAnalytics,
    Position,
    PositionEvent,
    PositionEventsResponse,
    UpdatePositionLevelsRequest,
)
from app.services.paper_trading_service import InsufficientMarginError, PaperTradingService

router = APIRouter(tags=["paper"])
paper_service = PaperTradingService()
logger = logging.getLogger(__name__)


def _prices() -> dict[str, float]:
    return store.get_latest_prices()


@router.get("/paper/account", response_model=PaperAccount)
def get_paper_account() -> PaperAccount:
    summary = paper_service.get_account_summary(_prices())
    return PaperAccount(**summary)


@router.post("/paper/preview", response_model=PaperTradePreview)
def preview_paper_trade(body: OpenPaperTradeRequest) -> PaperTradePreview:
    preview = paper_service.preview_trade(
        symbol=body.symbol,
        entry=body.entry,
        margin_percent=body.margin_percent,
        leverage=body.leverage,
        side=body.side,
        stop_loss=body.stop_loss,
        take_profit=body.take_profit,
        prices=_prices(),
    )
    return PaperTradePreview(**preview)


@router.post("/paper/open", response_model=Position)
def open_paper_trade(body: OpenPaperTradeRequest) -> Position:
    try:
        position = paper_service.open_paper_trade(
            symbol=body.symbol,
            side=body.side,
            entry=body.entry,
            margin_percent=body.margin_percent,
            leverage=body.leverage,
            stop_loss=body.stop_loss,
            take_profit=body.take_profit,
            signal_id=body.signal_id,
            prices=_prices(),
        )
    except InsufficientMarginError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    logger.info(
        "Trade Opened: id=%s %s %s margin=%s lev=%sx qty=%s",
        position["id"],
        position["symbol"],
        position["side"],
        position["margin_used"],
        position["leverage"],
        position["quantity"],
    )
    return Position(**position)


@router.get("/open-positions", response_model=OpenPositionsResponse)
def get_open_positions() -> OpenPositionsResponse:
    records = paper_service.get_open_positions_enriched(_prices())
    positions = [OpenPosition(**item) for item in records]
    return OpenPositionsResponse(positions=positions, count=len(positions))


@router.patch("/position/{position_id}/levels", response_model=Position)
def update_position_levels(position_id: int, body: UpdatePositionLevelsRequest) -> Position:
    try:
        updated = paper_service.update_position_levels(
            position_id,
            stop_loss=body.stop_loss,
            take_profit=body.take_profit,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Position(**updated)


@router.post("/position/{position_id}/breakeven", response_model=Position)
def move_stop_to_breakeven(position_id: int) -> Position:
    try:
        updated = paper_service.move_stop_to_breakeven(position_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return Position(**updated)


@router.get("/position/{position_id}/events", response_model=PositionEventsResponse)
def get_position_events(position_id: int) -> PositionEventsResponse:
    try:
        events = paper_service.get_position_events(position_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    items = [PositionEvent(**event) for event in events]
    return PositionEventsResponse(events=items, count=len(items))


@router.post("/position/{position_id}/close", response_model=Position)
def close_position(position_id: int) -> Position:
    position = paper_service.repository.get_by_id(position_id)
    if position is None:
        raise HTTPException(status_code=404, detail=f"Position {position_id} not found")

    prices = _prices()
    current = prices.get(position["symbol"])
    if current is None:
        raise HTTPException(
            status_code=503,
            detail=f"No live price available for {position['symbol']}",
        )

    try:
        closed = paper_service.close_manually(position_id, current)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    logger.info(
        "Trade Closed: id=%s %s manual pnl=%s",
        closed["id"],
        closed["symbol"],
        closed.get("pnl"),
    )
    return Position(**closed)


@router.get("/trade-history")
def get_trade_history() -> dict[str, Any]:
    """Return closed trades as plain JSON (avoids response-model 500s on legacy rows)."""
    trades: list[dict[str, Any]] = []
    try:
        for item in paper_service.get_closed_trades():
            try:
                trades.append(ClosedTrade.model_validate(item).model_dump(mode="json"))
            except Exception as exc:
                logger.warning(
                    "Skipping closed trade id=%s in /trade-history: %s",
                    item.get("id"),
                    exc,
                )
    except Exception as exc:
        logger.exception("/trade-history failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"trades": trades, "count": len(trades)}


@router.get("/paper-statistics", response_model=PaperStatistics)
def get_paper_statistics() -> PaperStatistics:
    stats = paper_service.get_statistics()
    return PaperStatistics(**stats)


@router.get("/paper/performance", response_model=PerformanceAnalytics)
def get_paper_performance() -> PerformanceAnalytics:
    analytics = paper_service.get_performance_analytics(_prices())
    return PerformanceAnalytics(**analytics)
