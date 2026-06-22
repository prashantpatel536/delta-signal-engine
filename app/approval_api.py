"""API routes for signal approval workflow."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query

from app.api import resolve_delta_symbol
from app.config import settings
from app.models import (
    ApproveTradeRequest,
    ApproveTradeResponse,
    MissedOpportunityAnalytics,
    MissedOpportunityAuditItem,
    MissedOpportunityDebugResponse,
    MissedOpportunitySummary,
    MissedOpportunitySymbolNet,
    SignalStatistics,
    StoredSignal,
    StoredSignalsResponse,
)
from app.market_data import store
from app.services.missed_opportunity_service import missed_opportunity_service
from app.services.paper_trading_service import PaperTradingService
from app.services.signal_service import SignalService

router = APIRouter(tags=["approval"])
signal_service = SignalService()
paper_service = PaperTradingService()
logger = logging.getLogger(__name__)


def _to_stored(record: dict) -> StoredSignal:
    return StoredSignal.from_record(record)


def _resolve_signal_timeframe(
    timeframe: str | None,
    signal_timeframe: str | None,
) -> str | None:
    """Signal TF filter — prefers explicit signal_timeframe query param."""
    return signal_timeframe or timeframe


@router.get("/pending-signals", response_model=StoredSignalsResponse)
def get_pending_signals(
    symbol: str | None = Query(default=None, description="Filter by symbol e.g. ETH or ETHUSDT"),
    timeframe: str | None = Query(default=None, description="Filter by signal timeframe 1m/5m/15m/1h"),
    signal_timeframe: str | None = Query(default=None, description="Signal timeframe (alias)"),
) -> StoredSignalsResponse:
    delta_symbol = resolve_delta_symbol(symbol) if symbol else None
    tf = _resolve_signal_timeframe(timeframe, signal_timeframe)
    if tf is not None and tf not in settings.timeframes:
        raise HTTPException(status_code=400, detail=f"Invalid signal timeframe '{tf}'")
    records = signal_service.get_pending_signals(
        symbol=delta_symbol,
        timeframe=tf,
    )
    signals = [_to_stored(item) for item in records]
    return StoredSignalsResponse(signals=signals, count=len(signals))


@router.get("/pending-signals/latest", response_model=StoredSignal | None)
def get_latest_pending_signal(
    symbol: str | None = Query(default=None),
    timeframe: str | None = Query(default=None),
    signal_timeframe: str | None = Query(default=None),
) -> StoredSignal | None:
    delta_symbol = resolve_delta_symbol(symbol) if symbol else None
    tf = _resolve_signal_timeframe(timeframe, signal_timeframe)
    if tf is not None and tf not in settings.timeframes:
        raise HTTPException(status_code=400, detail=f"Invalid signal timeframe '{tf}'")
    record = signal_service.get_latest_pending_signal(
        symbol=delta_symbol,
        timeframe=tf,
    )
    return _to_stored(record) if record else None


@router.get("/signal-history", response_model=StoredSignalsResponse)
def get_signal_history(
    status: str | None = Query(
        default=None,
        description="Filter by status: PENDING, APPROVED, REJECTED, EXPIRED",
    ),
    symbol: str | None = Query(default=None, description="Filter by symbol e.g. ETH or ETHUSDT"),
    timeframe: str | None = Query(default=None, description="Filter by signal timeframe"),
    signal_timeframe: str | None = Query(default=None, description="Signal timeframe (alias)"),
) -> StoredSignalsResponse:
    if status is not None and status.upper() not in {
        "PENDING",
        "APPROVED",
        "REJECTED",
        "EXPIRED",
        "TP_HIT",
        "SL_HIT",
        "MISSED_WINNER",
        "MISSED_LOSER",
    }:
        raise HTTPException(status_code=400, detail=f"Invalid status filter: {status}")
    tf = _resolve_signal_timeframe(timeframe, signal_timeframe)
    if tf is not None and tf not in settings.timeframes:
        raise HTTPException(status_code=400, detail=f"Invalid signal timeframe '{tf}'")
    filter_status = status.upper() if status else None
    delta_symbol = resolve_delta_symbol(symbol) if symbol else None
    records = signal_service.get_signal_history(
        filter_status,
        symbol=delta_symbol,
        timeframe=tf,
    )
    signals = [_to_stored(item) for item in records]
    return StoredSignalsResponse(signals=signals, count=len(signals))


def _symbol_net_models(items: list[dict]) -> list[MissedOpportunitySymbolNet]:
    return [MissedOpportunitySymbolNet(**item) for item in items]


@router.get("/missed-opportunities/summary", response_model=MissedOpportunitySummary)
def get_missed_summary() -> MissedOpportunitySummary:
    raw = missed_opportunity_service.get_summary()
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


@router.get("/debug/missed-opportunities", response_model=MissedOpportunityDebugResponse)
def debug_missed_opportunities() -> MissedOpportunityDebugResponse:
    audit = missed_opportunity_service.get_debug_audit()
    return MissedOpportunityDebugResponse(
        total_missed=int(audit["total_missed"]),
        total_winners=int(audit["total_winners"]),
        total_losers=int(audit["total_losers"]),
        totals_consistent=bool(audit["totals_consistent"]),
        duplicate_outcome_count=int(audit["duplicate_outcome_count"]),
        monitoring_active=int(audit["monitoring_active"]),
        gross_missed_profit=float(audit["gross_missed_profit"]),
        gross_missed_loss=float(audit["gross_missed_loss"]),
        net_missed_profit=float(audit["net_missed_profit"]),
        signals=[MissedOpportunityAuditItem(**item) for item in audit["signals"]],
    )


@router.get("/missed-opportunities/analytics", response_model=MissedOpportunityAnalytics)
def get_missed_analytics(
    period: str = Query(default="today", pattern="^(today|7d|30d)$"),
) -> MissedOpportunityAnalytics:
    data = missed_opportunity_service.get_analytics(period)
    return MissedOpportunityAnalytics(**data)


@router.get("/signal/{signal_id}", response_model=StoredSignal)
def get_signal(signal_id: int) -> StoredSignal:
    record = signal_service.get_signal(signal_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Signal {signal_id} not found")
    return _to_stored(record)


@router.post("/signal/{signal_id}/approve", response_model=StoredSignal)
def approve_signal(signal_id: int) -> StoredSignal:
    try:
        record = signal_service.approve_signal(signal_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    logger.info("Signal Approved: id=%s %s %s", record["id"], record["symbol"], record["side"])
    return _to_stored(record)


@router.post("/signal/{signal_id}/reject", response_model=StoredSignal)
def reject_signal(signal_id: int) -> StoredSignal:
    try:
        record = signal_service.reject_signal(signal_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _to_stored(record)


@router.post("/signal/{signal_id}/approve-trade", response_model=ApproveTradeResponse)
def approve_and_trade(signal_id: int, body: ApproveTradeRequest) -> ApproveTradeResponse:
    try:
        signal_record, position = signal_service.approve_and_execute(
            signal_id,
            leverage=body.leverage,
            margin_percent=body.margin_percent,
            stop_loss=body.stop_loss,
            take_profit=body.take_profit,
            prices=store.get_latest_prices(),
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    logger.info(
        "Signal Approved + Trade Opened: signal=%s position=%s %s",
        signal_record["id"],
        position["id"],
        position["symbol"],
    )
    from app.models import Position

    return ApproveTradeResponse(
        signal=_to_stored(signal_record),
        position=Position(**position),
    )


@router.get("/signals/latest", response_model=StoredSignal | None)
def get_latest_signal() -> StoredSignal | None:
    record = signal_service.get_latest_signal()
    return _to_stored(record) if record else None


@router.get("/signal-statistics", response_model=SignalStatistics)
def get_signal_statistics() -> SignalStatistics:
    counts = signal_service.get_statistics()
    missed = missed_opportunity_service.get_summary()
    return SignalStatistics(
        total=counts.get("TOTAL", 0),
        pending=counts.get("PENDING", 0),
        approved=counts.get("APPROVED", 0),
        rejected=counts.get("REJECTED", 0),
        expired=counts.get("EXPIRED", 0),
        missed_opportunities=int(missed["missed_opportunities"]),
        missed_winners=int(missed["missed_winners"]),
        missed_losers=int(missed["missed_losers"]),
        gross_missed_profit=float(missed["gross_missed_profit"]),
        gross_missed_loss=float(missed["gross_missed_loss"]),
        net_missed_profit=float(missed["net_missed_profit"]),
        monitoring=int(missed["monitoring"]),
        by_symbol=_symbol_net_models(missed.get("by_symbol", [])),
    )
