"""FastAPI route definitions."""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd
from fastapi import APIRouter, HTTPException, Query

from app.candle_utils import first_last_candles, validate_candle_series
from app.config import RESOLUTION_SECONDS, settings
from app.indicators import candles_to_records, series_to_list
from app.signals import detect_all_signals
from app.market_data import delta_client, store
from app.models import (
    Candle,
    ChartDebugResponse,
    ChartResponse,
    DebugRawResponse,
    HealthResponse,
    Signal,
    SignalDiagnosticsResponse,
    SignalsResponse,
    StatusResponse,
    StoredSignal,
    WatchlistItem,
    WatchlistResponse,
)
from app.health import build_health_payload
from app.services.runtime_settings import get_signal_timeframe
from app.services.signal_service import SignalService

signal_service = SignalService()

logger = logging.getLogger(__name__)

router = APIRouter()


def _warm_chart_cache_if_needed(delta_symbol: str, timeframe: str) -> None:
    """Fetch candles on demand when in-memory cache is empty (e.g. after VPS restart)."""
    chart_data = store.get_chart_data(delta_symbol, timeframe)
    tf_data = chart_data.get(timeframe)
    if tf_data is not None and not tf_data.candles.empty:
        return

    from app.indicators import calculate_indicators

    logger.info("Chart cache miss — fetching %s %s on demand", delta_symbol, timeframe)
    try:
        candles = delta_client.fetch_candles(delta_symbol, timeframe)
        if candles.empty:
            return
        display_candles, _ = delta_client.resolve_ohlc_candles(
            candles, delta_symbol, timeframe
        )
        sma84, hh50, ll50 = calculate_indicators(display_candles)
        store.update(
            delta_symbol,
            timeframe,
            candles,
            sma84,
            hh50,
            ll50,
            None,
            display_candles=display_candles,
        )
    except Exception as exc:
        logger.warning("On-demand chart fetch failed for %s %s: %s", delta_symbol, timeframe, exc)


def resolve_delta_symbol(symbol: str) -> str:
    """Map short symbol (ETH) or full symbol (ETHUSDT) to Delta product symbol."""
    upper = symbol.upper()
    if upper in settings.symbol_map:
        return settings.symbol_map[upper]
    if upper.endswith("USDT") and upper in settings.symbol_map.values():
        return upper
    for short, delta_symbol in settings.symbol_map.items():
        if delta_symbol == upper:
            return delta_symbol
    raise HTTPException(
        status_code=404,
        detail=f"Unknown symbol '{symbol}'. Supported: {', '.join(settings.symbol_map.keys())}",
    )


def resolve_short_symbol(symbol: str) -> str:
    upper = symbol.upper()
    if upper in settings.symbol_map:
        return upper
    for short, delta_symbol in settings.symbol_map.items():
        if delta_symbol == upper:
            return short
    raise HTTPException(status_code=404, detail=f"Unknown symbol '{symbol}'")


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(**build_health_payload())


@router.get("/live-signals", response_model=SignalsResponse)
def get_signals(
    symbol: str | None = Query(default=None, description="Filter by symbol e.g. ETH or ETHUSDT"),
    timeframe: str | None = Query(default=None, description="Filter by timeframe 1m/5m/15m"),
) -> SignalsResponse:
    raw_signals = store.get_latest_signals()
    if symbol:
        delta_symbol = resolve_delta_symbol(symbol)
        raw_signals = [s for s in raw_signals if s.get("symbol") == delta_symbol]
    if timeframe:
        if timeframe not in settings.timeframes:
            raise HTTPException(status_code=400, detail=f"Invalid timeframe '{timeframe}'")
        raw_signals = [s for s in raw_signals if s.get("timeframe") == timeframe]
    signals = [Signal(**item) for item in raw_signals]
    return SignalsResponse(signals=signals, count=len(signals))


@router.get("/chart/{symbol}", response_model=ChartResponse)
def get_chart(
    symbol: str,
    timeframe: str = Query(default="5m", description="Chart candle timeframe: 1m, 5m, 15m, 1h"),
    signal_timeframe: str | None = Query(
        default=None,
        description="Signal generation timeframe (defaults to chart timeframe)",
    ),
    limit: int | None = Query(default=None, ge=1, le=500, description="Max candles to return"),
) -> ChartResponse:
    if timeframe not in settings.timeframes:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid timeframe '{timeframe}'. Supported: {', '.join(settings.timeframes)}",
        )

    signal_tf = signal_timeframe or timeframe
    if signal_tf not in settings.timeframes:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid signal_timeframe '{signal_tf}'. Supported: {', '.join(settings.timeframes)}",
        )

    delta_symbol = resolve_delta_symbol(symbol)
    short_symbol = resolve_short_symbol(symbol)
    _warm_chart_cache_if_needed(delta_symbol, timeframe)
    chart_data = store.get_chart_data(delta_symbol, timeframe)
    tf_data = chart_data.get(timeframe)

    if tf_data is None or tf_data.candles.empty:
        raise HTTPException(
            status_code=503,
            detail=(
                f"No candle data available yet for {short_symbol} ({delta_symbol}) "
                f"on {timeframe}. Wait for the background refresh cycle."
            ),
        )

    trade_df = tf_data.candles
    display_df = tf_data.display_candles
    if display_df.empty:
        display_df = trade_df.copy()

    signal_tf_data = chart_data.get(signal_tf)
    signal_ohlc_df = (
        signal_tf_data.candles
        if signal_tf_data is not None and not signal_tf_data.candles.empty
        else pd.DataFrame()
    )
    signal_sma84 = signal_tf_data.sma84 if signal_tf_data is not None else pd.Series(dtype=float)
    signal_hh50 = signal_tf_data.hh50 if signal_tf_data is not None else pd.Series(dtype=float)
    signal_ll50 = signal_tf_data.ll50 if signal_tf_data is not None else pd.Series(dtype=float)

    stored_count = len(trade_df)
    display_stored_count = len(display_df)
    chart_tail_removed = 0

    if limit is not None:
        trade_df = trade_df.tail(limit).reset_index(drop=True)
        display_df = display_df.tail(limit).reset_index(drop=True)
        sma84 = tf_data.sma84.tail(limit).reset_index(drop=True)
        hh50 = tf_data.hh50.tail(limit).reset_index(drop=True)
        ll50 = tf_data.ll50.tail(limit).reset_index(drop=True)
        chart_tail_removed = stored_count - len(trade_df)
    else:
        sma84 = tf_data.sma84
        hh50 = tf_data.hh50
        ll50 = tf_data.ll50

    sent_count = len(trade_df)
    candle_records = candles_to_records(display_df)

    logger.info(
        "Chart response %s %s: stored=%d limit=%s sent=%d (trade candles for signals/indicators)",
        delta_symbol,
        timeframe,
        stored_count,
        limit,
        sent_count,
    )

    if sent_count != len(sma84) or sent_count != len(hh50) or sent_count != len(ll50):
        logger.error(
            "Chart length mismatch %s %s: candles=%d sma=%d hh=%d ll=%d",
            delta_symbol,
            timeframe,
            sent_count,
            len(sma84),
            len(hh50),
            len(ll50),
        )

    # Chart indicators from chart timeframe candles.
    # Signal markers / review from independent signal timeframe.
    chart_signals: list[dict[str, Any]] = []
    if not signal_ohlc_df.empty:
        from app.signals import _closed_bar_slice

        closed_signals_df, closed_sma, closed_hh, closed_ll = _closed_bar_slice(
            signal_ohlc_df,
            signal_sma84,
            signal_hh50,
            signal_ll50,
        )
        if len(closed_signals_df) >= 2:
            chart_signals = detect_all_signals(
                closed_signals_df,
                closed_sma,
                closed_hh,
                closed_ll,
                delta_symbol,
                signal_tf,
            )

    audit = validate_candle_series(trade_df, timeframe)

    last_idx = sent_count - 1 if sent_count else None
    signal_context = {
        "timeframe": timeframe,
        "chart_timeframe": timeframe,
        "signal_timeframe": signal_tf,
        "timeframe_match": timeframe == signal_tf,
        "live_price": store.get_live_price(delta_symbol),
        "last_refresh": store.last_refresh,
        "last_live_price_refresh": store.last_live_price_refresh,
        "candle_count": sent_count,
        "indicator_source": "mark_ohlc_candles",
        "signal_source": f"mark_ohlc_candles_{signal_tf}",
        "chart_display_source": "mark_ohlc_candles",
        "symbol": delta_symbol,
    }
    if last_idx is not None and last_idx >= 0:
        signal_context["last_sma84"] = (
            None if pd.isna(sma84.iloc[last_idx]) else float(sma84.iloc[last_idx])
        )
        signal_context["last_hh50"] = (
            None if pd.isna(hh50.iloc[last_idx]) else float(hh50.iloc[last_idx])
        )
        signal_context["last_ll50"] = (
            None if pd.isna(ll50.iloc[last_idx]) else float(ll50.iloc[last_idx])
        )
        signal_context["last_candle_time"] = int(trade_df["time"].iloc[last_idx])

    quality_signal = signal_tf_data.latest_signal if signal_tf_data else None
    active_stored: dict[str, Any] | None = None
    if quality_signal and quality_signal.get("timeframe") == signal_tf:
        sig_last_idx = len(signal_ohlc_df) - 1 if len(signal_ohlc_df) else None
        candle_time = quality_signal.get("candle_time")
        sig_idx = sig_last_idx
        if candle_time is not None and not signal_ohlc_df.empty:
            matches = signal_ohlc_df.index[signal_ohlc_df["time"] == candle_time].tolist()
            if matches:
                sig_idx = matches[0]
        if sig_idx is not None and sig_idx >= 0 and signal_tf == get_signal_timeframe():
            hh_val = signal_hh50.iloc[sig_idx]
            ll_val = signal_ll50.iloc[sig_idx]
            if not pd.isna(hh_val) and not pd.isna(ll_val):
                active_stored = signal_service.resolve_runtime_signal(
                    quality_signal,
                    float(hh_val),
                    float(ll_val),
                )
                if active_stored:
                    signal_context["active_signal"] = {
                        "id": active_stored["id"],
                        "status": active_stored["status"],
                        "side": active_stored["side"],
                        "timeframe": active_stored["timeframe"],
                        "signal_timeframe": active_stored.get("signal_timeframe", active_stored["timeframe"]),
                        "entry": active_stored["entry"],
                        "stop_loss": active_stored["stop_loss"],
                        "take_profit": active_stored["take_profit"],
                        "risk_reward": active_stored["risk_reward"],
                        "created_at": active_stored["created_at"],
                    }
                    signal_context["signal_quality"] = signal_service.stored_to_quality(
                        active_stored,
                        signal_tf,
                    )

    enriched_signals = signal_service.enrich_chart_signals(
        chart_signals,
        delta_symbol,
        signal_tf,
    )

    return ChartResponse(
        symbol=delta_symbol,
        timeframe=timeframe,
        candles=candle_records,
        sma84=series_to_list(sma84),
        hh50=series_to_list(hh50),
        ll50=series_to_list(ll50),
        signals=[Signal(**item) for item in enriched_signals],
        candle_audit=audit,
        candle_counts={
            "stored_in_cache": stored_count,
            "display_stored": display_stored_count,
            "sent_to_frontend": sent_count,
            "chart_limit": limit,
            "chart_tail_removed": chart_tail_removed,
            "volume_filter_removed": 0,
            "indicator_rows_removed": 0,
            "mark_enrichment_enabled": settings.enrich_flat_candles_with_mark,
        },
        signal_context=signal_context,
    )


@router.get("/watchlist", response_model=WatchlistResponse)
def get_watchlist(
    timeframe: str = Query(default="5m", description="Timeframe for prices and signals"),
) -> WatchlistResponse:
    if timeframe not in settings.timeframes:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid timeframe '{timeframe}'. Supported: {', '.join(settings.timeframes)}",
        )

    interval = RESOLUTION_SECONDS[timeframe]
    bars_24h = max(1, (24 * 3600) // interval)
    items: list[WatchlistItem] = []

    for short, delta_symbol in settings.symbol_map.items():
        chart_data = store.get_chart_data(delta_symbol, timeframe)
        tf_data = chart_data.get(timeframe)
        if tf_data is None or tf_data.candles.empty:
            continue

        candles = tf_data.candles
        close = float(candles["close"].iloc[-1])
        lookback = min(len(candles) - 1, bars_24h)
        ref = float(candles["close"].iloc[-1 - lookback])
        change = close - ref
        change_pct = (change / ref * 100.0) if ref else 0.0

        latest = tf_data.latest_signal
        signal_side = latest["signal"] if latest else None

        items.append(
            WatchlistItem(
                symbol=delta_symbol,
                short_symbol=short,
                price=round(close, 2),
                change=round(change, 2),
                change_pct=round(change_pct, 2),
                signal=signal_side,
            )
        )

    return WatchlistResponse(timeframe=timeframe, items=items)


@router.get("/debug/chart/{symbol}/{timeframe}", response_model=ChartDebugResponse)
def debug_chart(symbol: str, timeframe: str) -> ChartDebugResponse:
    """Return last candle and indicator values from trade candles for Delta comparison."""
    if timeframe not in settings.timeframes:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid timeframe '{timeframe}'. Supported: {', '.join(settings.timeframes)}",
        )

    delta_symbol = resolve_delta_symbol(symbol)
    chart_data = store.get_chart_data(delta_symbol, timeframe)
    tf_data = chart_data.get(timeframe)

    if tf_data is None or tf_data.candles.empty:
        raise HTTPException(
            status_code=503,
            detail=f"No cached data for {delta_symbol} {timeframe}",
        )

    trade_df = tf_data.candles
    display_df = tf_data.display_candles if not tf_data.display_candles.empty else trade_df
    audit = validate_candle_series(trade_df, timeframe)

    last_trade, _ = first_last_candles(trade_df)
    last_display, _ = first_last_candles(display_df)

    idx = len(trade_df) - 1
    sma_val = tf_data.sma84.iloc[idx]
    hh_val = tf_data.hh50.iloc[idx]
    ll_val = tf_data.ll50.iloc[idx]

    return ChartDebugResponse(
        symbol=delta_symbol,
        timeframe=timeframe,
        last_candle=Candle(**last_display) if last_display else None,
        last_candle_trade=Candle(**last_trade) if last_trade else None,
        sma84=None if pd.isna(sma_val) else round(float(sma_val), 2),
        hh50=None if pd.isna(hh_val) else round(float(hh_val), 2),
        ll50=None if pd.isna(ll_val) else round(float(ll_val), 2),
        candle_count=len(trade_df),
        expected_interval_seconds=audit["expected_interval_seconds"],
        candle_audit=audit,
    )


@router.get("/debug/raw/{symbol}", response_model=DebugRawResponse)
def debug_raw_candles(
    symbol: str,
    timeframe: str = Query(default="5m", description="Candle timeframe: 1m, 5m, 15m"),
    limit: int | None = Query(
        default=None,
        ge=1,
        le=500,
        description="Optional chart limit to simulate /chart tail slice",
    ),
) -> DebugRawResponse:
    """
    Live-fetch candles from Delta and report pipeline counts at each stage.

    Compares live fetch vs cached store vs optional chart limit slice.
    """
    if timeframe not in settings.timeframes:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid timeframe '{timeframe}'. Supported: {', '.join(settings.timeframes)}",
        )

    delta_symbol = resolve_delta_symbol(symbol)

    try:
        live_df, live_audit = delta_client.fetch_candles_with_audit(
            delta_symbol,
            timeframe,
        )
        display_df, enrich_stats = delta_client.build_display_candles(
            live_df,
            delta_symbol,
            timeframe,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Delta API fetch failed for {delta_symbol}: {exc}",
        ) from exc

    cached_data = store.get_chart_data(delta_symbol, timeframe).get(timeframe)
    cached_df = cached_data.candles if cached_data else None
    cached_count = len(cached_df) if cached_df is not None and not cached_df.empty else 0
    cached_first, cached_last = (
        first_last_candles(cached_df) if cached_count else (None, None)
    )

    chart_sent_count = cached_count
    chart_tail_removed = 0
    if limit is not None and cached_count:
        chart_sent_count = min(limit, cached_count)
        chart_tail_removed = cached_count - chart_sent_count

    pipeline = {
        **live_audit,
        **enrich_stats,
        "cached_count": cached_count,
        "cached_first_candle": cached_first,
        "cached_last_candle": cached_last,
        "chart_limit": limit,
        "chart_sent_count": chart_sent_count,
        "chart_tail_removed": chart_tail_removed,
        "display_flat_after": int(validate_candle_series(display_df, timeframe)["flat_count"])
        if not display_df.empty
        else 0,
        "checks": {
            "dropna_in_normalize": live_audit.get("dropna_removed", 0),
            "duplicate_in_normalize": live_audit.get("duplicate_removed", 0),
            "volume_filter_removed": 0,
            "fetch_tail_removed": live_audit.get("fetch_tail_removed", 0),
            "chart_api_tail_removed": chart_tail_removed,
            "indicator_rows_removed": 0,
            "trade_flat_before_enrich": enrich_stats.get("flat_before", 0),
            "enriched_from_mark": enrich_stats.get("enriched_from_mark", 0),
            "display_flat_after_enrich": enrich_stats.get("flat_after", 0),
            "gap_fill_used": False,
        },
    }

    first, last = first_last_candles(display_df)
    processed_count = live_audit.get("after_fetch_tail_count", len(live_df))

    return DebugRawResponse(
        symbol=delta_symbol,
        timeframe=timeframe,
        raw_candle_count=live_audit.get("raw_api_count", 0),
        processed_candle_count=processed_count,
        first_candle=Candle(**first) if first else None,
        last_candle=Candle(**last) if last else None,
        pipeline=pipeline,
    )


@router.get("/debug/signals/data", response_model=SignalDiagnosticsResponse)
def debug_signals_data(
    symbol: str = Query(default="ETH", description="Symbol e.g. ETH or ETHUSDT"),
    timeframe: str = Query(default="5m", description="Timeframe 1m/5m/15m/1h"),
) -> SignalDiagnosticsResponse:
    if timeframe not in settings.timeframes:
        raise HTTPException(status_code=400, detail=f"Invalid timeframe '{timeframe}'")

    delta_symbol = resolve_delta_symbol(symbol)
    short_symbol = resolve_short_symbol(symbol)

    chart_data = store.get_chart_data(delta_symbol, timeframe)
    tf_data = chart_data.get(timeframe)

    sma_val = hh_val = ll_val = None
    candle_count = 0
    last_candle_time = None
    runtime_signal = None

    if tf_data and not tf_data.candles.empty:
        trade_df = tf_data.candles
        candle_count = len(trade_df)
        last_candle_time = int(trade_df.iloc[-1]["time"])
        sma_raw = tf_data.sma84.iloc[-1]
        hh_raw = tf_data.hh50.iloc[-1]
        ll_raw = tf_data.ll50.iloc[-1]
        sma_val = None if pd.isna(sma_raw) else round(float(sma_raw), 2)
        hh_val = None if pd.isna(hh_raw) else round(float(hh_raw), 2)
        ll_val = None if pd.isna(ll_raw) else round(float(ll_raw), 2)
        if tf_data.latest_signal:
            runtime_signal = Signal(**tf_data.latest_signal)

    latest_record = signal_service.get_latest_signal()
    latest_stored = StoredSignal.from_record(latest_record) if latest_record else None

    filtered = signal_service.get_signal_history(symbol=delta_symbol, timeframe=timeframe)
    signal_time = None
    if filtered:
        signal_time = filtered[0].get("created_at")

    pending_blocked = False
    if runtime_signal:
        side = runtime_signal.signal
        pending_blocked = signal_service.repository.has_pending(
            delta_symbol, timeframe, side
        )

    return SignalDiagnosticsResponse(
        symbol=delta_symbol,
        timeframe=timeframe,
        latest_stored_signal=latest_stored,
        runtime_signal=runtime_signal,
        signal_time=signal_time or (runtime_signal.timestamp if runtime_signal else None),
        sma84=sma_val,
        hh50=hh_val,
        ll50=ll_val,
        last_candle_time=last_candle_time,
        candle_count=candle_count,
        duplicate_pending_blocked=pending_blocked,
        indicator_source="trade_candles",
    )


@router.get("/status", response_model=StatusResponse)
def get_status() -> StatusResponse:
    return StatusResponse(
        symbols=list(settings.symbol_map.keys()),
        timeframes=list(settings.timeframes),
        delta_symbols=dict(settings.symbol_map),
        refresh_interval_seconds=settings.refresh_interval_seconds,
        candle_limit=settings.candle_limit,
        last_refresh=store.last_refresh,
    )
